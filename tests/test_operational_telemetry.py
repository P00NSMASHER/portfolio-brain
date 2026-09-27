import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import dashboard.operational_telemetry as telemetry
from agents.heartbeat_state import heartbeat,seed_state
from cost_governor.cost_governor import commit_reservation,load_state as load_cost_state,make_github_job_request,preflight,zero_usage
from runtime.state import bootstrap_state
from scheduler.autonomous_scheduler import build_context,load_state as load_scheduler_state,mark_work,schedule_cycle

ROOT=Path(__file__).resolve().parents[1]
AT="2026-09-26T12:00:00Z"


class OperationalTelemetryTests(unittest.TestCase):
    def _write(self,root,name,value):
        (root/name).write_text(json.dumps(value))

    def test_live_telemetry_separates_actual_from_conservative_accounting(self):
        with tempfile.TemporaryDirectory() as td:
            live=Path(td)

            scheduler,receipt=schedule_cycle(load_scheduler_state(),build_context(),at=AT)
            fps=[w["fingerprint"] for w in receipt["selected_work"]]
            scheduler=mark_work(scheduler,fps[0],"ACTIVE")
            scheduler=mark_work(scheduler,fps[1],"CANCELLED")
            scheduler=mark_work(scheduler,fps[2],"ACTIVE")
            scheduler=mark_work(scheduler,fps[2],"COMPLETE")
            self._write(live,"scheduler_state.json",scheduler)

            cost=load_cost_state()
            r1=make_github_job_request(workflow_id="runtime-worker",job_id="runtime-sync",run_id="telemetry-1",attempt=1,project_ids=["PRJ-000"],estimated_minutes=5,authority_class="OBSERVE",at=AT)
            cost,d1=preflight(cost,r1,at=AT)
            actual=zero_usage();actual.update({"github_job_starts":1,"github_runner_minutes":3})
            cost,_=commit_reservation(cost,d1["reservation_id"],actual,at=AT)
            r2=make_github_job_request(workflow_id="runtime-worker",job_id="runtime-sync",run_id="telemetry-2",attempt=1,project_ids=["PRJ-000"],estimated_minutes=5,authority_class="OBSERVE",at=AT)
            cost,_=preflight(cost,r2,at=AT)
            self._write(live,"cost_state.json",cost)

            hunter=json.loads((ROOT/"hunting/HUNTER_STATE_SEED.json").read_text())
            hunter["sequence"]=2;hunter["updated_at"]=AT
            first=next(iter(hunter["strategy_stats"].values()))
            first["cycles"]=2;first["candidates"]=7;first["retained"]=2
            hunter["recent_cycles"]=[{"cycle_id":"HC-1","finished_at":AT,"receipt_hash":"sha256:"+"1"*64,"retained":2,"proposals":0}]
            self._write(live,"hunter_state.json",hunter)

            notifications=json.loads((ROOT/"notifications/NOTIFICATION_STATE_SEED.json").read_text())
            self._write(live,"notification_state.json",notifications)

            agent_state=heartbeat(seed_state(),agent_ids=["AGT-HUNTER"],activity_kind="HUNTER_CYCLE",source_workflow="hunter-autonomous-cycle",source_run_id="42",at=AT)
            self._write(live,"agent_heartbeat_state.json",agent_state)

            runtime=bootstrap_state(now=AT)
            runtime["sequence"]=1;runtime["updated_at"]=AT;runtime["last_cycle_id"]="RC-1"
            runtime["recent_cycles"]=[{"cycle_id":"RC-1","mode":"sync","finished_at":AT,"status":"PASS","receipt_hash":"sha256:"+"2"*64}]
            self._write(live,"runtime_state.json",runtime)

            sources={"generated_at":AT,"bridge_status":"LIVE","sources":{
                key:{"status":"LIVE","age_minutes":0,"source_run_id":"1","artifact_created_at":AT}
                for key in ["runtime","scheduler","hunter","cost","notifications","agents"]
            }}
            self._write(live,"state_sources.json",sources)

            with patch.object(telemetry,"LIVE",live):
                out=telemetry.build_operational_telemetry(at=AT)

        self.assertEqual(out["queue"]["counts"]["ACTIVE"],1)
        self.assertEqual(out["queue"]["counts"]["COMPLETE"],1)
        self.assertEqual(out["queue"]["counts"]["CANCELLED"],1)
        self.assertEqual(out["cost"]["actual_usage_today"]["github_runner_minutes"],3)
        self.assertEqual(out["cost"]["budget_accounted_usage_today"]["github_runner_minutes"],8)
        self.assertGreater(out["cost"]["utilization"]["github_runner_minutes"]["used"],out["cost"]["utilization"]["github_runner_minutes"]["actual"])
        hunter_row=next(x for x in out["agents"]["agents"] if x["agent_id"]=="AGT-HUNTER")
        self.assertEqual(hunter_row["heartbeat_health"],"LIVE")
        self.assertEqual(out["cycles"]["latest_overall"]["subsystem"],"runtime")
        self.assertEqual(out["runtime_sync_proof"]["status"],"VERIFIED_SYNC_WORK")
        self.assertEqual(out["runtime_sync_proof"]["source_run_id"],"telemetry-1")
        self.assertEqual(out["hunter"]["totals"]["candidates"],7)
        self.assertGreaterEqual(out["failures"]["count"],1)

    def test_runtime_sync_proof_survives_newer_observe_artifact(self):
        runtime={"recent_cycles":[{
            "mode":"sync","status":"PASS","cycle_id":"RC-1",
            "finished_at":"2026-09-26T11:59:30Z","receipt_hash":"sha256:"+"a"*64
        },{
            "mode":"observe","status":"PASS","cycle_id":"RC-2",
            "finished_at":"2026-09-26T12:00:30Z","receipt_hash":"sha256:"+"b"*64
        }]}
        source={"generated_at":"2026-09-26T12:01:00Z","sources":{
            "runtime":{"status":"LIVE","source_run_id":99},
            "cost":{"status":"LIVE","source_run_id":99},
        }}
        cost={"reservations":[{
            "reservation_id":"CRES-SYNC",
            "resource_kind":"GITHUB_JOB",
            "workflow_id":"runtime-worker","job_id":"runtime-sync","status":"COMMITTED",
            "created_at":"2026-09-26T11:59:00Z",
            "committed_at":"2026-09-26T12:00:00Z",
            "evidence_refs":["github-run:42","workflow:runtime-worker","job:runtime-sync","github-run:42:finalized"],
        }]}
        proof=telemetry._runtime_sync_proof(runtime,cost,source)
        self.assertEqual(proof["status"],"VERIFIED_SYNC_WORK")
        self.assertEqual(proof["source_run_id"],42)
        self.assertEqual(proof["runtime_artifact_source_run_id"],99)
        self.assertEqual(proof["reservation_id"],"CRES-SYNC")
        self.assertEqual(proof["cycle_id"],"RC-1")

    def test_runtime_sync_proof_fails_closed_without_temporal_reservation_match(self):
        runtime={"recent_cycles":[{
            "mode":"sync","status":"PASS","cycle_id":"RC-1",
            "finished_at":"2026-09-26T11:59:30Z","receipt_hash":"sha256:"+"a"*64
        }]}
        source={"generated_at":"2026-09-26T12:01:00Z","sources":{
            "runtime":{"status":"LIVE","source_run_id":99},
            "cost":{"status":"LIVE","source_run_id":99},
        }}
        cost={"reservations":[{
            "reservation_id":"CRES-WRONG-WINDOW",
            "resource_kind":"GITHUB_JOB",
            "workflow_id":"runtime-worker","job_id":"runtime-sync","status":"COMMITTED",
            "created_at":"2026-09-26T11:00:00Z",
            "committed_at":"2026-09-26T11:01:00Z",
            "evidence_refs":["github-run:42"],
        }]}
        proof=telemetry._runtime_sync_proof(runtime,cost,source)
        self.assertEqual(proof["status"],"UNVERIFIED_SYNC_WORK")
        self.assertEqual(proof["reason"],"MISSING_MATCHING_SYNC_RESERVATION")

    def test_runtime_sync_proof_rejects_stale_sync_even_if_observe_state_is_live(self):
        runtime={"recent_cycles":[{
            "mode":"sync","status":"PASS","cycle_id":"RC-OLD",
            "finished_at":"2026-09-26T09:00:00Z","receipt_hash":"sha256:"+"a"*64
        }]}
        source={"generated_at":"2026-09-26T12:01:00Z","sources":{
            "runtime":{"status":"LIVE","source_run_id":99},
            "cost":{"status":"LIVE","source_run_id":99},
        }}
        cost={"reservations":[{
            "reservation_id":"CRES-OLD",
            "resource_kind":"GITHUB_JOB",
            "workflow_id":"runtime-worker","job_id":"runtime-sync","status":"COMMITTED",
            "created_at":"2026-09-26T08:59:00Z",
            "committed_at":"2026-09-26T09:01:00Z",
            "evidence_refs":["github-run:42"],
        }]}
        proof=telemetry._runtime_sync_proof(runtime,cost,source)
        self.assertEqual(proof["status"],"UNVERIFIED_SYNC_WORK")
        self.assertEqual(proof["reason"],"SYNC_CYCLE_TOO_OLD")

    def test_health_check_cannot_hide_stalled_assigned_work(self):
        scheduler,receipt=schedule_cycle(
            load_scheduler_state(),build_context(),at="2026-09-26T10:00:00Z"
        )
        hunt=next(row for row in receipt["selected_work"] if row["work_type"]=="HUNT")
        scheduler["work_items"]=[hunt]
        agents=seed_state()
        agents=heartbeat(
            agents,
            agent_ids=list(agents["agents"]),
            activity_kind="HEALTH_CHECK",
            source_workflow="agent-heartbeat-sweep",
            source_run_id="probe-1",
            at=AT,
        )
        view=telemetry._agents(
            agents,scheduler,at=datetime.fromisoformat(AT.replace("Z","+00:00")).astimezone(timezone.utc)
        )
        hunter=next(row for row in view["agents"] if row["agent_id"]=="AGT-HUNTER")
        auditor=next(row for row in view["agents"] if row["agent_id"]=="AGT-AUDITOR")
        self.assertEqual(hunter["heartbeat_health"],"STALLED")
        self.assertEqual(hunter["open_work_count"],1)
        self.assertEqual(auditor["heartbeat_health"],"IDLE_HEALTHY")
        self.assertEqual(view["stalled"],1)

    def test_real_activity_survives_later_health_probe(self):
        scheduler,receipt=schedule_cycle(
            load_scheduler_state(),build_context(),at="2026-09-26T10:00:00Z"
        )
        hunt=next(row for row in receipt["selected_work"] if row["work_type"]=="HUNT")
        scheduler["work_items"]=[hunt]
        agents=heartbeat(
            seed_state(),
            agent_ids=["AGT-HUNTER"],
            activity_kind="HUNTER_CYCLE",
            source_workflow="hunter-autonomous-cycle",
            source_run_id="real-1",
            at="2026-09-26T11:30:00Z",
        )
        agents=heartbeat(
            agents,
            agent_ids=list(agents["agents"]),
            activity_kind="HEALTH_CHECK",
            source_workflow="agent-heartbeat-sweep",
            source_run_id="probe-2",
            at=AT,
        )
        view=telemetry._agents(
            agents,scheduler,at=datetime.fromisoformat(AT.replace("Z","+00:00")).astimezone(timezone.utc)
        )
        hunter=next(row for row in view["agents"] if row["agent_id"]=="AGT-HUNTER")
        self.assertEqual(hunter["heartbeat_health"],"LIVE")
        self.assertEqual(hunter["last_activity_kind"],"HUNTER_CYCLE")
        self.assertEqual(hunter["source_run_id"],"real-1")


if __name__=="__main__":
    unittest.main()
