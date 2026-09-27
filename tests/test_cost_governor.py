import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from model_router.model_router import prepare_governed_execution
from cost_governor.cancel_managed_jobs import managed_run_ids
from cost_governor.workflow_gate import governed_github_attempt, measured_github_usage
from workload_control.workload_gate import evaluate as evaluate_workload, load_policy as workload_policy
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
    validate_decision_record,
    validate_request,
    validate_state,
    zero_usage,
)


AT = "2026-09-25T12:00:00Z"
ROOT = Path(__file__).resolve().parents[1]


def github_request(*, run_id="100", attempt=1, minutes=5, workflow="runtime-worker", job="runtime-sync", authority="OBSERVE", at=AT):
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

    def test_only_paid_workflows_finalize_cost_state(self):
        paid_workflows = ["model-value-proof.yml", "runtime-worker.yml"]
        for filename in paid_workflows:
            with self.subTest(workflow=filename):
                workflow = (ROOT / ".github/workflows" / filename).read_text()
                self.assertIn("portfolio-cost-governed-autonomy", workflow)
                self.assertIn("cost_governor.workflow_gate preflight", workflow)
                self.assertIn("cost_governor.workflow_gate finalize", workflow)

        nonpaid_workflows = [
            "agent-heartbeat-sweep.yml",
            "command-center-pages.yml",
            "continuous-learning-bootstrap.yml",
            "hunter-autonomous-cycle.yml",
            "portfolio-autonomous-scheduler.yml",
            "portfolio-notification-cycle.yml",
            "software-factory-candidate.yml",
            "verified-feedback-bootstrap.yml",
        ]
        for filename in nonpaid_workflows:
            with self.subTest(workflow=filename):
                workflow = (ROOT / ".github/workflows" / filename).read_text()
                self.assertIn("workload_control.workload_gate preflight", workflow)
                self.assertNotIn("cost_governor.workflow_gate preflight", workflow)
                self.assertNotIn("cost_governor.workflow_gate finalize", workflow)

    def test_watchdog_polling_is_hourly_not_quarter_hourly(self):
        workflow = (ROOT / ".github/workflows/portfolio-cost-watchdog.yml").read_text()
        self.assertIn('cron: "53 * * * *"',workflow)
        self.assertNotIn('cron: "*/15 * * * *"',workflow)
        self.assertIn("actions: write",workflow)
        self.assertIn("workflow_run:",workflow)
        self.assertIn('workflows: ["agent-heartbeat-sweep"]',workflow)
        self.assertIn('operations/TRIGGER_WORKFLOW_LIVENESS',workflow)


    def test_paid_wrapper_jobs_have_timeouts_without_daily_job_quotas(self):
        p = policy()
        keys = [
            "runtime-worker::runtime-observe",
            "runtime-worker::runtime-sync",
            "runtime-worker::runtime-daily",
            "runtime-worker::runtime-weekly",
            "model-value-proof::proof",
        ]
        for key in keys:
            cfg = p["workflow_job_ceilings"][key]
            self.assertGreater(cfg["max_minutes_per_job"], 0)
            self.assertEqual(cfg["daily_ceiling"]["github_job_starts"], 0)
            self.assertEqual(cfg["daily_ceiling"]["github_runner_minutes"], 0)
        self.assertEqual(p["portfolio_ceiling"]["github_job_starts"], 0)
        self.assertEqual(p["portfolio_ceiling"]["github_runner_minutes"], 0)


    def test_github_job_counts_do_not_block_paid_workflow_wrappers(self):
        p = copy.deepcopy(policy())
        state = load_state()
        for idx in range(3):
            state, decision = preflight(
                state,
                github_request(run_id=f"sync-{idx}", workflow="runtime-worker", job="runtime-sync"),
                at=AT,
                policy_data=p,
            )
            self.assertEqual(decision["status"], "RESERVED")
            self.assertTrue(decision["can_execute"])

    def test_event_observe_ignores_dashboard_test_operator_and_one_shot_trigger_churn(self):
        workflow=(ROOT/".github/workflows/runtime-event-observe.yml").read_text()
        self.assertIn("group: runtime-event-observe-${{ github.event_name }}-${{ github.ref }}",workflow)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'push' }}",workflow)
        for path in [
            '"dashboard/**"','"tests/**"','"operator_console/**"','"cost_governor/**"',
            '".github/workflows/command-center-pages.yml"',
            '"value_proof/TRIGGER_END_TO_END_PROOF"',
            '"value_proof/TRIGGER_VERIFIED_FEEDBACK_BOOTSTRAP"',
            '"learning/TRIGGER_VERIFIED_OUTCOME_BOOTSTRAP"',
            '".github/workflows/model-value-proof.yml"',
            '".github/workflows/verified-feedback-bootstrap.yml"',
            '".github/workflows/continuous-learning-bootstrap.yml"',
            '"operations/TRIGGER_WORKFLOW_LIVENESS"',
            '".github/workflows/portfolio-cost-watchdog.yml"',
        ]:
            self.assertIn(path,workflow)


    def test_nonpaid_workflows_use_independent_workload_controls(self):
        expected = {
            "agent-heartbeat-sweep.yml": ("agent-heartbeat-sweep", "heartbeat", "portfolio-heartbeat", 2),
            "command-center-pages.yml": ("command-center-pages", "publish", "portfolio-reporting-pages", 5),
            "continuous-learning-bootstrap.yml": ("continuous-learning-bootstrap", "bootstrap", "portfolio-learning-bootstrap", 2),
            "hunter-autonomous-cycle.yml": ("hunter-autonomous-cycle", "hunt", "portfolio-hunter-cycle", 5),
            "portfolio-autonomous-scheduler.yml": ("portfolio-autonomous-scheduler", "schedule", "portfolio-scheduler", 5),
            "portfolio-notification-cycle.yml": ("portfolio-notification-cycle", "notify", "portfolio-notification", 2),
            "software-factory-candidate.yml": ("software-factory-candidate", "execute-candidate-action", "portfolio-software-factory", 5),
            "verified-feedback-bootstrap.yml": ("verified-feedback-bootstrap", "feedback", "portfolio-feedback-bootstrap", 2),
        }
        wp = workload_policy()
        for filename, values in expected.items():
            workflow_id, job_id, group, minutes = values
            with self.subTest(workflow=filename):
                workflow = (ROOT / ".github/workflows" / filename).read_text()
                self.assertIn(f"group: {group}", workflow)
                self.assertIn("cancel-in-progress: false", workflow)
                self.assertIn("workload_control.workload_gate preflight", workflow)
                self.assertNotIn("portfolio-cost-governed-autonomy", workflow)
                self.assertNotIn("cost_governor.workflow_gate", workflow)
                decision = evaluate_workload(
                    workflow_id=workflow_id,
                    job_id=job_id,
                    estimated_minutes=minutes,
                )
                self.assertEqual(decision["status"], "WORKLOAD_ALLOWED")
                self.assertEqual(decision["concurrency_group"], group)
                self.assertEqual(
                    wp["services"][f"{workflow_id}::{job_id}"]["max_minutes_per_job"],
                    minutes,
                )


    def test_model_value_proof_remains_paid_cost_governed_and_bounded(self):
        workflow=(ROOT/".github/workflows/model-value-proof.yml").read_text()
        self.assertIn("portfolio-cost-governed-autonomy",workflow)
        self.assertIn("cost_governor.workflow_gate preflight",workflow)
        self.assertIn("cost_governor.workflow_gate finalize",workflow)
        self.assertIn("PORTFOLIO_MODEL_API_KEY",workflow)
        self.assertIn("value_proof.end_to_end",workflow)
        self.assertNotIn("\n  schedule:",workflow)
        p=policy()
        self.assertIn("model-value-proof",p["managed_workflow_names"])
        cfg=p["workflow_job_ceilings"]["model-value-proof::proof"]
        self.assertEqual(cfg["max_minutes_per_job"],5)
        self.assertEqual(cfg["daily_ceiling"]["github_job_starts"],0)
        self.assertEqual(cfg["daily_ceiling"]["github_runner_minutes"],0)


    def test_verified_feedback_bootstrap_is_workload_controlled_and_model_free(self):
        workflow=(ROOT/".github/workflows/verified-feedback-bootstrap.yml").read_text()
        self.assertIn("group: portfolio-feedback-bootstrap",workflow)
        self.assertIn("workload_control.workload_gate preflight",workflow)
        self.assertNotIn("cost_governor.workflow_gate",workflow)
        self.assertIn("value_proof.proof_artifact_state",workflow)
        self.assertIn("value_proof.feedback_loop",workflow)
        self.assertNotIn("PORTFOLIO_MODEL_API_KEY",workflow)
        self.assertNotIn("value_proof.model_task",workflow)
        self.assertNotIn("value_proof.verifier",workflow)
        self.assertNotIn("\n  schedule:",workflow)


    def test_continuous_learning_bootstrap_is_workload_controlled_and_model_free(self):
        workflow=(ROOT/".github/workflows/continuous-learning-bootstrap.yml").read_text()
        self.assertIn("group: portfolio-learning-bootstrap",workflow)
        self.assertIn("workload_control.workload_gate preflight",workflow)
        self.assertNotIn("cost_governor.workflow_gate",workflow)
        self.assertIn("value_proof.proof_artifact_state",workflow)
        self.assertIn("learning.live_observations",workflow)
        self.assertIn("learning.integrity",workflow)
        self.assertNotIn("PORTFOLIO_MODEL_API_KEY",workflow)
        self.assertNotIn("python -m value_proof.model_task",workflow)
        self.assertNotIn("python -m value_proof.verifier",workflow)
        self.assertNotIn("\n  schedule:",workflow)


    def test_command_center_hourly_refresh_is_independent_from_paid_spend(self):
        workflow = (ROOT / ".github/workflows/command-center-pages.yml").read_text()
        self.assertIn('cron: "37 * * * *"',workflow)
        self.assertIn("workflow_dispatch:",workflow)
        self.assertNotIn("\n  push:",workflow)
        self.assertIn("group: portfolio-reporting-pages",workflow)
        self.assertIn("workload_control.workload_gate preflight",workflow)
        self.assertNotIn("cost_governor.workflow_gate",workflow)
        self.assertNotIn("PORTFOLIO_SPEND_DISABLED",workflow)
        self.assertIn("actions: read",workflow)
        self.assertNotIn("contents: write",workflow)

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
        validate_decision_record(state["recent_decisions"][0])

    def test_successful_github_job_commits_measured_not_reserved_minutes(self):
        state, decision = preflight(load_state(), github_request(minutes=5), at=AT)
        row = next(r for r in state["reservations"] if r["reservation_id"] == decision["reservation_id"])
        actual = measured_github_usage(row, at="2026-09-25T12:01:01Z")
        self.assertEqual(actual["github_job_starts"],1)
        self.assertEqual(actual["github_runner_minutes"],2)
        state, commit = commit_reservation(state,decision["reservation_id"],actual,at="2026-09-25T12:01:01Z")
        self.assertEqual(commit["status"],"COMMITTED")
        self.assertEqual(state["reservations"][0]["actual_usage"]["github_runner_minutes"],2)

    def test_subminute_github_job_is_charged_one_runner_minute(self):
        state, decision = preflight(load_state(),github_request(minutes=5),at=AT)
        row = next(r for r in state["reservations"] if r["reservation_id"] == decision["reservation_id"])
        actual = measured_github_usage(row,at="2026-09-25T12:00:01Z")
        self.assertEqual(actual["github_runner_minutes"],1)

    def test_github_usage_timestamp_rollback_fails_closed(self):
        state, decision = preflight(load_state(),github_request(minutes=5),at=AT)
        row = next(r for r in state["reservations"] if r["reservation_id"] == decision["reservation_id"])
        with self.assertRaisesRegex(CostGovernorError,"finish before reservation"):
            measured_github_usage(row,at="2026-09-25T11:59:59Z")

    def test_cost_decision_history_rejects_hash_tampering(self):
        state, _ = preflight(load_state(), github_request(), at=AT)
        poisoned = copy.deepcopy(state)
        poisoned["recent_decisions"][0]["reason_codes"] = ["FORGED_ALLOW"]
        with self.assertRaisesRegex(CostGovernorError, "cost decision hash mismatch"):
            validate_state(poisoned)

    def test_cost_decision_history_cannot_grant_authority(self):
        state, _ = preflight(load_state(), github_request(), at=AT)
        poisoned = copy.deepcopy(state)
        poisoned["recent_decisions"][0]["authority_granted"] = True
        with self.assertRaisesRegex(CostGovernorError, "may not grant authority"):
            validate_state(poisoned)

    def test_exact_duplicate_decision_record_is_not_appended_twice(self):
        request = github_request()
        state, _ = preflight(load_state(), request, at=AT)
        state, _ = preflight(state, request, at=AT)
        state, _ = preflight(state, request, at=AT)
        self.assertEqual(len(state["recent_decisions"]), 2)

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

    def test_cancelled_before_preflight_rerun_starts_at_governed_attempt_one(self):
        state=load_state()
        self.assertEqual(
            governed_github_attempt(state,run_id="cancelled-run",job_id="feedback",observed_attempt=2),
            1,
        )

    def test_skipped_github_attempt_numbers_advance_only_one_governed_retry(self):
        state=load_state()
        first_req=github_request(run_id="retry-run",attempt=1)
        state,first=preflight(state,first_req,at=AT)
        self.assertEqual(first["status"],"RESERVED")
        self.assertEqual(
            governed_github_attempt(state,run_id="retry-run",job_id="schedule",observed_attempt=3),
            2,
        )

    def test_same_github_attempt_remains_idempotent_after_reservation(self):
        state=load_state()
        req=github_request(run_id="same-run",attempt=1)
        state,first=preflight(state,req,at=AT)
        self.assertEqual(first["status"],"RESERVED")
        self.assertEqual(
            governed_github_attempt(state,run_id="same-run",job_id="schedule",observed_attempt=1),
            1,
        )
        state,second=preflight(state,req,at=AT)
        self.assertEqual(second["status"],"DUPLICATE_SUPPRESSED")

    def test_governed_retry_still_cannot_exceed_retry_limit(self):
        state=load_state()
        first=github_request(run_id="limit-run",attempt=1)
        state,d1=preflight(state,first,at=AT)
        self.assertEqual(d1["status"],"RESERVED")
        second=github_request(run_id="limit-run",attempt=2)
        state,d2=preflight(state,second,at=AT)
        self.assertEqual(d2["status"],"RESERVED")
        governed=governed_github_attempt(state,run_id="limit-run",job_id="schedule",observed_attempt=7)
        self.assertEqual(governed,3)
        third=github_request(run_id="limit-run",attempt=governed)
        _,d3=preflight(state,third,at=AT)
        self.assertEqual(d3["status"],"BLOCKED_RETRY_LIMIT")
        self.assertIn("RETRY_LIMIT_EXCEEDED",d3["reason_codes"])

    def test_retry_sequence_cannot_start_at_three(self):
        _, decision = preflight(load_state(), github_request(attempt=3), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_RETRY_LIMIT")
        self.assertIn("RETRY_LIMIT_EXCEEDED", decision["reason_codes"])

    def test_act_can_never_be_authorized_by_cost_budget(self):
        _, decision = preflight(load_state(), github_request(authority="ACT"), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_AUTHORITY")
        self.assertFalse(decision["authority_granted"])


    def test_environment_spend_kill_switch_blocks_paid_work_but_not_github_wrapper(self):
        route = {
            "status": "ROUTED",
            "tier": 2,
            "route_id": "MRT-KILL",
            "provider_id": "openai",
            "model_id": "gpt-5.6-luna",
            "max_estimated_cost_usd": 0.01,
            "route_hash": "sha256:kill",
        }
        request = {
            "request_id": "MRQ-KILL",
            "project_ids": ["PRJ-000"],
            "max_input_tokens": 100,
            "max_output_tokens": 100,
            "authority_class": "OBSERVE",
            "data_classification": "SANITIZED",
        }
        with patch.dict(os.environ, {"PORTFOLIO_SPEND_DISABLED": "true"}):
            _, paid = reserve_model_execution(load_state(), route, request, at=AT)
            _, wrapper = preflight(load_state(), github_request(), at=AT)
        self.assertEqual(paid["status"], "BLOCKED_KILL_SWITCH")
        self.assertEqual(wrapper["status"], "RESERVED")

    def test_unconfigured_workflow_job_fails_closed(self):
        _, decision = preflight(load_state(), github_request(workflow="unknown-workflow"), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any(x.startswith("UNCONFIGURED_WORKFLOW_JOB:") for x in decision["reason_codes"]))

    def test_per_job_minute_ceiling_is_enforced(self):
        _, decision = preflight(load_state(), github_request(minutes=6), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_BUDGET")
        self.assertTrue(any(x.startswith("JOB_MINUTE_CEILING_EXCEEDED:") for x in decision["reason_codes"]))


    def test_github_job_ignores_portfolio_daily_job_counters(self):
        p = copy.deepcopy(policy())
        p["portfolio_ceiling"]["github_job_starts"] = 0
        p["portfolio_ceiling"]["github_runner_minutes"] = 0
        _, decision = preflight(load_state(), github_request(), at=AT, policy_data=p)
        self.assertEqual(decision["status"], "RESERVED")


    def test_github_job_ignores_project_daily_job_counters(self):
        p = copy.deepcopy(policy())
        p["project_overrides"]["PRJ-000"]["github_job_starts"] = 0
        p["project_overrides"]["PRJ-000"]["github_runner_minutes"] = 0
        _, decision = preflight(load_state(), github_request(), at=AT, policy_data=p)
        self.assertEqual(decision["status"], "RESERVED")


    def test_github_job_ignores_legacy_workflow_daily_job_counters(self):
        p = copy.deepcopy(policy())
        cfg = p["workflow_job_ceilings"]["runtime-worker::runtime-sync"]["daily_ceiling"]
        cfg["github_job_starts"] = 0
        cfg["github_runner_minutes"] = 0
        _, decision = preflight(load_state(), github_request(), at=AT, policy_data=p)
        self.assertEqual(decision["status"], "RESERVED")


    def test_expired_github_wrapper_does_not_consume_a_daily_job_quota(self):
        p = copy.deepcopy(policy())
        first_at = "2026-09-25T00:00:00Z"
        state, first = preflight(load_state(), github_request(run_id="1", at=first_at), at=first_at, policy_data=p)
        self.assertEqual(first["status"], "RESERVED")
        later = "2026-09-25T07:00:00Z"
        state, second = preflight(state, github_request(run_id="2", at=later), at=later, policy_data=p)
        self.assertEqual(second["status"], "RESERVED")
        self.assertEqual(state["reservations"][0]["status"], "EXPIRED")

    def test_cancelled_reservation_releases_compute_capacity(self):
        p = copy.deepcopy(policy())
        for ceiling in (
            p["portfolio_ceiling"],
            p["project_overrides"]["PRJ-000"],
            p["workflow_job_ceilings"]["runtime-worker::runtime-sync"]["daily_ceiling"],
        ):
            ceiling["github_job_starts"] = 1
            ceiling["github_runner_minutes"] = 5
        state, first = preflight(load_state(), github_request(run_id="1"), at=AT, policy_data=p)
        state = cancel_reservation(state, first["reservation_id"], at=AT, policy_data=p)
        state, second = preflight(state, github_request(run_id="2"), at=AT, policy_data=p)
        self.assertEqual(second["status"], "RESERVED")


    def test_paid_usage_overage_trips_hard_stop_and_blocks_next_paid_preflight(self):
        route = {
            "status": "ROUTED",
            "tier": 2,
            "route_id": "MRT-OVERAGE-1",
            "provider_id": "openai",
            "model_id": "gpt-5.6-luna",
            "max_estimated_cost_usd": 0.01,
            "route_hash": "sha256:overage1",
        }
        request = {
            "request_id": "MRQ-OVERAGE-1",
            "project_ids": ["PRJ-000"],
            "max_input_tokens": 100,
            "max_output_tokens": 100,
            "authority_class": "OBSERVE",
            "data_classification": "SANITIZED",
        }
        state, decision = reserve_model_execution(load_state(), route, request, at=AT)
        actual = zero_usage()
        actual.update({
            "cost_usd": 0.02,
            "input_tokens": 100,
            "output_tokens": 100,
            "model_calls": 1,
            "api_calls": 1,
        })
        state, commit = commit_reservation(state, decision["reservation_id"], actual, at=AT)
        self.assertEqual(commit["status"], "HARD_STOP_OVERAGE")
        self.assertEqual(hard_stop_reason(state, at=AT), "CURRENT_DAY_PAID_RESERVATION_OVERAGE")

        next_route = dict(route, route_id="MRT-OVERAGE-2", route_hash="sha256:overage2")
        next_request = dict(request, request_id="MRQ-OVERAGE-2")
        state, blocked = reserve_model_execution(state, next_route, next_request, at=AT)
        self.assertEqual(blocked["status"], "BLOCKED_BUDGET")
        self.assertFalse(blocked["can_execute"])
        self.assertTrue(any(x.startswith("HARD_STOP_ACTIVE:") for x in blocked["reason_codes"]))

        _, wrapper = preflight(state, github_request(run_id="after-overage"), at=AT)
        self.assertEqual(wrapper["status"], "RESERVED")

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
