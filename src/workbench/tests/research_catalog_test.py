"""File SQLite, actual SQL traces and separate-process CAS/publication checks.

Only generated fixtures; no user DBs, model calls or provider credentials.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workbench.research_catalog import ResearchAccess, ResearchCatalog, ResearchError, digest, SCHEMA


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'research.sqlite3'
        self.events = []
        self.store = ResearchCatalog(self.path, trace=self.events.append)
        self.store.initialize()
        self.course = str(uuid.uuid4())
        self.other = str(uuid.uuid4())

    def seed(self, *, course=False, body=None):
        source = self.store.create_source('course' if course else 'web', 'synthetic source',
                                          courses=(self.course,) if course else ())
        entry = self.store.add_entry(body or ('COURSE_SECRET_fixture' if course else 'synthetic general'),
                                     [source], facets=('interest',))
        return source, entry

    def body_queries(self):
        return [q for q in self.events if q.startswith('SELECT body FROM rc_bodies')]

    def test_reader_constructor_does_not_create_or_open_database(self):
        missing = self.path.with_name('missing.sqlite3')
        ResearchCatalog(missing)
        self.assertFalse(missing.exists())

    def test_reopened_catalog_is_metadata_only(self):
        self.seed(course=True)
        self.events.clear()
        rows = ResearchCatalog(self.path, trace=self.events.append).catalog()
        self.assertEqual(rows[0]['restriction'], 'study')
        self.assertNotIn('COURSE_SECRET_', json.dumps(rows))
        self.assertFalse(any('rc_bodies' in q for q in self.events))

    def test_all_selection_permissions_checked_before_first_body(self):
        _, general = self.seed()
        _, course = self.seed(course=True)
        self.events.clear()
        with self.assertRaisesRegex(ResearchError, 'course_access_denied'):
            self.store.read_selected([general, course])
        self.assertEqual(self.body_queries(), [])

    def test_study_reads_only_selected_course_and_id(self):
        _, entry = self.seed(course=True)
        other_source = self.store.create_source('course', 'other', courses=(self.other,))
        self.store.add_entry('OTHER_COURSE', [other_source])
        self.events.clear()
        result = self.store.read_selected([entry], access=ResearchAccess('study', (self.course,)))
        self.assertEqual(len(self.body_queries()), 1)
        self.assertIn(entry[0], self.body_queries()[0])
        self.assertNotIn('OTHER_COURSE', json.dumps(result))

    def test_wrong_course_and_untrusted_access_dictionary_cannot_read(self):
        _, entry = self.seed(course=True)
        for access in (ResearchAccess('study', (self.other,)), {'scene': 'study', 'courses': [self.course]}):
            self.events.clear()
            with self.assertRaises(ResearchError):
                self.store.read_selected([entry], access=access)
            self.assertFalse(self.body_queries())

    def test_two_hop_course_restriction_survives_interest_tag(self):
        source, _ = self.seed(course=True)
        derived = self.store.create_source('derived', 'synthetic first derivative', parents=[source])
        twice = self.store.create_source('derived', 'synthetic second derivative', parents=[derived])
        entry = self.store.add_entry('COURSE_SECRET_derived', [twice], facets=('interest', 'encounter'))
        self.events.clear()
        with self.assertRaisesRegex(ResearchError, 'course_access_denied'):
            self.store.read_selected([entry])
        self.assertFalse(self.body_queries())

    def test_unscoped_course_tag_and_confirmed_trust_rejected(self):
        source, _ = self.seed()
        with self.assertRaisesRegex(ResearchError, 'course_facet_requires_scoped_source'):
            self.store.add_entry('synthetic', [source], facets=('course',))
        with self.assertRaisesRegex(ValueError, 'research_cannot_approve_l2'):
            self.store.add_entry('synthetic', [source], trust='user_confirmed')

    def test_shared_ancestor_and_multicourse_union(self):
        root = self.store.create_source('course', 'a', courses=(self.course,))
        left = self.store.create_source('derived', 'left', parents=[root])
        right = self.store.create_source('derived', 'right', parents=[root])
        entry = self.store.add_entry('COURSE_SECRET_shared', [left, right])
        self.assertEqual(len(self.store.read_selected([entry], access=ResearchAccess('study', (self.course,)))), 1)
        root2 = self.store.create_source('course', 'b', courses=(self.other,))
        mixed = self.store.add_entry('COURSE_SECRET_mixed', [root, root2])
        with self.assertRaisesRegex(ResearchError, 'course_access_denied'):
            self.store.read_selected([mixed], access=ResearchAccess('study', (self.course,)))
        self.assertEqual(len(self.store.read_selected([mixed], access=ResearchAccess('study', tuple(sorted((self.course, self.other)))))), 1)

    def test_repeated_diamond_ancestry_does_not_expand_metadata_queries_exponentially(self):
        root = self.store.create_source('course', 'synthetic root', courses=(self.course,))
        parents = [root]
        for level in range(12):
            parents = [self.store.create_source('derived', 'synthetic ' + str(level) + side, parents=parents)
                       for side in ('left', 'right')]
        self.store.add_entry('COURSE_SECRET_diamond', parents)
        self.events.clear()
        rows = self.store.catalog()
        queries = [q for q in self.events if q.startswith('SELECT id,revision,kind,restriction')]
        self.assertLessEqual(len(queries), 30)
        self.assertEqual(rows[0]['restriction'], 'study')
        self.assertFalse(any('rc_source_payloads' in q or 'SELECT body FROM rc_bodies' in q for q in self.events))

    def test_revised_root_blocks_derived_after_reopen(self):
        source, _ = self.seed(course=True)
        derivative = self.store.create_source('derived', 'derived', parents=[source])
        entry = self.store.add_entry('COURSE_SECRET_old', [derivative])
        self.store.change_source(*source, source_text='revised source')
        self.events.clear()
        with self.assertRaisesRegex(ResearchError, 'research_unavailable'):
            ResearchCatalog(self.path, trace=self.events.append).read_selected([entry], access=ResearchAccess('study', (self.course,)))
        self.assertFalse(self.body_queries())
        rows = self.store.catalog()
        self.assertTrue(all(r['state'] == 'unavailable' for r in rows))

    def test_withdrawn_or_conflicted_source_cannot_be_revived(self):
        for state in ('withdrawn', 'conflict'):
            source, entry = self.seed()
            updated = self.store.change_source(*source, state=state)
            self.events.clear()
            with self.assertRaisesRegex(ResearchError, 'research_unavailable'):
                self.store.read_selected([entry])
            self.assertFalse(self.body_queries())
            with self.assertRaisesRegex(ResearchError, 'source_requires_explicit_rebuild'):
                self.store.change_source(*updated, state='active')

    def test_unresolved_conflict_blocks_later_member(self):
        group = str(uuid.uuid4())
        entries = []
        for claim in ('A', 'B', 'A'):
            source = self.store.create_source('web', 'synthetic ' + claim)
            entries.append(self.store.add_entry('synthetic body ' + claim, [source],
                                               conflict_group=group, assertion_hash=digest(claim)))
        rows = self.store.catalog()
        self.assertEqual([r['state'] for r in rows], ['conflict'] * 3)
        self.events.clear()
        with self.assertRaises(ResearchError):
            self.store.read_selected([entries[-1]])
        self.assertFalse(self.body_queries())

    def test_total_utf8_budget_checked_before_any_body(self):
        _, entry = self.seed(body='中文' * 10)
        self.events.clear()
        with self.assertRaisesRegex(ResearchError, 'research_budget_exceeded'):
            self.store.read_selected([entry], max_bytes=59)
        self.assertFalse(self.body_queries())
        self.assertEqual(self.store.read_selected([entry], max_bytes=60)[0]['body'], '中文' * 10)

    def test_body_corruption_fails_integrity_instead_of_returning_it(self):
        _, entry = self.seed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE rc_bodies SET body=? WHERE id=?', ('corrupted synthetic', entry[0]))
        with self.assertRaisesRegex(ResearchError, 'research_body_integrity_failed'):
            self.store.read_selected([entry])

    def test_unknown_schema_does_not_fall_back_to_body(self):
        self.seed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE rc_meta SET value='99' WHERE key='schema'")
        self.events.clear()
        with self.assertRaisesRegex(ResearchError, 'unsupported_research_schema'):
            self.store.catalog()
        self.assertFalse(self.body_queries())

    def test_inconsistent_course_and_unknown_trust_metadata_fail_closed(self):
        source, entry = self.seed(course=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE rc_sources SET restriction='general',courses='[]' WHERE id=?", (source[0],))
            db.execute("UPDATE rc_entries SET restriction='general',courses='[]' WHERE id=?", (entry[0],))
        self.events.clear()
        with self.assertRaisesRegex(ResearchError, 'research_unavailable'):
            self.store.read_selected([entry])
        self.assertFalse(self.body_queries())
        _, ordinary = self.seed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE rc_entries SET trust='user_confirmed' WHERE id=?", (ordinary[0],))
        self.events.clear()
        with self.assertRaisesRegex(ResearchError, 'research_unavailable'):
            self.store.read_selected([ordinary])
        self.assertFalse(self.body_queries())

    def test_stale_cas_does_not_overwrite_new_revision(self):
        source, _ = self.seed()
        updated = self.store.change_source(*source, source_text='new')
        with self.assertRaisesRegex(ResearchError, 'source_revision_changed'):
            self.store.change_source(*source, source_text='obsolete')
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT revision FROM rc_sources WHERE id=?', (source[0],)).fetchone()[0], updated[1])

    def test_publication_transaction_rolls_back_answer_and_dependencies(self):
        _, entry = self.seed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('CREATE TABLE fixture_answers(id TEXT); CREATE TABLE fixture_deps(id TEXT);')
        with self.assertRaisesRegex(RuntimeError, 'synthetic rollback'):
            with self.store.validation_transaction([entry]) as db:
                db.execute("INSERT INTO fixture_answers VALUES ('answer')")
                db.execute('INSERT INTO fixture_deps VALUES (?)', (entry[0],))
                raise RuntimeError('synthetic rollback')
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM fixture_answers').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM fixture_deps').fetchone()[0], 0)

    def test_existing_l2_rows_are_not_migrated_or_reclassified(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("CREATE TABLE lm_approved(key TEXT,body TEXT); INSERT INTO lm_approved VALUES ('old','synthetic old L2');")
        self.store.initialize()
        self.seed(course=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT * FROM lm_approved').fetchall(), [('old', 'synthetic old L2')])

    def test_original_source_versions_are_archived_without_catalog_payload_reads(self):
        source, entry = self.seed(course=True)
        updated = self.store.change_source(*source, source_text='COURSE_SECRET_new_original')
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute('SELECT revision,body FROM rc_source_payloads WHERE source_id=?', (source[0],)).fetchall()
        self.assertEqual(set(rows), {(source[1], 'synthetic source'), (updated[1], 'COURSE_SECRET_new_original')})
        self.events.clear()
        self.store.catalog()
        self.assertFalse(any('rc_source_payloads' in q for q in self.events))
        with self.assertRaises(ResearchError):
            self.store.read_selected([entry], access=ResearchAccess('study', (self.course,)))

    def test_v1_migration_does_not_invent_missing_source_original_or_change_l2(self):
        path = self.path.with_name('old-research.sqlite3')
        source, revision = str(uuid.uuid4()), str(uuid.uuid4())
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(SCHEMA[0])
            db.execute("INSERT INTO rc_meta VALUES ('schema','1')")
            db.execute('CREATE TABLE rc_sources(id TEXT PRIMARY KEY,revision TEXT,kind TEXT,restriction TEXT,courses TEXT,state TEXT,payload_hash TEXT,parents TEXT)')
            for statement in SCHEMA[3:]:
                db.execute(statement)
            db.execute('INSERT INTO rc_sources VALUES (?,?,?,?,?,?,?,?)', (source, revision, 'web', 'general', '[]', 'active', digest('missing original'), '[]'))
            db.execute("CREATE TABLE lm_approved(key TEXT,body TEXT)")
            db.execute("INSERT INTO lm_approved VALUES ('old','synthetic old L2')")
        store = ResearchCatalog(path)
        store.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(db.execute('SELECT payload_stored FROM rc_sources').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_source_payloads').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT * FROM lm_approved').fetchall(), [('old', 'synthetic old L2')])
        with self.assertRaisesRegex(ResearchError, 'source_unavailable'):
            store.add_entry('do not treat missing original as valid', [(source, revision)])

    def writer_process(self, source):
        code = """import sys
sys.path.insert(0,sys.argv[1])
from workbench.research_catalog import ResearchCatalog,ResearchError
print('ready',flush=True)
try:
 ResearchCatalog(sys.argv[2]).change_source(sys.argv[3],sys.argv[4],source_text='cross process update')
 print('updated',flush=True)
except ResearchError as e: print(str(e),flush=True)
"""
        return subprocess.Popen([sys.executable, '-B', '-c', code,
                                 str(Path(__file__).resolve().parents[2]), str(self.path), *source],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_other_process_cannot_publish_old_source_after_cas(self):
        source, _ = self.seed()
        self.store.change_source(*source, source_text='newest')
        child = self.writer_process(source)
        out, err = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, err)
        self.assertIn('source_revision_changed', out)

    def test_publication_lock_serializes_cross_process_source_writer(self):
        source, entry = self.seed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE fixture_saved(id TEXT)')
        with self.store.validation_transaction([entry]) as db:
            child = self.writer_process(source)
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            self.assertIsNone(child.poll())
            db.execute("INSERT INTO fixture_saved VALUES ('valid-at-publication')")
        out, err = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, err)
        self.assertIn('updated', out)
        with self.assertRaisesRegex(ResearchError, 'research_unavailable'):
            with self.store.validation_transaction([entry]):
                self.fail('obsolete source reached publication')
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM fixture_saved').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
