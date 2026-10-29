"""Run the real command boundary against hostile local input and original files."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from test_brain_v8_contracts import work
from test_brain_v8_journal import operation
from brain.v8.journal import KernelJournal


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.input=self.root/'input.json'

    def run_cli(self,*args):
        env=dict(os.environ)
        for key in ['GITHUB_TOKEN','GH_TOKEN','OPENAI_API_KEY']: env.pop(key,None)
        return subprocess.run([sys.executable,'-m','brain.v8',*args],capture_output=True,
                              text=True,timeout=8,env=env)

    def assert_blocked(self,result):
        self.assertEqual(result.returncode,2)
        self.assertTrue(result.stdout.startswith('{'),'missing bounded CLI rejection')
        self.assertEqual(json.loads(result.stdout)['status'],'BLOCKED')

    def test_validate_and_plan_without_credentials_or_external_actions(self):
        row=work()
        self.input.write_text(json.dumps(row))
        result=self.run_cli('validate','--input',str(self.input))
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(data['work_id'],row['work_id'])
        self.assertEqual(data['runtime_actions_executed'],0)
        self.assertFalse(data['production_accepted'])
        self.input.write_text(json.dumps([row,work('other',priority_tier=0)]))
        result=self.run_cli('plan','--input',str(self.input),'--cycle','0','--limit','1')
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(data['selected'][0]['project_id'],'other')
        self.assertEqual(data['scope'],'LOCAL_V8_KERNEL_ONLY')

    def test_malformed_duplicate_non_utf8_and_oversize_inputs_fail_without_echo(self):
        for payload in [b'{PRIVATESECRET',b'{"schema_version":1,"schema_version":1}',
                        b'\xffPRIVATESECRET',b' '*1048577,
                        ('['*1200+'0'+']'*1200).encode()]:
            self.input.write_bytes(payload)
            result=self.run_cli('validate','--input',str(self.input))
            self.assert_blocked(result)
            self.assertNotIn('PRIVATESECRET',result.stdout+result.stderr)
            self.assertLess(len(result.stdout+result.stderr),2000)

    def test_symlink_and_fifo_input_refused_without_hanging(self):
        target=self.root/'original.json'
        target.write_text(json.dumps(work()))
        self.input.symlink_to(target)
        self.assert_blocked(self.run_cli('validate','--input',str(self.input)))
        self.input.unlink()
        os.mkfifo(self.input)
        self.assert_blocked(self.run_cli('validate','--input',str(self.input)))
        self.assertEqual(json.loads(target.read_text()),work())

    def test_replay_readonly_summarizes_and_missing_never_created(self):
        path=self.root/'journal.sqlite'
        with KernelJournal(path,create=True) as journal: journal.append(operation(outcome='EXTERNAL_INTENT'))
        before=path.read_bytes()
        result=self.run_cli('replay','--journal',str(path))
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(data['record_count'],1)
        self.assertEqual(data['unresolved_external_count'],1)
        self.assertEqual(path.read_bytes(),before)
        missing=self.root/'absent.sqlite'
        self.assert_blocked(self.run_cli('replay','--journal',str(missing)))
        self.assertFalse(missing.exists())

    def test_foreign_production_database_preserved(self):
        path=self.root/'state.sqlite'
        with sqlite3.connect(path) as db: db.execute('CREATE TABLE meta(key TEXT,value TEXT)')
        path.chmod(0o600)
        before=path.read_bytes()
        self.assert_blocked(self.run_cli('replay','--journal',str(path)))
        self.assertEqual(path.read_bytes(),before)

    def test_cli_succeeds_when_network_and_child_process_creation_forbidden(self):
        self.input.write_text(json.dumps(work()))
        code="""import sys,runpy
sys.argv=['brain.v8','validate','--input',sys.argv[1]]
def guard(event,args):
 if event in {'socket.connect','socket.bind','subprocess.Popen','os.system'}:
  raise RuntimeError('external operation prohibited')
sys.addaudithook(guard)
runpy.run_module('brain.v8',run_name='__main__')
"""
        result=subprocess.run([sys.executable,'-c',code,str(self.input)],capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['runtime_actions_executed'],0)
