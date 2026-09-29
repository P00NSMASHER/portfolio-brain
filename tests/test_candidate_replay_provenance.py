import copy
from pathlib import Path
import unittest

from software_factory.candidate_worker import BuildError, object_hash
from software_factory.validate_candidate_replay import validate_source_proof


class ReplayProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.task = {"base_sha": "a" * 40}
        summary = {"attempted_count": 1, "completed_count": 1, "deferred_count": 0,
                   "remaining_queued_count": 0, "authority_granted": False}
        summary["receipt_hash"] = object_hash(summary)
        self.proof = {"proof_kind": "CONTROLLED_REAL_SOURCE_REPAIR_PILOT",
                      "queue_origin": "EXPLICIT_CI_PILOT_NOT_LIVE_ALLOCATION",
                      "worker_head_sha": "b" * 40, "run_id": "100", "run_attempt": "2",
                      "pilot_base_sha": self.task["base_sha"], "task_hash": object_hash(self.task),
                      "image_id": "sha256:" + "c" * 64, "summary": summary,
                      "independent_verification": False, "production_changed": False,
                      "merged": False, "deployed": False}
        self.seal()

    def seal(self):
        self.proof.pop("receipt_hash", None)
        self.proof["receipt_hash"] = object_hash(self.proof)

    def check(self):
        validate_source_proof(self.proof, self.task, head="b" * 40, run_id="100", run_attempt="2",
                              image_id="sha256:" + "c" * 64)

    def test_exact_source_identity_passes_without_granting_approval(self):
        self.check()
        self.assertFalse(self.proof["independent_verification"])

    def test_same_branch_different_revision_is_rejected(self):
        self.proof["worker_head_sha"] = "d" * 40; self.seal()
        with self.assertRaisesRegex(BuildError, "head mismatch"):
            self.check()

    def test_other_run_cannot_supply_proof(self):
        self.proof["run_id"] = "99"; self.seal()
        with self.assertRaisesRegex(BuildError, "run mismatch"):
            self.check()

    def test_old_attempt_cannot_supply_proof(self):
        self.proof["run_attempt"] = "1"; self.seal()
        with self.assertRaisesRegex(BuildError, "attempt mismatch"):
            self.check()

    def test_wrong_image_cannot_supply_proof(self):
        self.proof["image_id"] = "sha256:" + "d" * 64; self.seal()
        with self.assertRaisesRegex(BuildError, "image mismatch"):
            self.check()

    def test_other_task_cannot_supply_proof(self):
        self.proof["task_hash"] = "sha256:" + "f" * 64; self.seal()
        with self.assertRaisesRegex(BuildError, "task mismatch"):
            self.check()

    def test_rehashed_authority_claim_is_rejected(self):
        self.proof["independent_verification"] = True; self.seal()
        with self.assertRaisesRegex(BuildError, "upgrade authority"):
            self.check()

    def test_no_completed_work_cannot_supply_proof(self):
        self.proof["summary"]["completed_count"] = 0
        self.proof["summary"].pop("receipt_hash")
        self.proof["summary"]["receipt_hash"] = object_hash(self.proof["summary"])
        self.seal()
        with self.assertRaisesRegex(BuildError, "completed candidate"):
            self.check()

    def test_replay_job_is_read_only_and_uses_exact_artifact_id(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/foundation-ci.yml").read_text()
        replay = workflow.split("  candidate-replay:", 1)[1]
        self.assertIn("needs: validate", replay)
        self.assertIn("artifact-ids: ${{ needs.validate.outputs.candidate_artifact_id }}", replay)
        self.assertIn("persist-credentials: false", replay)
        self.assertIn("contents: read", replay)
        self.assertNotIn(": write", replay)
        self.assertIn("python -m software_factory.validate_candidate_replay", replay)
        self.assertIn("needs.validate.outputs.candidate_image_ref", replay)
        self.assertIn("github.run_attempt", replay)


if __name__ == "__main__":
    unittest.main()
