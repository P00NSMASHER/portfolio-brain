import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class CheckpointVerificationDispatchTests(unittest.TestCase):
    def test_checkpoint_finalizer_retries_trusted_dispatch_until_independent_gate_exists(self):
        text=(ROOT/".github/workflows/portfolio-state-checkpoint-candidate.yml").read_text()
        self.assertIn("Dispatch Foundation verification when independent gate is still missing",text)
        self.assertIn('"portfolio-phase1-gate"',text)
        self.assertIn('row.get("app",{}).get("id")==5121826',text)
        self.assertIn("actions/workflows/foundation-ci.yml/runs?branch=",text)
        self.assertIn("event=workflow_dispatch",text)
        self.assertIn('row.get("head_sha")==sha',text)
        self.assertIn('row.get("status")!="completed"',text)
        self.assertIn('gh workflow run foundation-ci.yml --ref "$CHECKPOINT_BRANCH"',text)

    def test_legitimate_checkpoint_noop_does_not_require_candidate_pr(self):
        text=(ROOT/".github/workflows/portfolio-state-checkpoint-candidate.yml").read_text()
        self.assertIn(
            "steps.incident.outputs.active == 'true' || steps.generate.outputs.changed == 'true'",
            text,
        )
        self.assertIn("steps.candidate.outputs.head_sha != ''",text)
        self.assertIn("if git diff --quiet -- state_journal; then",text)
        self.assertIn('echo "changed=false" >> "$GITHUB_OUTPUT"',text)

    def test_canonical_ready_trigger_remains_explicit_and_auditable(self):
        trigger=(ROOT/".github/triggers/step2-canonical-ready.txt").read_text()
        self.assertIn("post-sequence372-checkpoint-merge-live-reducer",trigger)

if __name__=="__main__":
    unittest.main()
