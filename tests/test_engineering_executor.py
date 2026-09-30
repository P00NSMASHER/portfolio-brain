"""The repair handler must preserve task identity and existing admission controls."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scheduler import engineering_executor as handler
from software_factory.candidate_worker import BuildError, object_hash
try:
    from .test_candidate_worker import SOURCE, snapshot_fixture, task_fixture, trusted_fixture_runner
except ImportError:
    from test_candidate_worker import SOURCE, snapshot_fixture, task_fixture, trusted_fixture_runner


class EngineeringHandlerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = task_fixture()
        self.work = {"scheduler_work_id": "SWORK-TEST", "source_ref": self.task["source_ref"],
                     "project_ids": ["PRJ-000"], "assigned_agent_id": "AGT-ENGINEER",
                     "required_authority": "MODIFY", "work_type": "REPAIR"}
        self.config = {"tasks": [{"source_ref": self.task["source_ref"], "task_hash": object_hash(self.task),
                                  "task": self.task}], "checkout": self.root,
                       "output_root": self.root / "proof", "runner": trusted_fixture_runner}
        self.context = {"candidate_build_configuration": self.config}
        self.policy = {"repository_policies": [{"repository_full_name": self.task["repository"],
                                                "candidate_modify_enabled": True}],
                       "forbidden_candidate_paths": [".github/", "cost_governor/"]}
        self.mocks = [patch.object(handler, "_kill_state", return_value=False),
                      patch.object(handler, "_factory_policy", return_value=self.policy),
                      patch.object(handler, "load_snapshot", return_value=snapshot_fixture())]
        for mock in self.mocks:
            mock.start(); self.addCleanup(mock.stop)

    def run_handler(self):
        return handler.repair_handler(self.work, self.context)

    def test_measured_candidate_is_not_claimed_as_delivered(self):
        result = self.run_handler()
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["result_kind"], "CANDIDATE_BUILD_TESTED")
        self.assertEqual(result["result"]["delivered_improvements"], 0)
        self.assertFalse(result["result"]["independent_verification"])
        self.assertFalse(result["result"]["production_changed"])

    def test_missing_task_is_deferred(self):
        self.config["tasks"] = []
        self.assertEqual(self.run_handler()["result_kind"], "NO_UNIQUE_APPROVED_BUILD_TASK")

    def test_duplicate_task_is_deferred(self):
        self.config["tasks"] *= 2
        self.assertEqual(self.run_handler()["status"], "DEFERRED")

    def test_downstream_not_onboarded_is_deferred(self):
        self.policy["repository_policies"][0]["candidate_modify_enabled"] = False
        self.assertEqual(self.run_handler()["result_kind"], "BUILD_REPOSITORY_NOT_ONBOARDED")

    def test_kill_switch_is_honored(self):
        with patch.object(handler, "_kill_state", return_value=True):
            self.assertEqual(self.run_handler()["result_kind"], "BUILD_KILL_SWITCH_ACTIVE")

    def test_wrong_role_is_deferred(self):
        self.work["assigned_agent_id"] = "AGT-HUNTER"
        self.assertEqual(self.run_handler()["result_kind"], "BUILD_ROLE_OR_AUTHORITY_MISMATCH")

    def test_wrong_authority_is_deferred(self):
        self.work["required_authority"] = "OBSERVE"
        self.assertEqual(self.run_handler()["status"], "DEFERRED")

    def test_project_identity_cannot_be_borrowed(self):
        self.work["project_ids"] = ["PRJ-OTHER"]
        with self.assertRaisesRegex(BuildError, "not bound"):
            self.run_handler()

    def test_task_hash_cannot_be_self_upgraded(self):
        self.task["edits"][0]["after"] += "\n# changed"
        with self.assertRaisesRegex(BuildError, "approved hash"):
            self.run_handler()

    def test_factory_forbidden_paths_stay_forbidden(self):
        self.policy["forbidden_candidate_paths"].append("parser.py")
        with self.assertRaisesRegex(BuildError, "factory forbids"):
            self.run_handler()

    def test_missing_sandbox_defers_without_host_fallback(self):
        del self.config["runner"]
        self.assertEqual(self.run_handler()["result_kind"], "BUILD_ISOLATED_RUNTIME_NOT_CONFIGURED")

    def test_cycle_deadline_prevents_more_test_execution(self):
        self.context["candidate_build_deadline"] = 0
        with self.assertRaisesRegex(BuildError, "deadline"):
            self.run_handler()

    def test_scheduler_completion_requires_real_success(self):
        # Only this repository-integration case needs the complete checkout.
        try:
            from scheduler.autonomous_scheduler import _candidate, _work_packet, load_state
            from scheduler.work_executor import execute_cycle
        except ModuleNotFoundError:
            self.skipTest("full-repository integration is run in GitHub CI")
        candidate = _candidate("REPAIR", self.task["source_ref"], ["PRJ-000"], "AGT-ENGINEER",
                               "ISOLATED_IMPLEMENTATION", "MODIFY", "LOW",
                               reason="explicit test fixture", evidence_refs=["fixture:build-worker"])
        state = load_state()
        state["work_items"] = [_work_packet(candidate, "2026-09-29T05:00:00Z")]
        updated, receipts, executed, meta = execute_cycle(
            state, runtime_state={}, handlers=handler.handler_table(), max_items=1,
            context_overrides=self.context, at="2026-09-29T05:00:00Z")
        self.assertEqual(updated["work_items"][0]["state"], "COMPLETE")
        self.assertEqual(meta["summary"]["attempted_count"], 1)
        self.assertEqual(meta["summary"]["completed_count"], 1)
        self.assertEqual(receipts[0]["result"]["delivered_improvements"], 0)
        # A second task with a broken fix must remain queued, not become COMPLETE.
        self.task["edits"][0]["after"] = "    return int(value) + 1"
        self.config["tasks"][0]["task_hash"] = object_hash(self.task)
        updated, receipts, executed, meta = execute_cycle(
            state, runtime_state={}, handlers=handler.handler_table(), max_items=1,
            context_overrides=self.context, at="2026-09-29T05:01:00Z")
        self.assertEqual(updated["work_items"][0]["state"], "QUEUED")
        self.assertEqual(meta["summary"]["completed_count"], 0)
        self.assertEqual(meta["summary"]["deferred_count"], 1)
        self.assertEqual(executed, [])


if __name__ == "__main__":
    unittest.main()
