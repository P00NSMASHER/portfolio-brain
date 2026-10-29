"""Read-only planning integration; provider transport is mocked, not live proof."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from brain.v9.__main__ import main
from brain.v9.missions import compile_mission
from brain.v8.journal import KernelJournal
from tests.test_brain_v8_contracts import work
from tests.test_brain_v8_journal import operation


class ObservedPlanTests(unittest.TestCase):
    def test_live_head_drives_plan_and_source_drift_blocks_without_journal_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            row = work()
            heads = {row['repository']: row['source_sha']}
            mission = root / 'mission.json'
            mission.write_text(json.dumps(compile_mission([row], source_heads=heads)))
            db = root / 'kernel.sqlite'
            with KernelJournal(db, create=True) as journal:
                journal.append(operation(row))
            before = db.read_bytes()
            args = ['observe-plan', '--mission', str(mission), '--journal', str(db)]
            for observed, expected in ((heads, 0), ({row['repository']: 'f' * 40}, 2)):
                output = io.StringIO()
                with patch.dict(os.environ, {'V9_GITHUB_READ_TOKEN': 'test-secret'}), patch(
                    'brain.v9.github_observer.observe_repositories',
                    return_value={'source_heads': observed, 'write_authority': False}) as provider, contextlib.redirect_stdout(output):
                    result = main(args)
                self.assertEqual(result, expected, output.getvalue())
                provider.assert_called_once()
                self.assertEqual(provider.call_args.args[0], {row['repository']: []})
                self.assertNotIn('test-secret', output.getvalue())
                self.assertFalse(json.loads(output.getvalue())['production_accepted'])
                self.assertEqual(db.read_bytes(), before)

    def test_invalid_mission_is_rejected_before_provider_access(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'mission.json'
            p.write_text('{}')
            with patch('brain.v9.github_observer.observe_repositories') as provider, contextlib.redirect_stdout(io.StringIO()):
                result = main(['observe-plan', '--mission', str(p), '--journal', str(p.parent / 'missing')])
            self.assertEqual(result, 2)
            provider.assert_not_called()

    def test_missing_credential_fails_closed_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); row = work(); heads = {row['repository']: row['source_sha']}
            p = root / 'mission.json'
            p.write_text(json.dumps(compile_mission([row], source_heads=heads)))
            db = root / 'kernel.sqlite'
            with KernelJournal(db, create=True) as journal:
                journal.append(operation(row))
            before = db.read_bytes(); output = io.StringIO()
            with patch.dict(os.environ, {'V9_GITHUB_READ_TOKEN': ''}), contextlib.redirect_stdout(output):
                result = main(['observe-plan', '--mission', str(p), '--journal', str(db)])
            self.assertEqual(result, 2)
            self.assertEqual(json.loads(output.getvalue())['status'], 'BLOCKED')
            self.assertEqual(db.read_bytes(), before)
