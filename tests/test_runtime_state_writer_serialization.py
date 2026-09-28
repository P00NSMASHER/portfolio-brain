from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeStateWriterSerializationTests(unittest.TestCase):
    def test_observe_and_sync_share_one_nonpaid_state_writer_lane(self):
        workflow = (ROOT / ".github/workflows/runtime-worker.yml").read_text(encoding="utf-8")
        self.assertIn(
            "(inputs.mode == 'observe' || inputs.mode == 'sync') && 'portfolio-runtime-nonpaid-state-writer'",
            workflow,
        )
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertNotIn(
            "cancel-in-progress: ${{ inputs.mode == 'observe' || inputs.mode == 'sync' }}",
            workflow,
        )

    def test_paid_runtime_lane_and_authority_gates_are_unchanged(self):
        workflow = (ROOT / ".github/workflows/runtime-worker.yml").read_text(encoding="utf-8")
        self.assertIn("'portfolio-cost-governed-autonomy'", workflow)
        self.assertIn("python -m cost_governor.workflow_gate preflight", workflow)
        self.assertIn("--authority OBSERVE", workflow)
        self.assertIn("python -m workload_control.workload_gate preflight", workflow)


if __name__ == "__main__":
    unittest.main()
