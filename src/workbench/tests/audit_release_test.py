from pathlib import Path
import sys,tempfile,json,uuid,importlib.util,unittest
R=Path(__file__).resolve().parents[3];P=R;sys.path[:0]=[str(P/'src'),str(P/'mobile/update-publisher')]
from workbench.companion_chat import CompanionChat
from workbench.layer_sync import empty
from layer_service import LayerService

class Extra(unittest.TestCase):
 def test_service_attaches_new_owner_without_stealing(self):
  with tempfile.TemporaryDirectory() as td:
   chat=CompanionChat(Path(td)/'chat.json');service=LayerService(chat.store.path,str(uuid.uuid4()))
   request=str(uuid.uuid4());chat.store.begin_turn(chat.store.session_id,'合成待完成',request)
   service.exchange({'snapshot':empty(service.scope)})
   with chat.store.read_connection() as db:
    self.assertEqual(db.execute("SELECT value FROM lc_meta WHERE key='owner'").fetchone()[0],chat.store.owner)
    self.assertEqual(db.execute('SELECT status FROM lc_turns WHERE id=?',(request,)).fetchone()[0],'pending')
   newer=CompanionChat(Path(td)/'chat.json');service.exchange({'snapshot':empty(service.scope)})
   newer.store.begin_turn(newer.store.session_id,'重启后合成消息',str(uuid.uuid4()))
 def test_public_default_uses_no_private_inputs(self):
  spec=importlib.util.spec_from_file_location('build_core',P/'mobile/tools/build-core.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);src=root/'src/workbench';src.mkdir(parents=True)
   (src/'companion_core_memory.example.json').write_text('{"schemaVersion":1,"entries":[]}',encoding='utf8')
   (src/'companion_persona.example.md').write_text('PUBLIC',encoding='utf8')
   private=b'{"schemaVersion":1,"entries":[{"key":"synthetic","body":"PRIVATE_CANARY"}]}'
   (src/'companion_core_memory.json').write_bytes(private);(src/'companion_persona.md').write_text('PRIVATE_CANARY',encoding='utf8')
   notes=root/'local-notes';notes.mkdir();(notes/'user-memory-foundation.sqlite3').write_bytes(b'UNREADABLE_CANARY_NOT_A_DB')
   mod.generate(root)
   self.assertEqual((src/'companion_core_memory.json').read_bytes(),private)
   self.assertEqual(json.loads((root/'mobile/www/chat-core-memory.json').read_text())['entries'],[])
   self.assertEqual((root/'mobile/www/chat-persona.txt').read_text(),'PUBLIC')
   mod.generate(root,'private');self.assertIn('PRIVATE_CANARY',(root/'mobile/www/chat-core-memory.json').read_text())
   self.assertEqual((src/'companion_core_memory.json').read_bytes(),private)
if __name__=='__main__':unittest.main(verbosity=2)
