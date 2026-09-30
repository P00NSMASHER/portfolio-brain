"""Offline audit consistency and exact-source scan reproduction; no runtime calls."""
import ast
import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class ScanError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise ScanError(message)


def scan_method():
    tree = ast.parse((ROOT / 'state_journal/transport.py').read_text())
    reader = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GitHubReader')
    method = next(n for n in reader.body if isinstance(n, ast.FunctionDef) and n.name == 'list_recent_artifacts')
    # Execute only the audited pure scanner with a fake provider. No imports,
    # initialization, HTTP implementation, credentials or downstream engines.
    module = ast.Module(body=[method], type_ignores=[])
    namespace = {'datetime': datetime, 'require': require, 'JournalError': ScanError}
    exec(compile(ast.fix_missing_locations(module), '<audited-scan>', 'exec'), namespace)
    return namespace['list_recent_artifacts']


class AutomationGapAuditTests(unittest.TestCase):
    def test_build_cursor_is_preserved(self):
        state = json.loads((ROOT / 'PORTFOLIO_BUILD_STATE.json').read_text())
        self.assertEqual(state['completed_steps'], list(range(26)))
        self.assertIsNone(state['current_step'])
        self.assertEqual(state['working_branch'], 'main')

    def test_receipt_has_three_exact_sources_and_no_activation(self):
        e = json.loads((ROOT / 'docs/AUTOMATION_GAP_EVIDENCE.json').read_text())
        self.assertEqual(len(e['repositories']), 3)
        self.assertTrue(all(len(r['head_sha']) == 40 for r in e['repositories']))
        self.assertTrue(e['no_changes_to_product_repositories'])
        self.assertFalse(e['runtime_activated'])

    def test_shared_failure_is_bound_to_actual_runs(self):
        e = json.loads((ROOT / 'docs/AUTOMATION_GAP_EVIDENCE.json').read_text())
        self.assertEqual(len(e['failure_evidence']), 3)
        self.assertEqual(len({r['run_id'] for r in e['failure_evidence']}), 3)
        self.assertTrue(all(r['state'] == 'VERIFIED' for r in e['failure_evidence']))
        self.assertEqual(e['main_run_sample'], {'sample_size': 55, 'failures': 55})

    def test_existing_repair_is_not_declared_promoted(self):
        e = json.loads((ROOT / 'docs/AUTOMATION_GAP_EVIDENCE.json').read_text())
        self.assertEqual(e['existing_repair']['pull_request'], 207)
        self.assertEqual(e['existing_repair']['status'], 'OPEN_NOT_PROMOTED')

    def test_old_full_page_still_exhausts_source_scan(self):
        fake = SimpleNamespace(get=lambda _: {'artifacts': [
            {'id': i + 1, 'created_at': '2026-09-01T00:00:00Z'} for i in range(100)]})
        with self.assertRaisesRegex(ScanError, 'scan incomplete'):
            scan_method()(fake, '2026-09-29T00:00:00Z', max_pages=1)

    def test_short_page_filters_old_rows(self):
        fake = SimpleNamespace(get=lambda _: {'artifacts': [
            {'id': 1, 'created_at': '2026-09-01T00:00:00Z'},
            {'id': 2, 'created_at': '2026-09-30T00:00:00Z'}]})
        self.assertEqual([x['id'] for x in scan_method()(fake, '2026-09-29T00:00:00Z')], [2])

    def test_conflicting_provider_rows_fail_closed(self):
        fake = SimpleNamespace(get=lambda _: {'artifacts': [
            {'id': 1, 'created_at': '2026-09-30T00:00:00Z'},
            {'id': 1, 'created_at': '2026-09-30T00:01:00Z'}]})
        with self.assertRaisesRegex(ScanError, 'metadata changed'):
            scan_method()(fake, '2026-09-29T00:00:00Z')

    def test_default_executor_missing_three_handlers(self):
        tree = ast.parse((ROOT / 'scheduler/work_executor.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.AnnAssign)
                    and isinstance(n.target, ast.Name) and n.target.id == 'DEFAULT_HANDLERS')
        keys = {key.value for key in node.value.keys}
        self.assertEqual(keys, {'HUNT', 'RESEARCH', 'INTEGRATION', 'EXPERIMENT'})
        self.assertFalse(keys & {'REPAIR', 'TEST', 'VERIFICATION'})


if __name__ == '__main__':
    unittest.main()
