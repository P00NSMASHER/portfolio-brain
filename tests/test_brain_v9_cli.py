"""Exercise the actual offline v9 CLI without provider access."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from brain.v9.__main__ import main
from brain.v8.journal import KernelJournal
from test_brain_v8_contracts import work, LATER
from test_brain_v8_journal import operation


class MissionCLITests(unittest.TestCase):
    def invoke(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(args)
        return code, json.loads(out.getvalue())

    def test_compile_then_restart_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = work()
            heads = {row['repository']: row['source_sha']}
            source = root / 'input.json'
            source.write_text(json.dumps(dict(work=[row], source_heads=heads, max_parallel=1)))
            code, compiled = self.invoke(['compile', '--input', str(source)])
            self.assertEqual(code, 0)
            mission = root / 'mission.json'
            mission.write_text(json.dumps(compiled['result']))
            headfile = root / 'heads.json'
            headfile.write_text(json.dumps(heads))
            db = root / 'kernel.sqlite'
            with KernelJournal(db, create=True) as journal:
                journal.append(operation(row))
            before = db.read_bytes()
            code, result = self.invoke(['plan', '--mission', str(mission),
                '--heads', str(headfile), '--journal', str(db), '--now', LATER])
            self.assertEqual(code, 0)
            self.assertEqual(len(result['result']['selected']), 1)
            self.assertFalse(result['production_accepted'])
            self.assertEqual(before, db.read_bytes())

    def test_duplicate_json_missing_journal_and_bad_input_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.json'
            for contents in ('{"work":[],"work":[]}', '{}', 'null', 'NaN'):
                source.write_text(contents)
                code, result = self.invoke(['compile', '--input', str(source)])
                self.assertEqual(code, 2)
                self.assertEqual(result['status'], 'BLOCKED')
            code, result = self.invoke(['compile', '--input', str(root / 'missing')])
            self.assertEqual(code, 2)
            self.assertFalse(result['production_accepted'])


if __name__ == '__main__':
    unittest.main()
