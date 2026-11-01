"""Real file SQLite import tests, no user databases, model or network."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid

from workbench.research_catalog import ResearchAccess, ResearchCatalog, ResearchError
from workbench.research_import import FORMAT, ResearchImporter, load_packet


def identifier():
    return str(uuid.uuid4())


def packet():
    return {'format': FORMAT, 'namespace': identifier(), 'items': [{
        'id': 'synthetic/report.md', 'revision': identifier(), 'previous': None,
        'title': 'Synthetic lesson', 'body': 'Reported observation; not a user fact.',
        'source_text': 'Unchanged original report.', 'source_ref': 'synthetic://author/report',
        'review_status': 'partial', 'review_scope': 'NumPy checked; PyTorch not run.'}]}


class ResearchImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'research.sqlite3'
        self.events = []
        self.writer = ResearchImporter(self.path, trace=self.events.append)
        self.catalog = self.writer.catalog
        self.packet = packet()

    def apply(self, p=None, **kwargs):
        return self.writer.apply(p or self.packet, category=kwargs.pop('category', 'encounter'), **kwargs)

    def test_batch_source_body_provenance_and_receipt_commit_together(self):
        r = self.apply()
        self.assertEqual(r['created'], 1)
        self.assertFalse(r['l2Approved']); self.assertFalse(r['chatAccessGranted'])
        value = self.catalog.read_selected(r['entries'])[0]
        self.assertIn('PyTorch not run', value['body'])
        self.assertIn('第一人称属于该来源作者', value['body'])
        self.assertEqual(value['metadata']['facets'], ['encounter'])
        self.assertEqual(value['metadata']['trust'], 'agent_inferred')
        with self.catalog.connection() as db:
            source = json.loads(db.execute('SELECT body FROM rc_source_payloads').fetchone()[0])
            self.assertEqual(source, self.packet['items'][0])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        self.assertEqual(sum(q == 'BEGIN IMMEDIATE' for q in self.events), 1)

    def test_duplicate_idempotent_even_after_process_reopen(self):
        first = self.apply()
        script = ('import json,sys; from workbench.research_import import ResearchImporter; '
                  'p=json.loads(sys.argv[2]); print(json.dumps(ResearchImporter(sys.argv[1]).apply(p,category="encounter")))')
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', script,
                                 str(self.path), json.dumps(self.packet)], capture_output=True, text=True, check=True)
        second = json.loads(result.stdout)
        self.assertEqual(second['unchanged'], 1)
        self.assertEqual(second['created'], 0)
        self.assertEqual(second['entries'], [list(first['entries'][0])])

    def test_changed_payload_with_same_revision_rejected(self):
        self.apply()
        self.packet['items'][0]['review_scope'] = 'different claim'
        with self.assertRaisesRegex(ResearchError, 'content_mismatch'):
            self.apply()

    def test_cas_update_invalidates_old_dependency_and_archives_original(self):
        old = self.apply()['entries']
        before = deepcopy(self.packet)
        item = self.packet['items'][0]
        item.update(previous=item['revision'], revision=identifier(), body='Corrected report.')
        new = self.apply()
        self.assertEqual(new['updated'], 1)
        self.assertEqual(old[0][0], new['entries'][0][0])
        with self.assertRaises(ResearchError):
            self.catalog.read_selected(old)
        self.assertIn('Corrected report.', self.catalog.read_selected(new['entries'])[0]['body'])
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_source_payloads').fetchone()[0], 2)
        with self.assertRaisesRegex(ResearchError, 'old_import_replay'):
            self.apply(before)

    def test_stale_update_rolls_back_earlier_new_item(self):
        self.apply()
        current = deepcopy(self.packet['items'][0])
        new = deepcopy(current); new.update(id='new', revision=identifier())
        current.update(previous=identifier(), revision=identifier())
        self.packet['items'] = [new, current]
        with self.assertRaisesRegex(ResearchError, 'revision_changed'):
            self.apply()
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_entries').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_import_receipts').fetchone()[0], 1)

    def test_sql_failure_rolls_back_all_rows_and_keeps_original_error(self):
        self.catalog.initialize()
        with self.catalog.connection(write=True) as db:
            db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON rc_bodies BEGIN SELECT RAISE(ROLLBACK,'synthetic failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'synthetic failure'):
            self.apply()
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_sources').fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='rc_import_items'").fetchone())

    def test_new_catalog_schema_rolls_back_with_invalid_predecessor(self):
        self.packet['items'][0]['previous'] = identifier()
        with self.assertRaises(ResearchError): self.apply()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0], 0)

    def test_withdrawn_or_independently_changed_source_cannot_revive(self):
        r = self.apply()
        with self.catalog.connection() as db:
            source = db.execute('SELECT id,revision FROM rc_sources').fetchone()
        self.catalog.change_source(*source, state='withdrawn')
        with self.assertRaises(ResearchError): self.apply()
        with self.assertRaises(ResearchError): self.catalog.read_selected(r['entries'])

    def test_course_scope_is_host_owned_and_cannot_downgrade(self):
        course = identifier()
        r = self.apply(category='course', courses=(course,))
        self.events.clear()
        with self.assertRaisesRegex(ResearchError, 'course_access_denied'):
            self.catalog.read_selected(r['entries'])
        self.assertFalse(any(q.startswith('SELECT body ') for q in self.events))
        self.assertIn('Reported observation', self.catalog.read_selected(r['entries'], access=ResearchAccess('study', (course,)))[0]['body'])
        with self.assertRaisesRegex(ResearchError, 'scope_change'):
            self.apply()
        with self.assertRaisesRegex(ResearchError, 'scope_change'):
            self.apply(category='course', courses=(identifier(),))

    def test_packet_cannot_add_scope_or_approval_or_execute_paths(self):
        for field in ('category', 'courses', 'trust', 'command'):
            p = deepcopy(self.packet); p['items'][0][field] = 'user_confirmed'
            with self.assertRaises(ValueError): self.apply(p)
        self.assertFalse(self.path.exists())
        self.packet['items'][0]['id'] = '../../not-a-file'
        self.packet['items'][0]['source_ref'] = 'file:///missing-path-do-not-open'
        self.assertEqual(self.apply()['created'], 1)

    def test_duplicates_and_oversize_rejected_before_open(self):
        p = deepcopy(self.packet); p['items'] *= 2
        with self.assertRaises(ValueError): self.apply(p)
        p = deepcopy(self.packet); p['items'][0]['body'] = '字' * 9000
        with self.assertRaises(ValueError): self.apply(p)
        self.assertFalse(self.path.exists())

    def test_json_duplicate_keys_rejected(self):
        path = Path(self.temp.name) / 'packet.json'
        path.write_text('{"format":"x","format":"y"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate_import_json_key'):
            load_packet(path)

    def test_source_version_race_is_refused_by_second_writer(self):
        self.apply()
        one = deepcopy(self.packet); two = deepcopy(self.packet)
        for p in (one, two):
            i = p['items'][0]; i.update(previous=i['revision'], revision=identifier())
        self.apply(one)
        with self.assertRaisesRegex(ResearchError, 'revision_changed'):
            ResearchImporter(self.path).apply(two, category='encounter')

    def test_existing_chat_schema_and_rows_unchanged(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA user_version=1')
            db.execute('CREATE TABLE lc_guard(body TEXT)')
            db.execute("INSERT INTO lc_guard VALUES ('original chat sentinel')")
            db.commit()
        self.apply()
        self.assertFalse(any('lc_guard' in q for q in self.events))
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT body FROM lc_guard').fetchone()[0], 'original chat sentinel')

    def test_viewer_import_title_and_review_metadata_without_body_reads(self):
        from workbench.research_books import ResearchBooks
        self.apply()
        store = type('Reader', (), {'path': self.path, 'read_connection': self.catalog.connection})()
        self.events.clear()
        row = ResearchBooks(store).entries('encounter')['entries'][0]
        self.assertEqual(row['title'], 'Synthetic lesson')
        self.assertEqual(row['reviewStatus'], 'partial')
        self.assertEqual(row['reviewScope'], 'NumPy checked; PyTorch not run.')
        self.assertFalse(any('FROM rc_bodies' in q or 'FROM rc_source_payloads' in q for q in self.events))

    def test_course_import_labels_not_listed_in_general_group(self):
        from workbench.research_books import ResearchBooks
        self.apply(category='course', courses=(identifier(),))
        store = type('Reader', (), {'path': self.path, 'read_connection': self.catalog.connection})()
        self.events.clear()
        self.assertEqual(ResearchBooks(store).entries('encounter')['entries'], [])
        self.assertFalse(any('FROM rc_import_items' in q for q in self.events))

    def test_external_material_never_uses_agent_or_confirmed_trust(self):
        result = self.apply(source_kind='web')
        self.assertEqual(self.catalog.read_selected(result['entries'])[0]['metadata']['trust'], 'external_untrusted')

    def test_unknown_catalog_version_is_not_migrated(self):
        self.catalog.initialize()
        with self.catalog.connection(write=True) as db:
            db.execute("UPDATE rc_meta SET value='999' WHERE key='schema'")
        with self.assertRaisesRegex(ResearchError, 'unsupported_research_schema'):
            self.apply()
        with self.catalog.connection() as db:
            self.assertEqual(db.execute("SELECT value FROM rc_meta WHERE key='schema'").fetchone()[0], '999')


if __name__ == '__main__':
    unittest.main()
