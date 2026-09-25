import copy
import os
import unittest
from unittest.mock import patch

from cost_governor.cancel_managed_jobs import managed_run_ids
from cost_governor.cost_governor import (
    CostGovernorError,
    commit_reservation,
    hard_stop_reason,
    load_state,
    make_github_job_request,
    preflight,
    reserve_model_execution,
    validate_request,
    zero_usage,
)

AT = "2026-09-25T21:20:00Z"

def scheduler_job(*, run_id="100", attempt=1, workflow="portfolio-autonomous-scheduler", project="PRJ-000", minutes=5, authority="OBSERVE"):
    return make_github_job_request(
        workflow_id=workflow,
        job_id="schedule" if workflow == "portfolio-autonomous-scheduler" else "job",
        run_id=run_id,
        attempt=attempt,
        project_ids=[project],
        estimated_minutes=minutes,
        authority_class=authority,
        at=AT,
    )

class CostGovernorTests(unittest.TestCase):
    def test_configured_github_job_reserves_before_execution(self):
        state, decision = preflight(load_state(), scheduler_job(), at=AT)
        self.assertEqual(decision["status"], "RESERVED")
        self.assertTrue(decision["can_execute"])
        self.assertEqual(state["reservations"][0]["estimated_usage"]["github_runner_minutes"], 5)

    def test_duplicate_idempotency_does_not_spend_twice(self):
        state, _ = preflight(load_state(), scheduler_job(), at=AT)
        state, decision = preflight(state, scheduler_job(), at=AT)
        self.assertEqual(decision["status"], "DUPLICATE_SUPPRESSED")
        self.assertEqual(len(state["reservations"]), 1)

    def test_idempotency_collision_fails_closed(self):
        state, _ = preflight(load_state(), scheduler_job(), at=AT)
        changed = scheduler_job()
        changed["estimated_usage"]["github_runner_minutes"] = 4
        state, decision = preflight(state, changed, at=AT)
        self.assertEqual(decision["status"], "BLOCKED_IDEMPOTENCY_COLLISION")
        self.assertEqual(len(state["reservations"]), 1)

    def test_retry_group_cannot_reset_or_exceed_limit(self):
        state, _ = preflight(load_state(), scheduler_job(run_id="200", attempt=1), at=AT)
        state, second = preflight(state, scheduler_job(run_id="200", attempt=2), at=AT)
        self.assertEqual(second["status"], "RESERVED")
        state, third = preflight(state, scheduler_job(run_id="200", attempt=3), at=AT)
        self.assertEqual(third["status"], "BLOCKED_RETRY_LIMIT")

    def test_unconfigured_workflow_job_fails_closed(self):
        request = make_github_job_request(
            workflow_id="unknown-workflow",
            job_id="unknown-job",
            run_id="300",
            attempt=1,
            project_ids=["PRJ-000"],
            estimated_minutes=1,
            authority_class="OBSERVE",
            at=AT,
        )
        _, decision = preflight(load_state(), request, at=AT)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any(x.startswith("UNCONFIGURED_WORKFLOW_JOB") for x in decision["reason_codes"]))

    def test_project_ceiling_is_independent_scope(self):
        p = copy.deepcopy(__import__("cost_governor.cost_governor", fromlist=["policy"]).policy())
        p["portfolio_ceiling"]["github_runner_minutes"] = 500
        p["portfolio_ceiling"]["github_job_starts"] = 500
        p["workflow_job_ceilings"]["portfolio-autonomous-scheduler::schedule"]["max_minutes_per_job"] = 200
        p["workflow_job_ceilings"]["portfolio-autonomous-scheduler::schedule"]["daily_ceiling"]["github_runner_minutes"] = 500
        p["workflow_job_ceilings"]["portfolio-autonomous-scheduler::schedule"]["daily_ceiling"]["github_job_starts"] = 500
        request = scheduler_job(project="PRJ-UNREGISTERED", minutes=161)
        _, decision = preflight(load_state(), request, at=AT, policy_data=p)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertIn("BUDGET_EXCEEDED:project:PRJ-UNREGISTERED:github_runner_minutes", decision["reason_codes"])

    def test_paid_model_route_is_blocked_by_checked_in_zero_budget(self):
        route = {
            "route_id": "MRT-SYNTH",
            "route_hash": "sha256:" + "a" * 64,
            "status": "ROUTED",
            "tier": 2,
            "provider_id": "approved-api-slot",
            "model_id": "UNCONFIGURED_STRONG",
            "max_estimated_cost_usd": 0.01,
        }
        request = {
            "request_id": "MRQ-SYNTH",
            "project_ids": ["PRJ-000"],
            "authority_class": "OBSERVE",
            "data_classification": "SANITIZED",
            "max_input_tokens": 100,
            "max_output_tokens": 50,
        }
        _, decision = reserve_model_execution(load_state(), route, request, at=AT)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any("input_tokens" in reason or "model_calls" in reason for reason in decision["reason_codes"]))

    def test_tier0_needs_no_model_api_reservation(self):
        route = {"status": "ROUTED", "tier": 0}
        request = {
            "request_id": "MRQ-DET",
            "project_ids": ["PRJ-000"],
            "authority_class": "OBSERVE",
            "data_classification": "SANITIZED",
            "max_input_tokens": 0,
            "max_output_tokens": 0,
        }
        state, decision = reserve_model_execution(load_state(), route, request, at=AT)
        self.assertEqual(decision["status"], "TIER0_NO_SPEND")
        self.assertEqual(state["sequence"], 0)

    def test_act_budget_request_is_rejected(self):
        request = scheduler_job(authority="ACT")
        with self.assertRaises(CostGovernorError):
            # CLI builder intentionally cannot emit ACT; direct mutation proves validator/governor boundary.
            validate_request({**request, "authority_class": "ACT"})
        # A syntactically valid request constructed outside the CLI still cannot receive cost authority.
        request["authority_class"] = "ACT"
        state, decision = preflight(load_state(), request, at=AT)
        self.assertEqual(decision["status"], "BLOCKED_AUTHORITY")
        self.assertFalse(decision["authority_granted"])

    def test_overage_commits_usage_and_triggers_hard_stop(self):
        state, decision = preflight(load_state(), scheduler_job(run_id="400"), at=AT)
        actual = zero_usage()
        actual.update({"github_job_starts": 1, "github_runner_minutes": 6})
        state, commit = commit_reservation(state, decision["reservation_id"], actual, at=AT)
        self.assertEqual(commit["status"], "HARD_STOP_OVERAGE")
        self.assertEqual(state["reservations"][0]["actual_usage"]["github_runner_minutes"], 6)
        self.assertEqual(hard_stop_reason(state, at=AT), "CURRENT_DAY_RESERVATION_OVERAGE")

    def test_environment_kill_switch_blocks_new_reservation(self):
        with patch.dict(os.environ, {"PORTFOLIO_SPEND_DISABLED": "true"}):
            _, decision = preflight(load_state(), scheduler_job(run_id="500"), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_KILL_SWITCH")

    def test_cancellation_filter_only_targets_managed_active_runs(self):
        runs = [
            {"id": 1, "name": "portfolio-autonomous-scheduler", "status": "in_progress"},
            {"id": 2, "name": "foundation-ci", "status": "in_progress"},
            {"id": 3, "name": "hunter-autonomous-cycle", "status": "queued"},
            {"id": 4, "name": "hunter-autonomous-cycle", "status": "completed"},
        ]
        ids = managed_run_ids(runs, current_run_id=None, managed_names={"portfolio-autonomous-scheduler", "hunter-autonomous-cycle"}, limit=8)
        self.assertEqual(ids, [1, 3])

    def test_request_schema_rejects_payload_fields(self):
        request = scheduler_job(run_id="600")
        request["prompt"] = "secret payload"
        with self.assertRaises(CostGovernorError):
            validate_request(request)

if __name__ == "__main__":
    unittest.main()
