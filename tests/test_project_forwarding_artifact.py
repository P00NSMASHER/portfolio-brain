from legacy.workflow_archive import legacy_workflow_path
import unittest
from pathlib import Path

from runtime.forwarding_artifact_state import ARTIFACT_NAME
from runtime.project_forwarding import load_state

ROOT=Path(__file__).resolve().parents[1]


class ProjectForwardingArtifactTests(unittest.TestCase):
    def test_forwarding_uses_dedicated_artifact_namespace(self):
        self.assertEqual(ARTIFACT_NAME,"portfolio-project-forwarding-state")
        workflow=(legacy_workflow_path(ROOT/".github/workflows/runtime-worker.yml")).read_text(encoding="utf-8")
        self.assertIn("name: portfolio-project-forwarding-state",workflow)
        self.assertIn("path: runtime/out/project_forwarding_state.json",workflow)

    def test_missing_first_run_state_bootstraps_empty_valid_ledger(self):
        state=load_state(ROOT/"runtime/live/definitely-missing-project-forwarding-state.json")
        self.assertEqual(state["state_id"],"portfolio-project-forwarding-state")
        self.assertEqual(state["sequence"],0)
        self.assertEqual(state["delivered_keys"],[])


if __name__=="__main__":
    unittest.main()
