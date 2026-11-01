"""Synthetic project only; no real credentials, git add, commit, push, or publication."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'tools'))
from audit_source import audit


class SourceAuditChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'synthetic-project'
        (self.root/'tools').mkdir(parents=True)
        shutil.copy2(HERE/'tools'/'export_source.py',self.root/'tools'/'export_source.py')
        (self.root/'a.txt').write_text('SYNTHETIC_PUBLIC\n',encoding='utf-8')
        (self.root/'SYNTHETIC_PRIVATE_SENTINEL.txt').write_text('SYNTHETIC_PRIVATE_SENTINEL',encoding='utf-8')
        self.names=['.gitignore','a.txt','tools/export_source.py']
        self.manifest(self.names)
        self.restored_ignore()

    def manifest(self,names):
        (self.root/'source-files.json').write_text(json.dumps({'files':names}),encoding='utf-8')

    def restored_ignore(self):
        (self.root/'.gitignore').write_text('*\n!/.gitignore\n!/a.txt\n!/tools/\n!/tools/export_source.py\n',encoding='utf-8')

    def export(self):
        out=self.base/'exported'
        proc=subprocess.run([sys.executable,str(self.root/'tools'/'export_source.py'),'--output',str(out)],capture_output=True,text=True)
        return proc,out

    def test_export_zip_names_bytes_hashes_and_private_sentinel_absent(self):
        proc,out=self.export();self.assertEqual(proc.returncode,0,proc.stderr)
        archive=out.with_suffix('.zip');report=json.loads((self.base/'exported_files.json').read_text())
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.namelist(),self.names)
            self.assertIsNone(z.testzip())
            for row in report['files']:
                self.assertEqual(hashlib.sha256(z.read(row['file'])).hexdigest(),row['sha256'])
            self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL.txt',z.namelist())
        self.assertEqual(audit(self.root,archive=archive)['issues'],[])

    def test_duplicate_and_case_fold_collision_fail_before_output(self):
        for names in (self.names+['a.txt'],self.names+['A.txt']):
            with self.subTest(names=names):
                self.manifest(names)
                proc,out=self.export();self.assertNotEqual(proc.returncode,0)
                self.assertFalse(out.exists())

    def test_invalid_absolute_parent_windows_link_and_missing_fail_before_output(self):
        cases=['/absolute','../outside','a/./b','a//b','C:/private','missing.txt','linked.txt','linked-dir/a.txt']
        if os.name=='nt':
            import _winapi
            _winapi.CreateJunction(str(self.base),str(self.root/'linked-dir'))
            cases.remove('linked.txt')  # File symlinks require unavailable Windows privileges.
        else:
            (self.root/'linked.txt').symlink_to(self.base/'outside.txt')
            (self.root/'linked-dir').symlink_to(self.base,target_is_directory=True)
        for name in cases:
            with self.subTest(name=name):
                self.manifest(self.names+[name])
                proc,out=self.export();self.assertNotEqual(proc.returncode,0)
                self.assertFalse(out.exists())

    def test_existing_archive_report_and_nonempty_directory_are_not_overwritten(self):
        for collision in ('archive','report','nonempty'):
            with self.subTest(collision=collision):
                out=self.base/'exported';archive=out.with_suffix('.zip');report=self.base/'exported_files.json'
                if collision=='archive':archive.write_bytes(b'SYNTHETIC_EXISTING')
                if collision=='report':report.write_bytes(b'SYNTHETIC_EXISTING')
                if collision=='nonempty':out.mkdir();(out/'existing').write_bytes(b'SYNTHETIC_EXISTING')
                proc,_=self.export();self.assertNotEqual(proc.returncode,0)
                if collision=='archive':self.assertEqual(archive.read_bytes(),b'SYNTHETIC_EXISTING')
                if collision=='report':self.assertEqual(report.read_bytes(),b'SYNTHETIC_EXISTING')
                if collision=='nonempty':self.assertEqual((out/'existing').read_bytes(),b'SYNTHETIC_EXISTING')
                if archive.exists():archive.unlink()
                if report.exists():report.unlink()
                if out.exists():shutil.rmtree(out)

    def test_ignore_rule_truncation_exposes_private_path_and_fails(self):
        good=audit(self.root);self.assertTrue(good['ok'])
        (self.root/'.gitignore').write_text('!/.gitignore\n',encoding='utf-8')
        broken=audit(self.root);self.assertFalse(broken['ok'])
        self.assertLess(broken['excludedProbesIgnored'],broken['excludedProbeCount'])
        self.assertTrue(any('private/build probe unignored' in x for x in broken['issues']))

    def test_export_archive_mismatch_is_detected(self):
        proc,out=self.export();self.assertEqual(proc.returncode,0,proc.stderr)
        (self.root/'a.txt').write_text('SYNTHETIC_CHANGED',encoding='utf-8')
        result=audit(self.root,archive=out.with_suffix('.zip'))
        self.assertFalse(result['ok']);self.assertTrue(any('export hash mismatch' in x for x in result['issues']))


if __name__=='__main__':unittest.main()
