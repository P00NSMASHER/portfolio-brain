import json
import unittest
from pathlib import Path

from adapters.project_forwarding import ProjectForwardingError, digest, forward_cycle
from adapters.abvm_constrained import build_abvm_evidence
from governance.evidence_semantics import can_verify, verification_credit
from governance.validate_boundaries import validate_boundaries
from hunting.repo001_intake import build_intake, validate_intake
from dashboard.live_state_bridge import _freshness_detail, _source_state_hash

ROOT=Path(__file__).resolve().parents[1]

def adapter_for(repository_id):
    rows=json.loads((ROOT/"adapters"/"ADAPTER_REGISTRY.json").read_text())["adapters"]
    return next(row for row in rows if row["repository_id"]==repository_id)

def observation(repository_id, *, status="UNCHANGED", revision="a"*40, changed=0):
    adapter=adapter_for(repository_id)
    body={
      "schema_version":"1.0.0",
      "adapter_id":adapter["adapter_id"],
      "repository_id":repository_id,
      "repository_full_name":adapter["repository_full_name"],
      "source_ref":adapter["source_ref_policy"]["ref"],
      "status":status,
      "prior_sha":revision if status=="UNCHANGED" else None,
      "current_sha":None if status=="BLOCKED" else revision,
      "network_reads":0 if status=="BLOCKED" else 1,
      "compare":({"changed_file_count":changed,"files":[]} if status=="CHANGED" else None),
      "observed_at":"2026-09-30T14:00:00Z",
    }
    return {**body,"receipt_hash":digest(body)}

def cycle(observations):
    body={
      "schema_version":"1.0.0",
      "cycle_id":"cycle-worker4-proof",
      "mode":"observe",
      "started_at":"2026-09-30T14:00:00Z",
      "finished_at":"2026-09-30T14:00:00Z",
      "status":"PASS",
      "reason":None,
      "observations":observations,
      "api_requests":1,
    }
    return {**body,"receipt_hash":digest(body)}

class Worker4RemediationTests(unittest.TestCase):
    def test_project_forwarding_is_idempotent_exact_identity_once(self):
        obs=observation("REPO-008")
        receipt=forward_cycle(cycle([obs,obs]))
        self.assertEqual(1,receipt["delivery_count"])
        self.assertEqual(1,receipt["duplicate_observations_suppressed"])
        self.assertEqual("PRJ-000",receipt["deliveries"][0]["project_id"])
        self.assertFalse(receipt["authority_inherited"])
        self.assertFalse(receipt["deliveries"][0]["downstream_write"])

    def test_repo001_routes_each_declared_project_once(self):
        receipt=forward_cycle(cycle([observation("REPO-001")]))
        projects=[row["project_id"] for row in receipt["deliveries"]]
        self.assertEqual(["PRJ-001","PRJ-002","PRJ-008","PRJ-009","PRJ-010","PRJ-011"],projects)
        self.assertEqual(len(projects),len(set(projects)))

    def test_wrong_project_and_forbidden_capabilities_fail_closed(self):
        c=cycle([observation("REPO-008")])
        with self.assertRaisesRegex(ProjectForwardingError,"wrong-project"):
            forward_cycle(c,requested_project_id="PRJ-006")
        for capability in ("CANDIDATE_PR","DEPLOY","EXTERNAL_ACTION"):
            with self.subTest(capability=capability), self.assertRaises(ProjectForwardingError):
                forward_cycle(c,requested_capability=capability)

    def test_blocked_repository_binding_is_reportable_without_authority(self):
        receipt=forward_cycle(cycle([observation("REPO-006",status="BLOCKED")]))
        self.assertEqual(1,receipt["delivery_count"])
        delivery=receipt["deliveries"][0]
        self.assertEqual("PRJ-003",delivery["project_id"])
        self.assertEqual("BLOCKED",delivery["observation_status"])
        self.assertFalse(delivery["deployment"])

    def test_repo001_scout_bridge_dedupes_and_remains_preverification(self):
        candidate={
          "repository":"example/research-tool","exact_revision":"b"*40,
          "status":"PRE_VERIFICATION_CANDIDATE","archived":False,
          "triage_score":54,"root_code_signals":["src","tests"],
          "published_license_spdx":"MIT","discovery_query":"bounded research tool",
        }
        low={**candidate,"repository":"example/low","exact_revision":"c"*40,"triage_score":10}
        snapshots=[
          {"worker_id":"HUNTER-01","authority":"PRE_VERIFICATION_DISCOVERY_ONLY","candidates":[candidate,low]},
          {"worker_id":"HUNTER-02","authority":"PRE_VERIFICATION_DISCOVERY_ONLY","candidates":[candidate]},
        ]
        receipt=build_intake("d"*40,snapshots)
        validate_intake(receipt)
        self.assertEqual(1,receipt["intake_record_count"])
        self.assertEqual(1,receipt["rejection_counts"]["BELOW_TRIAGE_GATE"])
        record=receipt["records"][0]
        self.assertEqual(["HUNTER-01","HUNTER-02"],record["source_worker_ids"])
        self.assertFalse(record["proposal_eligible"])
        self.assertEqual({"technical":False,"market":False,"revenue":False},receipt["verification_credit"])
        self.assertFalse(receipt["creates_hunter_engine"])

    def test_abvm_projection_is_health_progress_only(self):
        c=cycle([observation("REPO-003",status="CHANGED",revision="e"*40,changed=7)])
        forwarding=forward_cycle(c)
        evidence=build_abvm_evidence(c,forwarding)
        self.assertEqual(["AUTOMATION_HEALTH","AUTOMATION_PROGRESS"],evidence["evidence_scope"])
        self.assertEqual(7,evidence["changed_file_count"])
        self.assertFalse(evidence["content_body_included"])
        self.assertFalse(evidence["child_data_included"])
        self.assertFalse(evidence["child_facing_mutation"])
        self.assertFalse(evidence["school_content_publication"])
        self.assertFalse(evidence["deployment_authority"])
        self.assertFalse(evidence["external_action_authority"])

    def test_heartbeat_notification_pages_and_observation_never_verify(self):
        for kind in ("HEARTBEAT","NOTIFICATION","PAGES_PUBLICATION","REPOSITORY_OBSERVATION"):
            with self.subTest(kind=kind):
                credit=verification_credit(kind)
                self.assertEqual({"meaning":credit["meaning"],"technical":False,"market":False,"revenue":False},credit)
                for dimension in ("technical","market","revenue"):
                    self.assertFalse(can_verify(kind,dimension))

    def test_dashboard_freshness_helpers_expose_hash_and_blocked_state(self):
        state={"sequence":9,"updated_at":"2026-09-30T14:00:00Z"}
        self.assertTrue(_source_state_hash(state).startswith("sha256:"))
        self.assertEqual((True,False,"STALE_SOURCE"),_freshness_detail("STALE","RESTORED_ARTIFACT",None))
        self.assertEqual((False,True,"ValueError"),_freshness_detail("FALLBACK","RESTORE_ERROR","ValueError"))

    def test_machine_authority_matrix_cross_checks_current_config(self):
        proof=validate_boundaries()
        self.assertEqual(12,proof["projects"])
        self.assertEqual("DENY",proof["default_decision"])

if __name__=="__main__":
    unittest.main()
