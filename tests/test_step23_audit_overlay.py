"""The supplemental lane is source-pinned, read-only, and cannot relax evidence."""
import ast
from pathlib import Path
import unittest
from acceptance.step23_audit_overlay import transform_collector, git_blob, EXPECTED_COLLECTOR, TARGET
ROOT=Path(__file__).resolve().parents[1]
class AuditOverlayTests(unittest.TestCase):
    def test_transform_is_bound_to_the_reviewed_collector(self):
        source=(ROOT/'acceptance/step23_live_collect.py').read_text()
        self.assertEqual(git_blob(source.encode()),EXPECTED_COLLECTOR)
        changed=transform_collector(source)
        ast.parse(changed)
        self.assertEqual(git_blob(changed.encode()),'d4fe688c26f71a1dcb845e278a0ce5f3fea8d5a7')
    def test_transform_requires_all_patch_preconditions(self):
        source=(ROOT/'acceptance/step23_live_collect.py').read_text()
        with self.assertRaisesRegex(RuntimeError,'precondition'):
            transform_collector(source.replace('    args = ap.parse_args()','    args = ap.parse_args([])'))
    def test_transformed_collector_preserves_final_validator(self):
        source=transform_collector((ROOT/'acceptance/step23_live_collect.py').read_text())
        self.assertIn('validate_step23(receipt)',source)
        self.assertIn('final_census_unchanged(all_grouped, final_grouped)',source)
        self.assertIn('observed_resets, observed_start = reset_history(',source)
        self.assertIn('window_deadline = window_start + timedelta',source)
        self.assertIn('if pending_final != 0:',source)
    def test_workflow_is_read_only_and_not_recurring(self):
        text=(ROOT/'.github/workflows/step23-read-only-audit.yml').read_text()
        self.assertIn('  actions: read',text)
        self.assertIn('  contents: read',text)
        self.assertNotIn(': write',text)
        self.assertNotIn('schedule:',text)
        self.assertNotIn('workflow_dispatch:',text)
        self.assertIn('ref: '+TARGET,text)
        self.assertEqual(text.count('persist-credentials: false'),2)
    def test_overlay_cannot_change_target_on_its_own(self):
        self.assertEqual(TARGET,'ca2ae77fa0314777bbc8591e3b2507b2effa43b5')
        source=(ROOT/'acceptance/step23_audit_overlay.py').read_text()
        self.assertIn('required_successes_per_workflow=3',source)
        self.assertIn('max_soak_duration_seconds=3600',source)
        self.assertIn('("portfolio-phase1-gate", 5121826)',source)
        self.assertNotIn('git push',source)
        self.assertNotIn('gh pr merge',source)
if __name__=='__main__':unittest.main()
