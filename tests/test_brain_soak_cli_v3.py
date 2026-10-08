import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class SoakCLITest(unittest.TestCase):
    def test_absent_proof_never_returns_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'evidence.json'
            sha='a'*40
            path.write_text(json.dumps({'runs':[], 'source_sha':sha,'current_main':sha,
                                        'first_state_parent':'b'*40,
                                        'started_at':'2026-10-08T01:00:00Z',
                                        'deadline_at':'2026-10-08T06:00:00Z',
                                        'now':'2026-10-08T02:00:00Z'}))
            done=subprocess.run([sys.executable,'-m','soak_v3','window','--manifest',str(path)],capture_output=True,text=True)
            self.assertEqual(done.returncode,0)
            self.assertEqual(json.loads(done.stdout)['result']['status'],'WAITING')
            self.assertNotIn('PASS',done.stdout)

    def test_malformed_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'evidence.json'
            path.write_text('{"runs":"not-a-list"}')
            done=subprocess.run([sys.executable,'-m','soak_v3','window','--manifest',str(path)],capture_output=True,text=True)
            self.assertEqual(done.returncode,1)
            self.assertEqual(json.loads(done.stdout)['status'],'BLOCKED')
