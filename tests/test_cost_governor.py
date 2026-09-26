import copy
import os
import unittest
from unittest.mock import patch

from model_router.model_router import prepare_governed_execution
from cost_governor.cancel_managed_jobs import managed_run_ids
from cost_governor.cost_governor import (
    CostGovernorError,
    cancel_reservation,
    commit_reservation,
    hard_stop_reason,
    load_state,
    make_github_job_request,
    policy,
    preflight,
    reserve_model_execution,
    validate_request,
    zero_usage,
)


AT = "2026-09-25T12:00:00Z"


def github_request(*, run_id="100", attempt=1, minutes=5, workflow="portfolio-autonomous-scheduler", job="schedule", authority="OBSERVE", at=AT):
    return make_github_job_request(
        workflow_id=workflow,
        job_id=job,
        run_id=run_id,
        attempt=attempt,
        project_ids=["PRJ-000"],
        estimated_minutes=minutes,
        authority_class=authority,
        at=at,
    )


class CostGovernorTests(unittest.TestCase):
    def test_checked_in_paid_budget_is_finite_and_nonzero(self):
        p = policy()
        self.assertGreater(p["portfolio_ceiling"]["cost_usd"], 0)
        self.assertGreater(p["portfolio_ceiling"]["model_calls"], 0)
        self.assertGreater(p["portfolio_ceiling"]["api_calls"], 0)
        for field in ("cost_usd", "input_tokens", "output_tokens", "model_calls", "api_calls"):
            self.assertGreaterEqual(p["portfolio_ceiling"][field], 0)

    def test_managed_github_job_reserves_before_execution(self):
        state, decision = preflight(load_state(), github_request(), at=AT)
        self.assertEqual(decision["status"], "RESERVED")
        self.assertTrue(decision["can_execute"])
        self.assertFalse(decision["authority_granted"])
        self.assertEqual(len(state["reservations"]), 1)

    def test_exact_duplicate_is_suppressed(self):
        request = github_request()
        state, first = preflight(load_state(), request, at=AT)
        state, second = preflight(state, request, at=AT)
        self.assertEqual(first["status"], "RESERVED")
        self.assertEqual(second["status"], "DUPLICATE_SUPPRESSED")
        self.assertFalse(second["can_execute"])
        self.assertEqual(len(state["reservations"]), 1)

    def test_idempotency_collision_fails_closed(self):
        request = github_request()
        state, _ = preflight(load_state(), request, at=AT)
        changed = copy.deepcopy(request)
        changed["evidence_refs"] = [*changed["evidence_refs"], "changed:evidence"]
        state, decision = preflight(state, changed, at=AT)
        self.assertEqual(decision["status"], "BLOCKED_IDEMPOTENCY_COLLISION")
        self.assertFalse(decision["can_execute"])

    def test_retry_sequence_cannot_start_at_three(self):
        _, decision = preflight(load_state(), github_request(attempt=3), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_RETRY_LIMIT")
        self.assertIn("RETRY_LIMIT_EXCEEDED", decision["reason_codes"])

    def test_act_can_never_be_authorized_by_cost_budget(self):
        _, decision = preflight(load_state(), github_request(authority="ACT"), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_AUTHORITY")
        self.assertFalse(decision["authority_granted"])

    def test_environment_kill_switch_blocks_new_work(self):
        with patch.dict(os.environ, {"PORTFOLIO_SPEND_DISABLED": "true"}):
            _, decision = preflight(load_state(), github_request(), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_KILL_SWITCH")

    def test_unconfigured_workflow_job_fails_closed(self):
        _, decision = preflight(load_state(), github_request(workflow="unknown-workflow"), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any(x.startswith("UNCONFIGURED_WORKFLOW_JOB:") for x in decision["reason_codes"]))

    def test_per_job_minute_ceiling_is_enforced(self):
        _, decision = preflight(load_state(), github_request(minutes=6), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any(x.startswith("JOB_MINUTE_CEILING_EXCEEDED:") for x in decision["reason_codes"]))

    def test_portfolio_scope_is_independent(self):
        p = copy.deepcopy(policy())
        p["portfolio_ceiling"]["github_job_starts"] = 0
        p["portfolio_ceiling"]["github_runner_minutes"] = 0
        _, decision = preflight(load_state(), github_request(), at=AT, policy_data=p)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any("portfolio:github_job_starts" in x for x in decision["reason_codes"]))

    def test_project_scope_is_independent(self):
        p = copy.deepcopy(policy())
        p["project_overrides"]["PRJ-000"]["github_job_starts"] = 0
        p["project_overrides"]["PRJ-000"]["github_runner_minutes"] = 0
        _, decision = preflight(load_state(), github_request(), at=AT, policy_data=p)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any("project:PRJ-000:github_job_starts" in x for x in decision["reason_codes"]))

    def test_workflow_job_scope_is_independent(self):
        p = copy.deepcopy(policy())
        cfg = p["workflow_job_ceilings"]["portfolio-autonomous-scheduler::schedule"]["daily_ceiling"]
        cfg["github_job_starts"] = 0
        cfg["github_runner_minutes"] = 0
        _, decision = preflight(load_state(), github_request(), at=AT, policy_data=p)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any("workflow_job:portfolio-autonomous-scheduler::schedule:github_job_starts" in x for x in decision["reason_codes"]))

    def test_expired_unknown_execution_remains_charged_for_day(self):
        p = copy.deepcopy(policy())
        for ceiling in (
            p["portfolio_ceiling"],
            p["project_overrides"]["PRJ-000"],
            p["workflow_job_ceilings"]["portfolio-autonomous-scheduler::schedule"]["daily_ceiling"],
        ):
            ceiling["github_job_starts"] = 1
            ceiling["github_runner_minutes"] = 5
        first_at = "2026-09-25T00:00:00Z"
        state, first = preflight(load_state(), github_request(run_id="1", at=first_at), at=first_at, policy_data=p)
        self.assertEqual(first["status"], "RESERVED")
        later = "2026-09-25T07:00:00Z"
        state, second = preflight(state, github_request(run_id="2", at=later), at=later, policy_data=p)
        self.assertEqual(second["status"], "BLOCKED_BUDGET")
        self.assertEqual(state["reservations"][0]["status"], "EXPIRED")

    def test_cancelled_reservation_releases_compute_capacity(self):
        p = copy.deepcopy(policy())
        for ceiling in (
            p["portfolio_ceiling"],
            p["project_overrides"]["PRJ-000"],
            p["workflow_job_ceilings"]["portfolio-autonomous-scheduler::schedule"]["daily_ceiling"],
        ):
            ceiling["github_job_starts"] = 1
            ceiling["github_runner_minutes"] = 5
        state, first = preflight(load_state(), github_request(run_id="1"), at=AT, policy_data=p)
        state = cancel_reservation(state, first["reservation_id"], at=AT, policy_data=p)
        state, second = preflight(state, github_request(run_id="2"), at=AT, policy_data=p)
        self.assertEqual(second["status"], "RESERVED")

    def test_actual_usage_overage_trips_hard_stop(self):
        state, decision = preflight(load_state(), github_request(minutes=1), at=AT)
        actual = zero_usage()
        actual.update({"github_job_starts": 1, "github_runner_minutes": 2})
        state, commit = commit_reservation(state, decision["reservation_id"], actual, at=AT)
        self.assertEqual(commit["status"], "HARD_STOP_OVERAGE")
        self.assertEqual(hard_stop_reason(state, at=AT), "CURRENT_DAY_RESERVATION_OVERAGE")

    def test_cost_request_rejects_payload_fields(self):
        request = github_request()
        request["prompt"] = "must-not-persist"
        with self.assertRaises(CostGovernorError):
            validate_request(request)

    def test_tier0_model_path_requires_no_paid_reservation(self):
        route = {"status": "ROUTED", "tier": 0}
        state = load_state()
        out, decision = reserve_model_execution(state, route, {"authority_class": "OBSERVE"})
        self.assertIs(out, state)
        self.assertEqual(decision["status"], "TIER0_NO_SPEND")
        self.assertTrue(decision["can_execute"])

    def test_tier0_act_is_not_cost_authorized(self):
        route = {"status": "ROUTED", "tier": 0}
        _, decision = reserve_model_execution(load_state(), route, {"authority_class": "ACT"})
        self.assertEqual(decision["status"], "BLOCKED_AUTHORITY")
        self.assertFalse(decision["can_execute"])

    def test_non_tier0_model_route_can_reserve_within_finite_budget(self):
        route = {
            "status": "ROUTED",
            "tier": 2,
            "route_id": "MRT-SYNTHETIC",
            "provider_id": "approved-api-slot",
            "model_id": "UNCONFIGURED_STRONG",
            "max_estimated_cost_usd": 0.01,
            "route_hash": "sha256:synthetic",
        }
        request = {
            "request_id": "MRQ-SYNTHETIC",
            "project_ids": ["PRJ-000"],
            "max_input_tokens": 100,
            "max_output_tokens": 100,
            "authority_class": "OBSERVE",
            "data_classification": "SANITIZED",
        }
        _, decision = reserve_model_execution(load_state(), route, request, at=AT)
        self.assertEqual(decision["status"], "RESERVED")
        self.assertTrue(decision["can_execute"])

    def test_model_router_tier0_path_is_cost_gated_without_granting_authority(self):
        request = {
            "schema_version": "1.0.0",
            "request_id": "MRQ-COST-TIER0",
            "project_ids": ["PRJ-000"],
            "task_kind": "SCHEMA_VALIDATION",
            "deterministic_sufficient": True,
            "consequence": "LOW",
            "data_classification": "SANITIZED",
            "authority_class": "OBSERVE",
            "requires_independent_adversarial": False,
            "builder_independence_group": None,
            "max_cost_usd": 0.0,
            "max_input_tokens": 0,
            "max_output_tokens": 0,
            "provider_allowlist": [],
            "evidence_refs": ["test:cost-tier0"],
        }
        state, guard = prepare_governed_execution(request, load_state(), at=AT)
        self.assertTrue(guard["cost_gate_passed"])
        self.assertFalse(guard["authority_granted"])
        self.assertEqual(guard["cost_decision"]["status"], "TIER0_NO_SPEND")
        self.assertEqual(state["sequence"], 0)

    def test_model_router_tier0_act_is_blocked_by_cost_boundary(self):
        request = {
            "schema_version": "1.0.0",
            "request_id": "MRQ-COST-ACT",
            "project_ids": ["PRJ-000"],
            "task_kind": "SCHEMA_VALIDATION",
            "deterministic_sufficient": True,
            "consequence": "HIGH",
            "data_classification": "SANITIZED",
            "authority_class": "ACT",
            "requires_independent_adversarial": False,
            "builder_independence_group": None,
            "max_cost_usd": 0.0,
            "max_input_tokens": 0,
            "max_output_tokens": 0,
            "provider_allowlist": [],
            "evidence_refs": ["test:cost-act"],
        }
        _, guard = prepare_governed_execution(request, load_state(), at=AT)
        self.assertFalse(guard["cost_gate_passed"])
        self.assertEqual(guard["cost_decision"]["status"], "BLOCKED_AUTHORITY")

    def test_cancellation_filter_never_targets_foundation_ci(self):
        runs = [
            {"id": 1, "status": "in_progress", "name": "portfolio-autonomous-scheduler"},
            {"id": 2, "status": "queued", "name": "foundation-ci"},
            {"id": 3, "status": "completed", "name": "portfolio-autonomous-scheduler"},
        ]
        ids = managed_run_ids(runs, current_run_id=None, managed_names={"portfolio-autonomous-scheduler"}, limit=8)
        self.assertEqual(ids, [1])


if __name__ == "__main__":
    unittest.main()
