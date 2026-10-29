"""PR #742 race regressions ported to the bounded original reader."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from brain.v9.batch_provider import GitHubOriginalReader
from brain.v9.batch_queue import BatchFault
from test_brain_v9_provider import R, SHA, BASE, OP, pr, checks


class ReadbackRaceTests(unittest.TestCase):
    def run_reader(self, rows, draft=False):
        reader = GitHubOriginalReader()
        with patch.object(reader, '_get', side_effect=rows):
            method = reader.read_draft_only if draft else reader.verify_draft_and_checks
            return method(R, 741, base_sha=BASE, head_sha=SHA, operation_id=OP)

    def test_pr_mutation_during_readback_refused(self):
        for draft in (True, False):
            for field, value in [('draft', False), ('state', 'closed'),
                                 ('body', ''), ('updated_at', 'later'),
                                 ('number', 741.0), ('draft', 1)]:
                changed = pr(); changed[field] = value
                rows = [{'commit': {'sha': BASE}}, pr()]
                if not draft:
                    rows += [checks(), checks()]
                with self.subTest(draft=draft, field=field):
                    with self.assertRaisesRegex(BatchFault, 'READBACK_PR_CHANGED'):
                        self.run_reader(rows + [changed], draft)

    def test_check_rerun_during_readback_refused(self):
        for change in ({'status': 'in_progress', 'conclusion': None},
                       {'conclusion': 'failure'}, {'id': 999},
                       {'app': {'id': 5121826.0}}):
            changed = deepcopy(checks()); changed['check_runs'][1].update(change)
            with self.subTest(change=change):
                with self.assertRaisesRegex(BatchFault, 'READBACK_CHECKS_CHANGED'):
                    self.run_reader([{'commit': {'sha': BASE}}, pr(), checks(), changed])

    def test_repeat_reads_cannot_exceed_get_budget(self):
        reader = GitHubOriginalReader(max_gets=3)
        documents = iter([{'commit': {'sha': BASE}}, pr(), checks()])
        import json
        from unittest.mock import MagicMock
        def response(*args, **kwargs):
            result = MagicMock()
            result.__enter__.return_value = result
            result.status = 200
            result.read.return_value = json.dumps(next(documents)).encode()
            return result
        with patch.object(reader._opener, 'open', side_effect=response) as opened:
            with self.assertRaisesRegex(BatchFault, 'READBACK_BUDGET_EXHAUSTED'):
                reader.verify_draft_and_checks(R, 741, base_sha=BASE,
                                              head_sha=SHA, operation_id=OP)
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(reader.gets_remaining, 0)
