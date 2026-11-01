"""Synthetic read-only viewer and authenticated loopback checks; no private data."""
import json
from pathlib import Path
import threading
import socket
import tempfile
import unittest
import uuid
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from workbench.research_books import ResearchBooks
from workbench.research_catalog import ResearchAccess, ResearchCatalog, ResearchError
from workbench.encounter_composition import create_desktop_chat
from workbench import server
import research_context_test as fixtures


class ResearchBooksTests(unittest.TestCase):
    captures = []

    def setUp(self):
        self.fixture = fixtures.ResearchWiringTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.chat = self.fixture.chat
        self.events = self.fixture.events
        self.viewer = ResearchBooks(self.chat.store, trace=self.events.append)

    def tearDown(self):
        self.captures.append({'case': self.id(), 'sql': self.events[:],
                              'syntheticModelCalls': len(self.fixture.http.requests)})

    def no_bodies(self):
        self.assertFalse(any(q.startswith('SELECT body ') for q in self.events))
        self.assertFalse(any('FROM rc_source_payloads' in q for q in self.events))

    def approved(self):
        ident, revision = 'synthetic-approved', str(uuid.uuid4())
        with self.chat.store.connection() as db:
            db.execute('INSERT INTO lm_approved VALUES (?,?,?,?,?,0,?)',
                       (ident, revision, 'APPROVED_BODY_fixture', 'source', '2026-01-01', 'owner'))
        return ident, revision

    def test_four_groups_count_metadata_only_and_course_overrides_interest(self):
        self.approved()
        c = self.chat.store.catalog
        source = c.create_source('web', 'synthetic original')
        c.add_entry('GENERAL_BODY_fixture', [source], facets=('encounter', 'interest'))
        self.fixture.seed()
        self.events.clear()
        value = self.viewer.groups()
        self.assertEqual({e['id']: e['count'] for e in value['groups']},
                         {'approved': 1, 'encounter': 1, 'interest': 1, 'course': 1})
        self.assertFalse(value['chatAccessGranted'])
        self.assertNotIn('BODY_fixture', json.dumps(value))
        self.no_bodies()

    def test_absent_catalog_does_not_create_tables_or_upgrade_default_chat(self):
        normal = create_desktop_chat(self.fixture.root / 'normal' / 'chat.json', keys=fixtures.Keys(), opener=self.fixture.http)
        viewer = ResearchBooks(normal.store, trace=self.events.append)
        self.assertEqual(viewer.groups()['researchStatus'], 'empty')
        self.assertEqual(viewer.entries('course')['entries'], [])
        with normal.store.read_connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'rc_%'").fetchone()[0], 0)

    def test_filtered_pagination_is_stable_and_never_reads_body(self):
        c = self.chat.store.catalog
        source = c.create_source('web', 'synthetic source')
        ids = [c.add_entry('GENERAL_BODY_fixture', [source])[0] for _ in range(32)]
        self.fixture.seed()
        self.events.clear()
        first = self.viewer.entries('interest')
        second = self.viewer.entries('interest', first['next'])
        self.assertEqual(len(first['entries']), 30)
        self.assertEqual(len(second['entries']), 2)
        self.assertEqual([r['id'] for r in first['entries'] + second['entries']], sorted(ids))
        self.assertIsNone(second['next'])
        self.no_bodies()

    def test_course_cannot_be_read_through_interest_label(self):
        _, entry = self.fixture.seed()
        self.events.clear()
        with self.assertRaises(ValueError):
            self.viewer.read('interest', *entry, purpose='browse')
        self.no_bodies()

    def test_course_requires_explicit_view_purpose_and_grants_no_chat_access(self):
        _, entry = self.fixture.seed()
        self.events.clear()
        with self.assertRaises(ValueError):
            self.viewer.read('course', *entry, purpose='browse')
        self.no_bodies()
        value = self.viewer.read('course', *entry, purpose='study_material')
        self.assertEqual(value['body'], 'COURSE_SECRET_source')
        self.assertIsNone(self.chat.store.scope.get())
        self.assertEqual(self.chat.research_provider._bindings, {})
        self.assertEqual(self.fixture.http.requests, [])
        with self.assertRaises(ResearchError):
            self.chat.store.catalog.read_selected([entry])

    def test_revised_or_withdrawn_source_is_not_read_from_saved_list(self):
        source, entry = self.fixture.seed()
        self.chat.store.catalog.change_source(*source, state='withdrawn')
        self.events.clear()
        self.assertEqual(self.viewer.entries('course')['entries'][0]['state'], 'unavailable')
        with self.assertRaises(ValueError):
            self.viewer.read('course', *entry, purpose='study_material')
        self.no_bodies()

    def test_changed_approved_revision_and_conflict_block_before_body(self):
        ident, revision = self.approved()
        with self.chat.store.connection() as db:
            db.execute('UPDATE lm_approved SET revision=? WHERE key=?', (str(uuid.uuid4()), ident))
        self.events.clear()
        with self.assertRaises(ValueError):
            self.viewer.read('approved', ident, revision, purpose='browse')
        self.no_bodies()
        with self.chat.store.connection() as db:
            db.execute('INSERT INTO lm_sync_conflicts VALUES (2,?)', (ident,))
        self.assertEqual(self.viewer.entries('approved')['entries'], [])

    def test_approved_view_is_read_only_and_does_not_reclassify_research(self):
        ident, revision = self.approved()
        self.fixture.seed(course=False)
        self.events.clear()
        self.assertNotIn('body', self.viewer.entries('approved')['entries'][0])
        self.no_bodies()
        self.assertEqual(self.viewer.read('approved', ident, revision, purpose='browse')['body'], 'APPROVED_BODY_fixture')
        self.assertEqual(self.viewer.groups()['groups'][0]['count'], 1)
        self.assertFalse(any(q.startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE')) for q in self.events))

    def test_unknown_catalog_version_returns_no_research_body(self):
        self.fixture.seed()
        with self.chat.store.connection() as db:
            db.execute("UPDATE rc_meta SET value='99' WHERE key='schema'")
        self.events.clear()
        self.assertEqual(self.viewer.groups()['researchStatus'], 'unsupported')
        self.assertEqual(self.viewer.entries('course')['entries'], [])
        self.no_bodies()

    def test_source_changed_between_metadata_and_body_still_blocks(self):
        source, entry = self.fixture.seed()
        original = self.viewer.catalog.read_selected
        def changed(*args, **kwargs):
            self.chat.store.catalog.change_source(*source, source_text='replacement source')
            return original(*args, **kwargs)
        self.viewer.catalog.read_selected = changed
        self.events.clear()
        with self.assertRaises(ValueError):
            self.viewer.read('course', *entry, purpose='study_material')
        self.no_bodies()

    def test_invalid_catalog_filters_are_rejected_before_sql(self):
        self.events.clear()
        for kwargs in ({'facet': 'all'}, {'restriction': True}, {'facet': 'interest" OR 1=1'}):
            with self.assertRaises(ValueError):
                self.chat.store.catalog.catalog(**kwargs)
        self.assertEqual(self.events, [])


class ResearchBooksHTTPTests(unittest.TestCase):
    def setUp(self):
        original_connect = socket.socket.connect
        def connect(sock, address):
            if address[0] != '127.0.0.1':
                raise AssertionError('non-loopback network prohibited')
            return original_connect(sock, address)
        network = patch.object(socket.socket, 'connect', new=connect)
        network.start(); self.addCleanup(network.stop)
        from workbench import companion_chat as cc
        persona = patch.object(cc, 'system_prompt', return_value='公开合成人设。')
        persona.start(); self.addCleanup(persona.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        core = patch.object(server, 'create_desktop_chat', side_effect=self.make_chat)
        core.start(); self.addCleanup(core.stop)
        no_background = patch.object(server.DesktopMemoryReview, 'start', return_value=None)
        no_background.start(); self.addCleanup(no_background.stop)
        self.s = server.WorkbenchServer(Path(self.tmp.name))
        self.thread = threading.Thread(target=self.s.serve, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    @staticmethod
    def make_chat(path, **kwargs):
        from workbench import companion_chat as cc
        from workbench.memory_layers import MemoryLayers
        with patch.object(cc, 'MemoryLayers', side_effect=lambda store: MemoryLayers(store, core_loader=lambda: {'schemaVersion': 1, 'entries': []})):
            return create_desktop_chat(path, keys=fixtures.Keys(), opener=fixtures.HTTP(), **kwargs)

    def close_server(self):
        self.s.stop(); self.thread.join(2); self.s.server_close()

    def post(self, command, params=None, token=None):
        req = Request(self.s.origin + '/api/call', data=json.dumps({'command': command, 'params': params or {}}).encode(),
                      headers={'Authorization': 'Bearer ' + (token or self.s.token), 'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_authenticated_groups_and_strict_command_shapes(self):
        self.assertEqual(self.post('chat.research.groups', token='wrong')[0], 403)
        code, value = self.post('chat.research.groups')
        self.assertEqual(code, 200)
        self.assertEqual(len(value['result']['groups']), 4)
        self.assertEqual(self.post('chat.research.groups', {'study': True})[0], 400)
        self.assertEqual(self.post('chat.research.list', {'category': 'unknown'})[0], 400)

    def test_explicit_course_view_cannot_enable_chat_or_approve_memory(self):
        catalog = ResearchCatalog(self.s.chat.store.path)
        catalog.initialize()
        course = str(uuid.uuid4())
        source = catalog.create_source('course', 'synthetic source', courses=(course,))
        entry = catalog.add_entry('COURSE_HTTP_FIXTURE', [source])
        params = {'category': 'course', 'id': entry[0], 'revision': entry[1], 'purpose': 'browse'}
        self.assertEqual(self.post('chat.research.read', params)[0], 400)
        params['purpose'] = 'study_material'
        code, value = self.post('chat.research.read', params)
        self.assertEqual(code, 200)
        self.assertEqual(value['result']['body'], 'COURSE_HTTP_FIXTURE')
        self.assertIsNone(self.s.chat.research_provider)
        self.assertEqual(self.post('chat.reply', {'text': 'synthetic', 'study': True})[0], 400)
        self.assertEqual(self.post('chat.research.approve', params)[0], 400)
        with self.s.chat.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
