import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from repair.repair_engine import failure_to_task, hashv
from scheduler.autonomous_scheduler import _candidate, _work_packet, load_state
from software_factory.candidate_worker import object_hash
from software_factory.complete_repair_work import finalize_scheduler_repair
from software_factory.repair_cycle_input import RepairCycleInputError, select_repair
from software_factory.repair_plan_artifact_state import _plan_from_zip
from software_factory.repair_cost_artifact_state import _state_from_zip
from cost_governor.cost_governor import load_state as load_cost_state


AT = "2026-09-29T13:00:00Z"


def ready_task():
    failure = {
        "schema_version": "1.0.0",
        "failure_id": "RFAIL-CYCLE-FIXTURE",
        "source_type": "FAILURE_PACKET",
        "project_ids": ["PRJ-000"],
        "target_repository_id": "REPO-008",
        "target_paths": ["software_factory/candidate_worker.py"],
        "failure_class": "REGRESSION",
        "observation": "Pinned fixture reproduces one bounded failure.",
        "reproduction_steps": ["python -m unittest tests.test_fixture"],
        "evidence_refs": ["fixture:repair-cycle"],
        "regression_test_requirement": "Add a regression that fails on the exact source and passes after repair.",
        "evidence_state": "VERIFIED",
        "sensitive_material_involved": False,
        "benchmark_contaminated": False,
        "reported_at": AT,
    }
    task = failure_to_task(failure)
    assert task["state"] == "READY_FOR_REPAIR"
    return task


def scheduler_with(task):
    candidate = _candidate(
        "REPAIR", task["repair_task_id"], task["project_ids"],
        "AGT-ENGINEER", "ISOLATED_IMPLEMENTATION", "MODIFY", "HIGH",
        reason="verified fixture repair",
        evidence_refs=[*task["evidence_refs"], "repair:" + task["repair_task_id"]],
    )
    state = load_state()
    work = _work_packet(candidate, AT)
    state["work_items"] = [work]
    return state, work


def submission(work):
    core = {
        "schema_version": 1,
        "status": "REMOTE_CANDIDATE_SUBMITTED",
        "submission_key": "sha256:" + "1" * 64,
        "task_id": "BUILD-AUTO-FIXTURE",
        "task_hash": "sha256:" + "2" * 64,
        "source_ref": work["source_ref"],
        "repository": "P00NSMASHER/portfolio-brain",
        "base_sha": "a" * 40,
        "branch_name": "factory/build-auto-fixture/attempt-1",
        "local_candidate_commit_sha": "b" * 40,
        "candidate_git_tree_sha": "c" * 40,
        "remote_commit_sha": "d" * 40,
        "remote_tree_sha": "c" * 40,
        "changed_paths": ["software_factory/candidate_worker.py", "tests/test_factory_generated_fixture.py"],
        "mutation_performed_this_run": True,
        "remote_candidate_present": True,
        "independent_verification": False,
        "pr_created": False,
        "production_changed": False,
        "merge_authorized": False,
        "deployment_authorized": False,
    }
    return {**core, "receipt_hash": object_hash(core)}


class RepairCycleActivationTests(unittest.TestCase):
    def test_selects_exact_ready_repair_and_stable_lineage(self):
        task = ready_task()
        state, work = scheduler_with(task)
        repair_state = {"tasks": [task]}
        first = select_repair(state, base_sha="a" * 40, repair_state=repair_state)
        second = select_repair(state, base_sha="a" * 40, repair_state=repair_state)
        self.assertEqual(first["source_ref"], task["repair_task_id"])
        self.assertEqual(first["scheduler_work_id"], work["scheduler_work_id"])
        self.assertEqual(first["lineage_id"], second["lineage_id"])
        self.assertEqual(first["repository"], "P00NSMASHER/portfolio-brain")
        self.assertFalse(first["authority_granted"])

    def test_no_repair_work_is_a_clean_noop(self):
        state = load_state()
        self.assertIsNone(select_repair(state, base_sha="a" * 40, repair_state={"tasks": []}))

    def test_stale_or_nonready_source_cannot_be_selected(self):
        task = ready_task()
        state, _ = scheduler_with(task)
        task = json.loads(json.dumps(task))
        task["state"] = "BLOCKED"
        body = dict(task)
        body.pop("task_hash")
        task["task_hash"] = hashv(body)
        with self.assertRaisesRegex(RepairCycleInputError, "READY_FOR_REPAIR"):
            select_repair(state, base_sha="a" * 40, repair_state={"tasks": [task]})

    def test_remote_candidate_completes_exact_scheduler_repair_once(self):
        task = ready_task()
        state, work = scheduler_with(task)
        receipt = submission(work)
        updated, disposition = finalize_scheduler_repair(
            state, work=work, submission=receipt, at="2026-09-29T13:01:00Z")
        self.assertEqual(disposition, "COMPLETED")
        self.assertEqual(updated["work_items"][0]["state"], "COMPLETE")
        self.assertIn(work["fingerprint"], updated["completed_fingerprints"])
        again, disposition = finalize_scheduler_repair(
            updated, work=work, submission=receipt, at="2026-09-29T13:02:00Z")
        self.assertEqual(disposition, "ALREADY_COMPLETE")
        self.assertEqual(again, updated)

    def test_submission_for_different_repair_cannot_complete_work(self):
        task = ready_task()
        state, work = scheduler_with(task)
        receipt = submission(work)
        receipt["source_ref"] = "RTASK-OTHER"
        body = dict(receipt); body.pop("receipt_hash")
        receipt["receipt_hash"] = object_hash(body)
        with self.assertRaisesRegex(Exception, "source mismatch"):
            finalize_scheduler_repair(state, work=work, submission=receipt, at=AT)

    def test_tampered_submission_receipt_cannot_complete_work(self):
        task = ready_task()
        state, work = scheduler_with(task)
        receipt = submission(work)
        receipt["remote_commit_sha"] = "e" * 40
        with self.assertRaisesRegex(Exception, "hash mismatch"):
            finalize_scheduler_repair(state, work=work, submission=receipt, at=AT)

    def test_prior_plan_zip_must_match_exact_lineage(self):
        plan = {"lineage_id": "RPLAN-EXACT", "task_hash": "sha256:" + "a" * 64, "task": {}}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("nested/repair_plan.json", json.dumps(plan))
        self.assertEqual(_plan_from_zip(buffer.getvalue(), "RPLAN-EXACT"), plan)
        self.assertIsNone(_plan_from_zip(buffer.getvalue(), "RPLAN-OTHER"))

    def test_repair_cost_restore_accepts_only_valid_cost_state(self):
        state = load_cost_state()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("cost_state.json", json.dumps(state))
        self.assertEqual(_state_from_zip(buffer.getvalue()), state)
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("cost_state.json", "{}")
        self.assertIsNone(_state_from_zip(bad.getvalue()))


if __name__ == "__main__":
    unittest.main()
