import copy
import json
import tempfile
import unittest
from pathlib import Path

from agents.heartbeat_state import AgentHeartbeatError, heartbeat, seed_state, validate_state

ROOT=Path(__file__).resolve().parents[1]


class AgentHeartbeatStateTests(unittest.TestCase):
    def test_seed_covers_all_ten_persistent_roles(self):
        state=seed_state();validate_state(state)
        self.assertEqual(len(state["agents"]),10)
        self.assertTrue(all(row["last_heartbeat_at"] is None for row in state["agents"].values()))

    def test_heartbeat_is_sanitized_and_durable(self):
        state=heartbeat(
            seed_state(),
            agent_ids=["AGT-HUNTER","AGT-RESEARCHER"],
            activity_kind="TEST_ACTIVITY",
            source_workflow="synthetic-workflow",
            source_run_id="12345",
            work_ids_by_agent={"AGT-RESEARCHER":["SWORK-ABC"]},
            at="2026-09-26T18:00:00Z",
        )
        validate_state(state)
        self.assertEqual(state["sequence"],1)
        self.assertEqual(state["agents"]["AGT-HUNTER"]["last_heartbeat_at"],"2026-09-26T18:00:00Z")
        self.assertIn("SWORK-ABC",state["agents"]["AGT-RESEARCHER"]["recent_work_ids"])
        raw=json.dumps(state).lower()
        for forbidden in ["password","api_key","private_payload","customer_email"]:
            self.assertNotIn(forbidden,raw)

    def test_health_check_sweep_covers_every_registered_agent(self):
        state=seed_state()
        agent_ids=sorted(state["agents"])
        out=heartbeat(
            state,
            agent_ids=agent_ids,
            activity_kind="HEALTH_CHECK",
            source_workflow="agent-heartbeat-sweep",
            source_run_id="health-run-1",
            at="2026-09-26T23:00:00Z",
        )
        validate_state(out)
        self.assertEqual(len(out["agents"]),10)
        self.assertTrue(all(row["last_heartbeat_at"]=="2026-09-26T23:00:00Z" for row in out["agents"].values()))
        self.assertTrue(all(row["last_activity_kind"]=="HEALTH_CHECK" for row in out["agents"].values()))
        self.assertTrue(all(row["source_workflow"]=="agent-heartbeat-sweep" for row in out["agents"].values()))

    def test_event_content_tampering_breaks_hash_validation(self):
        state=heartbeat(
            seed_state(),
            agent_ids=["AGT-HUNTER"],
            activity_kind="HUNTER_CYCLE",
            source_workflow="hunter-autonomous-cycle",
            source_run_id="trusted-run",
            at="2026-09-26T18:00:00Z",
        )
        for field,value in (
            ("activity_kind","FORGED_SUCCESS"),
            ("source_run_id","forged-run"),
            ("agent_id","AGT-AUDITOR"),
        ):
            poisoned=copy.deepcopy(state)
            poisoned["recent_events"][0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(AgentHeartbeatError,"hash mismatch"):
                validate_state(poisoned)

    def test_latest_agent_projection_must_match_event_history(self):
        state=heartbeat(
            seed_state(),
            agent_ids=["AGT-HUNTER"],
            activity_kind="HUNTER_CYCLE",
            source_workflow="hunter-autonomous-cycle",
            source_run_id="trusted-run",
            work_ids_by_agent={"AGT-HUNTER":["SWORK-TRUSTED"]},
            at="2026-09-26T18:00:00Z",
        )
        poisoned=copy.deepcopy(state)
        poisoned["agents"]["AGT-HUNTER"]["source_run_id"]="forged-run"
        with self.assertRaisesRegex(AgentHeartbeatError,"source run is not event-backed"):
            validate_state(poisoned)
        poisoned=copy.deepcopy(state)
        poisoned["agents"]["AGT-HUNTER"]["recent_work_ids"]=[]
        with self.assertRaisesRegex(AgentHeartbeatError,"work ids are not event-backed"):
            validate_state(poisoned)

    def test_heartbeat_time_cannot_roll_back_durable_state(self):
        state=heartbeat(
            seed_state(),
            agent_ids=["AGT-HUNTER"],
            activity_kind="HUNTER_CYCLE",
            source_workflow="hunter-autonomous-cycle",
            source_run_id="newer-run",
            at="2026-09-26T18:00:00Z",
        )
        with self.assertRaisesRegex(AgentHeartbeatError,"cannot move backward"):
            heartbeat(
                state,
                agent_ids=["AGT-HUNTER"],
                activity_kind="HUNTER_CYCLE",
                source_workflow="hunter-autonomous-cycle",
                source_run_id="older-run",
                at="2026-09-26T17:59:59Z",
            )

    def test_event_history_reordering_is_rejected(self):
        state=heartbeat(
            seed_state(),
            agent_ids=["AGT-HUNTER"],
            activity_kind="HUNTER_CYCLE",
            source_workflow="hunter-autonomous-cycle",
            source_run_id="run-1",
            at="2026-09-26T18:00:00Z",
        )
        state=heartbeat(
            state,
            agent_ids=["AGT-AUDITOR"],
            activity_kind="AUDIT",
            source_workflow="hostile-regression",
            source_run_id="run-2",
            at="2026-09-26T18:01:00Z",
        )
        poisoned=copy.deepcopy(state)
        poisoned["recent_events"].reverse()
        with self.assertRaisesRegex(AgentHeartbeatError,"not chronological"):
            validate_state(poisoned)

    def test_health_check_workflow_is_governed_and_recurring(self):
        body=(ROOT/".github/workflows/agent-heartbeat-sweep.yml").read_text()
        self.assertIn('cron: "29 */2 * * *"',body)
        self.assertIn("--all-registered",body)
        self.assertIn("--activity-kind HEALTH_CHECK",body)
        self.assertIn("cost_governor.workflow_gate preflight",body)
        self.assertIn("cost_governor.workflow_gate finalize",body)
        self.assertIn("name: portfolio-agent-heartbeat-state",body)
        self.assertIn("path: agents/out/agent_heartbeat_state.json",body)

    def test_operational_workflows_persist_heartbeat_artifacts(self):
        required={
            ".github/workflows/portfolio-autonomous-scheduler.yml":"--selected-work scheduler/out/executed_work.json",
            ".github/workflows/hunter-autonomous-cycle.yml":"--agent-id AGT-HUNTER",
            ".github/workflows/runtime-worker.yml":"--agent-id AGT-DATA-STEWARD",
            ".github/workflows/software-factory-candidate.yml":"--agent-id AGT-ENGINEER",
        }
        for path,marker in required.items():
            body=(ROOT/path).read_text()
            self.assertIn("python -m agents.artifact_state",body,path)
            self.assertIn("python -m agents.heartbeat_state",body,path)
            self.assertIn(marker,body,path)
            self.assertIn("name: portfolio-agent-heartbeat-state",body,path)
            self.assertIn("path: agents/out/agent_heartbeat_state.json",body,path)
        scheduler=(ROOT/".github/workflows/portfolio-autonomous-scheduler.yml").read_text()
        self.assertNotIn("--selected-work scheduler/out/scheduled_work.json",scheduler)


if __name__=="__main__":
    unittest.main()
