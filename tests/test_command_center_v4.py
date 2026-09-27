import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agents.heartbeat_state import heartbeat,seed_state,validate_state
from dashboard.history_state import append_point,daily_trends,project_momentum,validate_state as validate_history
from dashboard.command_center import build_command_center_snapshot,render_html
from operator_console.operator_console import validate_approval_ledger
from scheduler.autonomous_scheduler import _owner_approval
import scheduler.autonomous_scheduler as scheduler_module

ROOT=Path(__file__).resolve().parents[1]


def telemetry(at="2026-09-26T18:00:00Z",completed=2,actions=1,cost=1.5,hunter=5,failures=0,verified=0):
    project_activity={f"PRJ-{i:03d}":{"open_work":0,"completed_work":0,"cancelled_work":0,"sent_actions":0,"verified_outcomes":0} for i in range(12)}
    project_activity["PRJ-001"].update({"open_work":1,"completed_work":completed,"sent_actions":actions,"verified_outcomes":verified})
    return {
      "generated_at":at,
      "queue":{"open_total":1,"counts":{"QUEUED":1,"ACTIVE":0,"COMPLETE":completed,"CANCELLED":0},"completed_fingerprint_count":completed},
      "cost":{
        "actual_usage_today":{"cost_usd":cost,"model_calls":actions,"api_calls":0,"github_runner_minutes":10},
        "budget_accounted_usage_today":{"cost_usd":cost,"model_calls":actions,"api_calls":0,"github_runner_minutes":10}
      },
      "hunter":{"totals":{"candidates":hunter,"retained":2}},
      "actions":{"total_sent":actions},
      "failures":{"count":failures},
      "verified_external_outcomes":verified,
      "project_activity":project_activity,
    }


class CommandCenterV4Tests(unittest.TestCase):
    def test_agent_heartbeat_is_durable_actual_workflow_evidence(self):
        state=seed_state()
        out=heartbeat(
          state,agent_ids=["AGT-HUNTER"],activity_kind="HUNTER_CYCLE",
          source_workflow="hunter-autonomous-cycle",source_run_id="123",at="2026-09-26T18:00:00Z"
        )
        validate_state(out)
        row=out["agents"]["AGT-HUNTER"]
        self.assertEqual(row["last_heartbeat_at"],"2026-09-26T18:00:00Z")
        self.assertEqual(row["source_run_id"],"123")
        self.assertEqual(row["last_activity_kind"],"HUNTER_CYCLE")
        self.assertIsNone(out["agents"]["AGT-AUDITOR"]["last_heartbeat_at"])

    def test_managed_workflows_persist_role_heartbeats(self):
        expected={
          ".github/workflows/portfolio-autonomous-scheduler.yml":"AGT-PORTFOLIO-MANAGER",
          ".github/workflows/hunter-autonomous-cycle.yml":"AGT-HUNTER",
          ".github/workflows/runtime-worker.yml":"AGT-DATA-STEWARD",
          ".github/workflows/software-factory-candidate.yml":"AGT-ENGINEER",
        }
        for path,agent in expected.items():
            body=(ROOT/path).read_text()
            self.assertIn("python -m agents.artifact_state",body,path)
            self.assertIn("python -m agents.heartbeat_state",body,path)
            self.assertIn(agent,body,path)
            self.assertIn("portfolio-agent-heartbeat-state",body,path)

    def test_hourly_history_replaces_same_hour_and_accumulates_daily_deltas(self):
        state={"schema_version":"1.0.0","state_id":"portfolio-command-center-history","sequence":0,"updated_at":None,"points":[]}
        state=append_point(state,telemetry("2026-09-26T18:05:00Z",completed=1,actions=1,cost=1.0,hunter=4),source_commit="a"*40)
        state=append_point(state,telemetry("2026-09-26T18:55:00Z",completed=2,actions=2,cost=1.5,hunter=6),source_commit="b"*40)
        self.assertEqual(len(state["points"]),1)
        self.assertEqual(state["points"][0]["metrics"]["completed_work_total"],2)
        state=append_point(state,telemetry("2026-09-27T01:00:00Z",completed=5,actions=3,cost=.5,hunter=9,verified=1),source_commit="c"*40)
        validate_history(state)
        daily=daily_trends(state,14)
        self.assertEqual(daily[-1]["completed_work"],3)
        self.assertEqual(daily[-1]["action_executions"],1)
        self.assertEqual(daily[-1]["verified_external_outcomes"],1)

    def test_project_momentum_is_signals_not_opaque_score(self):
        state={"schema_version":"1.0.0","state_id":"portfolio-command-center-history","sequence":0,"updated_at":None,"points":[]}
        state=append_point(state,telemetry("2026-09-25T18:00:00Z",completed=0,actions=0),source_commit="a")
        state=append_point(state,telemetry("2026-09-26T18:00:00Z",completed=3,actions=2,verified=1),source_commit="b")
        rows={x["project_id"]:x for x in project_momentum(state,24)}
        self.assertEqual(rows["PRJ-001"]["completed_work_delta"],3)
        self.assertEqual(rows["PRJ-001"]["sent_actions_delta"],2)
        self.assertEqual(rows["PRJ-001"]["verified_outcomes_delta"],1)
        self.assertNotIn("score",rows["PRJ-001"])

    def test_owner_approval_ledger_is_sanitized_closed_contract(self):
        doc={"schema_version":"1.0.0","ledger_id":"portfolio-owner-approvals","approvals":[{
          "approval_id":"OAPR-"+"A"*20,"source_ref":"experiment:123","project_ids":["PRJ-001"],
          "approval_requirements":["CUSTOMER_COMMUNICATION"],"approved_by":"P00NSMASHER",
          "approved_at":"2026-09-26T18:00:00Z","status":"ACTIVE","reason_hash":"sha256:"+"0"*64
        }]}
        validate_approval_ledger(doc)
        bad=copy.deepcopy(doc);bad["approvals"][0]["approved_by"]="user@example.com"
        with self.assertRaises(Exception):validate_approval_ledger(bad)

    def test_exact_owner_approval_unlocks_only_matching_prep_source(self):
        ledger={"schema_version":"1.0.0","ledger_id":"portfolio-owner-approvals","approvals":[{
          "approval_id":"OAPR-"+"B"*20,"source_ref":"EXP-1","project_ids":["PRJ-008"],
          "approval_requirements":["CUSTOMER_COMMUNICATION"],"approved_by":"P00NSMASHER",
          "approved_at":"2026-09-26T18:00:00Z","status":"ACTIVE","reason_hash":"sha256:"+"1"*64
        }]}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"operator_console").mkdir()
            (root/"operator_console"/"OWNER_APPROVALS.json").write_text(json.dumps(ledger))
            (root/"operator_console"/"OPERATOR_POLICY.json").write_text(json.dumps({"allowed_approval_actors":["P00NSMASHER"]}))
            exp={"experiment_id":"EXP-1","project_ids":["PRJ-008"],"approval_requirements":["CUSTOMER_COMMUNICATION"]}
            u={"uncertainty_id":"UNC-1"}
            with patch.object(scheduler_module,"ROOT",root):
                self.assertEqual(_owner_approval(exp,u)["approval_id"],"OAPR-"+"B"*20)
                bad=copy.deepcopy(exp);bad["project_ids"]=["PRJ-009"]
                self.assertIsNone(_owner_approval(bad,u))
                bad_actor=copy.deepcopy(ledger);bad_actor["approvals"][0]["approved_by"]="OTHER"
                (root/"operator_console"/"OWNER_APPROVALS.json").write_text(json.dumps(bad_actor))
                self.assertIsNone(_owner_approval(exp,u))

    def test_operator_console_is_owner_only_manual_and_not_public_ui(self):
        workflow=(ROOT/".github/workflows/operator-console.yml").read_text()
        self.assertIn("workflow_dispatch:",workflow)
        self.assertNotIn("\n  schedule:",workflow)
        self.assertIn("github.actor == github.repository_owner",workflow)
        self.assertIn("actions: write",workflow)
        self.assertIn("pull-requests: write",workflow)
        self.assertIn("CANCEL_QUEUE_ITEM",workflow)
        self.assertIn("EMERGENCY_STOP",workflow)
        self.assertIn("PROPOSE_BUDGET",workflow)
        self.assertIn("PROPOSE_APPROVAL",workflow)
        snapshot=build_command_center_snapshot()
        self.assertNotIn("operator-console.yml",snapshot["workflows"])
        public=render_html(snapshot).lower()
        self.assertNotIn("operator-console.yml",public)
        self.assertNotIn("operator console",public)

    def test_command_center_history_is_persisted_and_public_summary_only(self):
        workflow=(ROOT/".github/workflows/command-center-pages.yml").read_text()
        self.assertIn("dashboard.history_artifact_state",workflow)
        self.assertIn("dashboard.history_state",workflow)
        self.assertIn("portfolio-command-center-history",workflow)
        self.assertIn("public/history.json",workflow)

    def test_command_center_has_iphone_first_responsive_projection(self):
        public=render_html(build_command_center_snapshot())
        self.assertIn('viewport-fit=cover',public)
        self.assertIn('data-mobile-optimized="true"',public)
        self.assertIn('env(safe-area-inset-left)',public)
        self.assertIn('.mobile-records{display:none}',public)
        self.assertIn('.mobile-hide{display:none!important}',public)
        self.assertIn('<div class="mobile-records">',public)
        self.assertIn('font-size:16px;min-height:44px',public)

    def test_command_center_exposes_verified_model_value_without_inventing_it(self):
        snapshot=build_command_center_snapshot()
        self.assertIn("feedback_state",snapshot["model_router"])
        self.assertIn("verified_feedback_records",snapshot["model_router"]["feedback_state"])
        self.assertIn("verified_value_events",snapshot["model_router"]["feedback_state"])
        self.assertIn("model_feedback",snapshot["state_sources"]["sources"])
        public=render_html(snapshot)
        self.assertIn("Verified Model Value",public)
        self.assertIn("Value evidence is credited only from durable VERIFIED feedback.",public)

    def test_command_center_exposes_proof_carrying_learning_integrity(self):
        snapshot=build_command_center_snapshot()
        self.assertIn("learning_loop",snapshot)
        integrity=snapshot["learning_loop"]["integrity"]
        self.assertIn(integrity["status"],{"HEALTHY","DEGRADED","NO_VERIFIED_VALUE"})
        self.assertFalse(integrity["authority_granted"])
        self.assertFalse(integrity["policy_promoted"])
        self.assertFalse(integrity["evidence_upgraded"])
        self.assertIn("learning",snapshot["state_sources"]["sources"])
        public=render_html(snapshot)
        self.assertIn("Verified Learning Integrity",public)
        self.assertIn("cross-checks Hunter, model feedback, and continuous learning",public)

    def test_pages_artifact_is_rerun_safe_and_attempt_scoped(self):
        workflow=(ROOT/".github/workflows/command-center-pages.yml").read_text()
        self.assertIn("name: github-pages-${{ github.run_attempt }}",workflow)
        self.assertIn("artifact_name: github-pages-${{ github.run_attempt }}",workflow)

    def test_command_center_exposes_hunter_proposal_inbox_without_rights_upgrade(self):
        snapshot=build_command_center_snapshot()
        self.assertIn("hunter_proposals",snapshot)
        proposals=snapshot["hunter_proposals"]
        self.assertEqual(proposals["authority_class"],"OBSERVE")
        self.assertEqual(proposals["rights_state"],"NOT_GRANTED_BY_DISCOVERY")
        self.assertEqual(proposals["proposal_count"],len(proposals["proposals"]))
        public=render_html(snapshot)
        self.assertIn("Hunter Proposal Inbox",public)
        self.assertIn("Discovery never grants reuse rights.",public)
        self.assertIn("exact-revision public candidates",public)
        self.assertIn("hunter_proposal_reviews",snapshot["state_sources"]["sources"])
        self.assertIn("review_state_sequence",proposals)
        self.assertIn("evidence_reviewed_count",proposals)
        self.assertLessEqual(proposals["evidence_reviewed_count"],proposals["proposal_count"])
        self.assertIn("License metadata",public)

    def test_scheduler_executes_work_before_heartbeating_workers(self):
        workflow=(ROOT/".github/workflows/portfolio-autonomous-scheduler.yml").read_text()
        self.assertIn("python -m scheduler.work_executor",workflow)
        self.assertIn("--selected-work scheduler/out/executed_work.json",workflow)
        self.assertNotIn("--selected-work scheduler/out/scheduled_work.json",workflow)
        self.assertIn("--activity-kind WORK_EXECUTION",workflow)
        self.assertIn("portfolio-hunter-state",workflow)
        self.assertLess(
            workflow.index("python -m scheduler.work_executor"),
            workflow.index("--activity-kind WORK_EXECUTION"),
        )

    def test_blanket_heartbeat_is_backed_by_real_subsystem_probes(self):
        workflow=(ROOT/".github/workflows/agent-heartbeat-sweep.yml").read_text()
        self.assertIn("python -m agents.validate_agents",workflow)
        self.assertIn("python -m scheduler.validate_scheduler",workflow)
        self.assertIn("python -m hunting.validate_hunter",workflow)
        self.assertIn("python -m runtime.validate_runtime",workflow)
        self.assertLess(
            workflow.index("Run deterministic subsystem probes"),
            workflow.index("Heartbeat every registered agent"),
        )

    def test_command_center_exposes_functional_not_declared_health(self):
        snapshot=build_command_center_snapshot()
        self.assertIn("functional_status",snapshot["system"])
        self.assertIn("functional_reasons",snapshot["system"])
        public=render_html(snapshot)
        self.assertIn("Functional health",public)
        self.assertIn("EVIDENCE-DRIVEN",public)


if __name__=="__main__":
    unittest.main()
