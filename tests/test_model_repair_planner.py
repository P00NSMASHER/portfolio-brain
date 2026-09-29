import copy
import json
from pathlib import Path
import tempfile
import unittest

from software_factory.candidate_worker import digest, object_hash, validate_task
from software_factory.model_repair_planner import (
    RepairPlannerError, build_model_request, plan_repair,
)


SOURCE = b'''def parse_count(value):
    return int(value)
'''

TEST_SOURCE = '''import unittest
from src.module import parse_count

class GeneratedRepairRegression(unittest.TestCase):
    def test_boolean_is_rejected(self):
        with self.assertRaises(ValueError, msg="BOOL_COUNT_REJECTED"):
            parse_count(True)
'''


def repair_task_fixture():
    task = {
        "repair_task_id": "RTASK-PLANNER-FIXTURE",
        "failure_id": "RFAIL-PLANNER-FIXTURE",
        "project_ids": ["PRJ-000"],
        "target_repository_id": "REPO-008",
        "target_paths": ["src/"],
        "state": "READY_FOR_REPAIR",
        "regression_test_requirement": "Boolean inputs must be rejected by parse_count.",
        "task_hash": "sha256:" + "a" * 64,
    }
    return task


def work_fixture():
    return {
        "scheduler_work_id": "SWORK-PLANNER-FIXTURE",
        "source_ref": "RTASK-PLANNER-FIXTURE",
        "project_ids": ["PRJ-000"],
        "assigned_agent_id": "AGT-ENGINEER",
        "required_authority": "MODIFY",
        "work_type": "REPAIR",
    }


def model_output(path="src/module.py", before="    return int(value)"):
    return json.dumps({
        "edits": [{
            "path": path,
            "before": before,
            "after": '    if isinstance(value, bool):\n        raise ValueError("boolean count")\n    return int(value)',
        }],
        "test_source": TEST_SOURCE,
        "baseline_failure_marker": "BOOL_COUNT_REJECTED",
    })


class RepairPlannerTests(unittest.TestCase):
    def setUp(self):
        self.work = work_fixture()
        self.repair = repair_task_fixture()
        self.snapshot = {"src/module.py": SOURCE, "README.md": b"fixture\n"}
        self.cost = {"fixture_sequence": 0}
        self.calls = 0

    def executor(self, request, prompt, state, **kwargs):
        self.calls += 1
        self.last_request = request
        self.last_prompt = prompt
        next_state = {"fixture_sequence": state["fixture_sequence"] + 1, "charged": True}
        return next_state, {
            "output_text": model_output(),
            "receipt": {"receipt_hash": "sha256:" + "b" * 64},
        }

    def plan(self, **kwargs):
        return plan_repair(
            work=self.work,
            repair_task=self.repair,
            base_sha="1" * 40,
            checkout=Path("."),
            cost_state=self.cost,
            snapshot_override=self.snapshot,
            executor=kwargs.pop("executor", self.executor),
            **kwargs,
        )

    def test_model_plan_becomes_exact_hash_bound_candidate_task(self):
        state, result = self.plan()
        self.assertEqual(self.calls, 1)
        self.assertTrue(result["model_call_performed"])
        self.assertFalse(result["reused"])
        self.assertTrue(state["charged"])
        task = result["task"]
        self.assertEqual(task["source_ref"], self.work["source_ref"])
        self.assertEqual(task["repository"], "P00NSMASHER/portfolio-brain")
        self.assertEqual(task["edits"][0]["source_sha256"], digest(SOURCE))
        self.assertEqual(result["task_hash"], object_hash(task))
        validate_task(task, result["task_hash"])
        self.assertTrue(task["test_path"].startswith("tests/test_factory_generated_"))
        self.assertFalse(result["planning_receipt"]["authority_granted"])
        self.assertFalse(result["planning_receipt"]["independent_verification"])

    def test_repeat_same_lineage_reuses_plan_without_model_call_or_cost(self):
        state, first = self.plan()
        self.assertEqual(self.calls, 1)
        def forbidden(*args, **kwargs):
            self.fail("repeat lineage must not execute provider")
        second_state, second = plan_repair(
            work=self.work, repair_task=self.repair, base_sha="1" * 40,
            checkout=Path("."), cost_state=state, prior_plan=first,
            snapshot_override=self.snapshot, executor=forbidden)
        self.assertEqual(second_state, state)
        self.assertTrue(second["reused"])
        self.assertFalse(second["model_call_performed"])
        self.assertEqual(second["task_hash"], first["task_hash"])

    def test_new_base_revision_cannot_reuse_old_plan(self):
        _, first = self.plan()
        with self.assertRaisesRegex(RepairPlannerError, "lineage mismatch"):
            plan_repair(
                work=self.work, repair_task=self.repair, base_sha="2" * 40,
                checkout=Path("."), cost_state=self.cost, prior_plan=first,
                snapshot_override=self.snapshot, executor=lambda *a, **k: self.fail("must not call"))

    def test_invalid_model_output_preserves_charged_cost_state_on_error(self):
        def bad_executor(request, prompt, state, **kwargs):
            return {"fixture_sequence": 1, "charged": True}, {
                "output_text": '{"edits":[]}',
                "receipt": {"receipt_hash": "sha256:" + "c" * 64},
            }
        with self.assertRaises(RepairPlannerError) as raised:
            self.plan(executor=bad_executor)
        self.assertEqual(raised.exception.cost_state, {"fixture_sequence": 1, "charged": True})

    def test_provider_failure_propagates_durable_cost_state(self):
        from model_router.openai_executor import OpenAIExecutorError
        def fail(request, prompt, state, **kwargs):
            raise OpenAIExecutorError("provider failed", cost_state={"fixture_sequence": 9, "charged": True})
        with self.assertRaises(RepairPlannerError) as raised:
            self.plan(executor=fail)
        self.assertEqual(raised.exception.cost_state["fixture_sequence"], 9)

    def test_model_cannot_edit_outside_admitted_target(self):
        def outside(request, prompt, state, **kwargs):
            return state, {"output_text": model_output(path="README.md"), "receipt": {}}
        with self.assertRaisesRegex(RepairPlannerError, "outside admitted target"):
            self.plan(executor=outside)

    def test_model_cannot_edit_tests_even_if_failure_target_is_tests(self):
        self.repair["target_paths"] = ["tests/"]
        self.snapshot = {"tests/test_existing.py": b"VALUE = 1\n"}
        def tests(request, prompt, state, **kwargs):
            output = json.dumps({
                "edits": [{"path": "tests/test_existing.py", "before": "VALUE = 1", "after": "VALUE = 2"}],
                "test_source": TEST_SOURCE,
                "baseline_failure_marker": "BOOL_COUNT_REJECTED",
            })
            return state, {"output_text": output, "receipt": {}}
        with self.assertRaisesRegex(RepairPlannerError, "cannot edit tests"):
            self.plan(executor=tests)

    def test_ambiguous_before_text_is_rejected(self):
        self.snapshot["src/module.py"] = SOURCE + SOURCE
        def ambiguous(request, prompt, state, **kwargs):
            return state, {"output_text": model_output(), "receipt": {}}
        with self.assertRaisesRegex(RepairPlannerError, "absent or ambiguous"):
            self.plan(executor=ambiguous)

    def test_failure_marker_must_be_present_in_generated_test(self):
        def missing(request, prompt, state, **kwargs):
            body = json.loads(model_output())
            body["baseline_failure_marker"] = "MISSING_MARKER"
            return state, {"output_text": json.dumps(body), "receipt": {}}
        with self.assertRaisesRegex(RepairPlannerError, "failure marker"):
            self.plan(executor=missing)

    def test_stable_lineage_produces_stable_model_request(self):
        _, first = self.plan()
        request_one = copy.deepcopy(self.last_request)
        self.calls = 0
        _, second = self.plan()
        request_two = self.last_request
        self.assertEqual(first["lineage_id"], second["lineage_id"])
        self.assertEqual(request_one["request_id"], request_two["request_id"])
        self.assertEqual(request_one["evidence_refs"], request_two["evidence_refs"])

    def test_model_request_is_bounded_tier2_debugging(self):
        request = build_model_request(
            lineage="RPLAN-X", project_ids=["PRJ-000"], evidence_hash="sha256:" + "d" * 64)
        self.assertEqual(request["task_kind"], "DEBUGGING")
        self.assertEqual(request["authority_class"], "MODIFY")
        self.assertLessEqual(request["max_cost_usd"], 0.08)
        self.assertLessEqual(request["max_output_tokens"], 2500)
        self.assertEqual(request["provider_allowlist"], ["openai"])


if __name__ == "__main__":
    unittest.main()
