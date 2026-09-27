import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from model_router.model_router import prepare_governed_execution
from cost_governor.cancel_managed_jobs import managed_run_ids
from cost_governor.workflow_gate import governed_github_attempt, measured_github_usage
from cost_governor.cost_governor import (
    CostGovernorError,
    cancel_reservation,
    commit_reservation,
    hard_stop_reason,
    load_state,
    make_github_job_request,
    make_model_request,
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


def model_request(*, route_id="MRT-TEST", request_id="MRQ-TEST", attempt=1, cost=0.01, at=AT):
    route = {
        "status": "ROUTED",
        "tier": 2,
        "route_id": route_id,
        "provider_id": "approved-api-slot",
        "model_id": "UNCONFIGURED_STRONG",
        "max_estimated_cost_usd": cost,
        "route_hash": f"sha256:{route_id.lower()}",
    }
    request = {
        "request_id": request_id,
        "project_ids": ["PRJ-000"],
        "max_input_tokens": 100,
        "max_output_tokens": 100,
        "authority_class": "OBSERVE",
        "data_classification": "SANITIZED",
    }
    return make_model_request(route, request, attempt=attempt, at=at)


class CostGovernorTests(unittest.TestCase):

    def test_only_paid_ledger_workflows_finalize_cost_state(self):
        paid_ledger_workflows=["model-value-proof.yml","runtime-worker.yml"]
        workload_only_workflows=[
            "agent-heartbeat-sweep.yml",
            "command-center-pages.yml",
            "continuous-learning-bootstrap.yml",
            "hunter-autonomous-cycle.yml",
            "portfolio-autonomous-scheduler.yml",
            "portfolio-notification-cycle.yml",
            "software-factory-candidate.yml",
            "verified-feedback-bootstrap.yml",
        ]
        for filename in paid_ledger_workflows:
            workflow=(ROOT/".github/workflows"/filename).read_text()
            self.assertIn("python -m cost_governor.artifact_state",workflow)
            self.assertIn("python -m cost_governor.workflow_gate finalize",workflow)
            self.assertIn("name: portfolio-cost-governor-state",workflow)
        for filename in workload_only_workflows:
            workflow=(ROOT/".github/workflows"/filename).read_text()
            self.assertNotIn("python -m cost_governor.artifact_state",workflow)
            self.assertNotIn("python -m cost_governor.workflow_gate finalize",workflow)
            self.assertNotIn("name: portfolio-cost-governor-state",workflow)
            self.assertIn("--state cost_governor/COST_STATE_SEED.json",workflow)
    def test_watchdog_polling_is_hourly_not_quarter_hourly(self):
        workflow = (ROOT / ".github/workflows/portfolio-cost-watchdog.yml").read_text()
        self.assertIn('cron: "53 * * * *"',workflow)
        self.assertNotIn('cron: "*/15 * * * *"',workflow)
        self.assertIn("actions: write",workflow)
        self.assertIn("workflow_run:",workflow)
        self.assertIn('workflows: ["agent-heartbeat-sweep"]',workflow)
        self.assertIn('operations/TRIGGER_WORKFLOW_LIVENESS',workflow)

    def test_runtime_subbudgets_isolate_push_observation_from_scheduled_reasoning(self):
        p=policy()
        keys={
          "observe":"runtime-worker::runtime-observe",
          "sync":"runtime-worker::runtime-sync",
          "daily":"runtime-worker::runtime-daily",
          "weekly":"runtime-worker::runtime-weekly",
        }
        cfg={mode:p["workflow_job_ceilings"][key]["daily_ceiling"] for mode,key in keys.items()}
        self.assertEqual(sum(row["github_job_starts"] for row in cfg.values()),60)
        self.assertLessEqual(
            sum(row["github_job_starts"] for row in cfg.values()),
            p["portfolio_ceiling"]["github_job_starts"]//2,
        )
        self.assertGreaterEqual(cfg["sync"]["github_job_starts"],26)
        self.assertGreaterEqual(cfg["daily"]["github_job_starts"],2)
        self.assertGreaterEqual(cfg["weekly"]["github_job_starts"],2)
        self.assertLess(cfg["observe"]["github_job_starts"],sum(row["github_job_starts"] for row in cfg.values()))
        workflow=(ROOT/".github/workflows/runtime-worker.yml").read_text()
        self.assertIn('--job-id "runtime-${RUNTIME_MODE}"',workflow)


    def test_daily_github_job_counts_are_non_enforcing_workload_telemetry(self):
        p=copy.deepcopy(policy())
        observe=p["workflow_job_ceilings"]["runtime-worker::runtime-observe"]["daily_ceiling"]
        sync=p["workflow_job_ceilings"]["runtime-worker::runtime-sync"]["daily_ceiling"]
        observe["github_job_starts"]=0;observe["github_runner_minutes"]=0
        sync["github_job_starts"]=0;sync["github_runner_minutes"]=0
        state=load_state()
        state,d1=preflight(
            state,
            github_request(run_id="observe-1",workflow="runtime-worker",job="runtime-observe"),
            at=AT,policy_data=p,
        )
        state,d2=preflight(
            state,
            github_request(run_id="observe-2",workflow="runtime-worker",job="runtime-observe"),
            at=AT,policy_data=p,
        )
        state,d3=preflight(
            state,
            github_request(run_id="sync-1",workflow="runtime-worker",job="runtime-sync"),
            at=AT,policy_data=p,
        )
        self.assertEqual([d1["status"],d2["status"],d3["status"]],["WORKLOAD_ADMITTED"]*3)
        self.assertEqual(state["reservations"],[])
        self.assertFalse(p["github_workload_control"]["daily_job_count_quotas_enforced"])
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


    def test_agent_heartbeat_sweep_is_workload_controlled_and_bounded(self):
        workflow=(ROOT/".github/workflows/agent-heartbeat-sweep.yml").read_text()
        self.assertIn('cron: "29 */2 * * *"',workflow)
        self.assertIn("group: portfolio-agent-heartbeat",workflow)
        self.assertNotIn("group: portfolio-cost-governed-autonomy",workflow)
        self.assertIn("cost_governor.workflow_gate preflight",workflow)
        p=policy()
        self.assertIn("agent-heartbeat-sweep",p["managed_workflow_names"])
        cfg=p["workflow_job_ceilings"]["agent-heartbeat-sweep::heartbeat"]
        self.assertEqual(cfg["max_minutes_per_job"],2)
        self.assertFalse(p["github_workload_control"]["daily_job_count_quotas_enforced"])
    def test_model_value_proof_is_one_shot_cost_governed_and_bounded(self):
        workflow=(ROOT/".github/workflows/model-value-proof.yml").read_text()
        self.assertIn("portfolio-cost-governed-autonomy",workflow)
        self.assertIn("cost_governor.workflow_gate preflight",workflow)
        self.assertIn("cost_governor.workflow_gate finalize",workflow)
        self.assertIn("PORTFOLIO_MODEL_API_KEY",workflow)
        self.assertIn("value_proof.end_to_end",workflow)
        self.assertNotIn("\\${{",workflow)
        self.assertNotIn("\n  schedule:",workflow)
        p=policy()
        self.assertIn("model-value-proof",p["managed_workflow_names"])
        cfg=p["workflow_job_ceilings"]["model-value-proof::proof"]
        self.assertEqual(cfg["max_minutes_per_job"],5)
        self.assertEqual(cfg["daily_ceiling"]["github_job_starts"],1)
        self.assertEqual(cfg["daily_ceiling"]["github_runner_minutes"],5)
        self.assertEqual(cfg["daily_ceiling"]["cost_usd"],0)
        self.assertEqual(cfg["daily_ceiling"]["model_calls"],0)
        self.assertEqual(cfg["daily_ceiling"]["api_calls"],0)


    def test_verified_feedback_bootstrap_is_one_shot_bounded_and_model_free(self):
        workflow=(ROOT/".github/workflows/verified-feedback-bootstrap.yml").read_text()
        self.assertIn("portfolio-cost-governed-autonomy",workflow)
        self.assertIn("cost_governor.workflow_gate preflight",workflow)
        self.assertNotIn("cost_governor.workflow_gate finalize",workflow)
        self.assertIn("--state cost_governor/COST_STATE_SEED.json",workflow)
        self.assertIn("value_proof.proof_artifact_state",workflow)
        self.assertIn("value_proof.feedback_loop",workflow)
        self.assertNotIn("PORTFOLIO_MODEL_API_KEY",workflow)
        self.assertNotIn("value_proof.model_task",workflow)
        self.assertNotIn("value_proof.verifier",workflow)
        self.assertNotIn("\n  schedule:",workflow)
        p=policy()
        self.assertIn("verified-feedback-bootstrap",p["managed_workflow_names"])
        self.assertEqual(p["workflow_job_ceilings"]["verified-feedback-bootstrap::feedback"]["max_minutes_per_job"],2)

    def test_continuous_learning_bootstrap_is_bounded_and_model_free(self):
        workflow=(ROOT/".github/workflows/continuous-learning-bootstrap.yml").read_text()
        self.assertIn("portfolio-cost-governed-autonomy",workflow)
        self.assertIn("cost_governor.workflow_gate preflight",workflow)
        self.assertNotIn("cost_governor.workflow_gate finalize",workflow)
        self.assertIn("--state cost_governor/COST_STATE_SEED.json",workflow)
        self.assertIn("value_proof.proof_artifact_state",workflow)
        self.assertIn("learning.live_observations",workflow)
        self.assertIn("learning.integrity",workflow)
        self.assertNotIn("PORTFOLIO_MODEL_API_KEY",workflow)
        self.assertNotIn("python -m value_proof.model_task",workflow)
        self.assertNotIn("python -m value_proof.verifier",workflow)
        self.assertNotIn("\n  schedule:",workflow)
        p=policy()
        self.assertIn("continuous-learning-bootstrap",p["managed_workflow_names"])
        self.assertEqual(p["workflow_job_ceilings"]["continuous-learning-bootstrap::bootstrap"]["max_minutes_per_job"],2)
    def test_command_center_hourly_refresh_has_independent_workload_lane(self):
        workflow = (ROOT / ".github/workflows/command-center-pages.yml").read_text()
        self.assertIn('cron: "37 * * * *"',workflow)
        self.assertIn("workflow_dispatch:",workflow)
        self.assertNotIn("\n  push:",workflow)
        self.assertIn("group: portfolio-command-center-publish",workflow)
        self.assertNotIn("group: portfolio-cost-governed-autonomy",workflow)
        self.assertIn("cost_governor.workflow_gate preflight",workflow)
        self.assertIn("actions: read",workflow)
        self.assertNotIn("contents: write",workflow)
        p=policy()
        self.assertIn("command-center-pages",p["managed_workflow_names"])
        self.assertIn("command-center-pages::publish",p["workflow_job_ceilings"])
        self.assertFalse(p["github_workload_control"]["durable_cost_reservations"])
    def test_checked_in_paid_budget_is_finite_and_nonzero(self):
        p = policy()
        self.assertGreater(p["portfolio_ceiling"]["cost_usd"], 0)
        self.assertGreater(p["portfolio_ceiling"]["model_calls"], 0)
        self.assertGreater(p["portfolio_ceiling"]["api_calls"], 0)
        for field in ("cost_usd", "input_tokens", "output_tokens", "model_calls", "api_calls"):
            self.assertGreaterEqual(p["portfolio_ceiling"][field], 0)


    def test_managed_github_job_is_admitted_without_paid_reservation(self):
        state = load_state()
        sequence = state["sequence"]
        out, decision = preflight(state, github_request(), at=AT)
        self.assertEqual(decision["status"], "WORKLOAD_ADMITTED")
        self.assertTrue(decision["can_execute"])
        self.assertFalse(decision["authority_granted"])
        self.assertIsNone(decision["reservation_id"])
        self.assertEqual(out["reservations"], [])
        self.assertEqual(out["sequence"], sequence)

    def test_workload_admission_does_not_consume_financial_ledger(self):
        state=load_state()
        out,decision=preflight(state,github_request(minutes=5),at=AT)
        self.assertEqual(decision["status"],"WORKLOAD_ADMITTED")
        self.assertEqual(out,state)
        self.assertEqual(out["reservations"],[])

    def test_workload_admission_does_not_charge_runner_minutes(self):
        state=load_state()
        out,decision=preflight(state,github_request(minutes=1),at=AT)
        self.assertEqual(decision["status"],"WORKLOAD_ADMITTED")
        self.assertEqual(out["sequence"],state["sequence"])
        self.assertEqual(out["reservations"],[])

    def test_workload_admission_preserves_per_job_timeout(self):
        _,decision=preflight(load_state(),github_request(minutes=6),at=AT)
        self.assertEqual(decision["status"],"BLOCKED_WORKLOAD")
        self.assertIn("JOB_MINUTE_CEILING_EXCEEDED:portfolio-autonomous-scheduler::schedule",decision["reason_codes"])

    def test_cost_decision_history_rejects_hash_tampering(self):
        state,_=preflight(load_state(),model_request(),at=AT)
        poisoned=copy.deepcopy(state)
        poisoned["recent_decisions"][0]["reason_codes"]=["FORGED_ALLOW"]
        with self.assertRaisesRegex(CostGovernorError,"cost decision hash mismatch"):
            validate_state(poisoned)

    def test_cost_decision_history_cannot_grant_authority(self):
        state,_=preflight(load_state(),model_request(),at=AT)
        poisoned=copy.deepcopy(state)
        poisoned["recent_decisions"][0]["authority_granted"]=True
        with self.assertRaisesRegex(CostGovernorError,"may not grant authority"):
            validate_state(poisoned)

    def test_exact_duplicate_decision_record_is_not_appended_twice(self):
        request=model_request()
        state,_=preflight(load_state(),request,at=AT)
        state,_=preflight(state,request,at=AT)
        state,_=preflight(state,request,at=AT)
        self.assertEqual(len(state["recent_decisions"]),2)

    def test_exact_duplicate_is_suppressed(self):
        request=model_request()
        state,first=preflight(load_state(),request,at=AT)
        state,second=preflight(state,request,at=AT)
        self.assertEqual(first["status"],"RESERVED")
        self.assertEqual(second["status"],"DUPLICATE_SUPPRESSED")
        self.assertFalse(second["can_execute"])
        self.assertEqual(len(state["reservations"]),1)

    def test_idempotency_collision_fails_closed(self):
        request=model_request()
        state,_=preflight(load_state(),request,at=AT)
        changed=copy.deepcopy(request)
        changed["evidence_refs"]=[*changed["evidence_refs"],"changed:evidence"]
        state,decision=preflight(state,changed,at=AT)
        self.assertEqual(decision["status"],"BLOCKED_IDEMPOTENCY_COLLISION")
        self.assertFalse(decision["can_execute"])

    def test_workload_rerun_uses_observed_attempt_without_paid_reservation(self):
        state=load_state()
        self.assertEqual(
            governed_github_attempt(state,run_id="cancelled-run",job_id="feedback",observed_attempt=2),
            2,
        )

    def test_workload_attempt_uses_native_github_attempt_when_no_legacy_reservation(self):
        state=load_state()
        self.assertEqual(
            governed_github_attempt(state,run_id="retry-run",job_id="schedule",observed_attempt=3),
            3,
        )

    def test_same_workload_attempt_is_state_neutral(self):
        state=load_state()
        req=github_request(run_id="same-run",attempt=1)
        state,first=preflight(state,req,at=AT)
        state,second=preflight(state,req,at=AT)
        self.assertEqual(first["status"],"WORKLOAD_ADMITTED")
        self.assertEqual(second["status"],"WORKLOAD_ADMITTED")
        self.assertEqual(state["reservations"],[])

    def test_workload_retry_cannot_exceed_retry_limit(self):
        _,decision=preflight(load_state(),github_request(run_id="limit-run",attempt=3),at=AT)
        self.assertEqual(decision["status"],"BLOCKED_RETRY_LIMIT")
        self.assertIn("RETRY_LIMIT_EXCEEDED",decision["reason_codes"])
    def test_retry_sequence_cannot_start_at_three(self):
        _, decision = preflight(load_state(), github_request(attempt=3), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_RETRY_LIMIT")
        self.assertIn("RETRY_LIMIT_EXCEEDED", decision["reason_codes"])

    def test_act_can_never_be_authorized_by_cost_budget(self):
        _, decision = preflight(load_state(), github_request(authority="ACT"), at=AT)
        self.assertEqual(decision["status"], "BLOCKED_AUTHORITY")
        self.assertFalse(decision["authority_granted"])


    def test_environment_spend_kill_switch_blocks_paid_work_not_github_workload(self):
        with patch.dict(os.environ,{"PORTFOLIO_SPEND_DISABLED":"true"}):
            _,paid=preflight(load_state(),model_request(),at=AT)
            _,workload=preflight(load_state(),github_request(),at=AT)
        self.assertEqual(paid["status"],"BLOCKED_KILL_SWITCH")
        self.assertEqual(workload["status"],"WORKLOAD_ADMITTED")

    def test_unconfigured_workflow_job_fails_closed(self):
        _,decision=preflight(load_state(),github_request(workflow="unknown-workflow"),at=AT)
        self.assertEqual(decision["status"],"BLOCKED_WORKLOAD")
        self.assertTrue(any(x.startswith("UNCONFIGURED_WORKFLOW_JOB:") for x in decision["reason_codes"]))

    def test_per_job_minute_ceiling_is_enforced(self):
        _,decision=preflight(load_state(),github_request(minutes=6),at=AT)
        self.assertEqual(decision["status"],"BLOCKED_WORKLOAD")
        self.assertTrue(any(x.startswith("JOB_MINUTE_CEILING_EXCEEDED:") for x in decision["reason_codes"]))

    def test_github_workload_ignores_portfolio_job_count_budget(self):
        p=copy.deepcopy(policy())
        p["portfolio_ceiling"]["github_job_starts"]=0
        p["portfolio_ceiling"]["github_runner_minutes"]=0
        _,decision=preflight(load_state(),github_request(),at=AT,policy_data=p)
        self.assertEqual(decision["status"],"WORKLOAD_ADMITTED")

    def test_github_workload_ignores_project_job_count_budget(self):
        p=copy.deepcopy(policy())
        p["project_overrides"]["PRJ-000"]["github_job_starts"]=0
        p["project_overrides"]["PRJ-000"]["github_runner_minutes"]=0
        _,decision=preflight(load_state(),github_request(),at=AT,policy_data=p)
        self.assertEqual(decision["status"],"WORKLOAD_ADMITTED")

    def test_github_workload_ignores_legacy_daily_job_count_ceiling(self):
        p=copy.deepcopy(policy())
        cfg=p["workflow_job_ceilings"]["portfolio-autonomous-scheduler::schedule"]["daily_ceiling"]
        cfg["github_job_starts"]=0
        cfg["github_runner_minutes"]=0
        _,decision=preflight(load_state(),github_request(),at=AT,policy_data=p)
        self.assertEqual(decision["status"],"WORKLOAD_ADMITTED")

    def test_repeated_workload_admission_does_not_accumulate_paid_state(self):
        state=load_state()
        for run_id in ("1","2","3"):
            state,decision=preflight(state,github_request(run_id=run_id),at=AT)
            self.assertEqual(decision["status"],"WORKLOAD_ADMITTED")
        self.assertEqual(state["reservations"],[])
        self.assertEqual(state["sequence"],0)

    def test_daily_job_counts_do_not_create_workload_capacity_exhaustion(self):
        p=copy.deepcopy(policy())
        cfg=p["workflow_job_ceilings"]["portfolio-autonomous-scheduler::schedule"]["daily_ceiling"]
        cfg["github_job_starts"]=0
        cfg["github_runner_minutes"]=0
        state,first=preflight(load_state(),github_request(run_id="1"),at=AT,policy_data=p)
        state,second=preflight(state,github_request(run_id="2"),at=AT,policy_data=p)
        self.assertEqual(first["status"],"WORKLOAD_ADMITTED")
        self.assertEqual(second["status"],"WORKLOAD_ADMITTED")

    def test_paid_usage_overage_trips_and_enforces_hard_stop(self):
        state,decision=preflight(load_state(),model_request(route_id="MRT-OVERAGE",request_id="MRQ-OVERAGE"),at=AT)
        self.assertEqual(decision["status"],"RESERVED")
        actual=zero_usage()
        actual.update({
            "cost_usd":0.02,
            "input_tokens":50,
            "output_tokens":50,
            "model_calls":1,
            "api_calls":1,
        })
        state,commit=commit_reservation(state,decision["reservation_id"],actual,at=AT)
        self.assertEqual(commit["status"],"HARD_STOP_OVERAGE")
        self.assertEqual(hard_stop_reason(state,at=AT),"CURRENT_DAY_PAID_RESERVATION_OVERAGE")
        _,blocked=preflight(
            state,
            model_request(route_id="MRT-AFTER-OVERAGE",request_id="MRQ-AFTER-OVERAGE"),
            at=AT,
        )
        self.assertEqual(blocked["status"],"BLOCKED_HARD_STOP")
        self.assertIn("CURRENT_DAY_PAID_RESERVATION_OVERAGE",blocked["reason_codes"])
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
