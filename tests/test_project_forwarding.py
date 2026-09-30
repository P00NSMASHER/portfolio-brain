import copy
import unittest

from runtime.project_forwarding import ProjectForwardingError, build_project_delivery, forward_observations, seed_state

def obs(repo_id="REPO-003",adapter_id="ADP-003",full_name="P00NSMASHER/abvmschoolstarworld",sha="a"*40,status="CHANGED"):
    return {
      "schema_version":"1.0.0","adapter_id":adapter_id,"repository_id":repo_id,
      "repository_full_name":full_name,"source_ref":"main","observed_at":"2026-09-30T14:00:00Z",
      "status":status,"blocked_by":None,"prior_sha":"b"*40 if status=="CHANGED" else None,
      "current_sha":sha if status!="BLOCKED" else None,"compare":None,"network_reads":1,
      "receipt_hash":"sha256:"+"c"*64,
    }

class ProjectForwardingTests(unittest.TestCase):
    def test_abvm_changed_revision_routes_once_as_sanitized_health_progress_evidence(self):
        state,receipt=forward_observations(
          seed_state(),[obs(),obs()],at="2026-09-30T14:00:01Z",
          cycle_id="CYCLE-1",cycle_receipt_hash="sha256:"+"d"*64)
        self.assertEqual(len(receipt["deliveries"]),1)
        delivery=receipt["deliveries"][0]
        self.assertEqual(delivery["project_id"],"PRJ-006")
        self.assertEqual(delivery["evidence_scope"],["REPOSITORY_OBSERVATION"])
        self.assertEqual(delivery["payload_scope"],"SANITIZED_METADATA_ONLY")
        self.assertFalse(delivery["authority_granted"])
        self.assertFalse(delivery["mutation_performed"])
        self.assertFalse(delivery["deploy_authority"])
        self.assertFalse(delivery["child_facing_mutation_authority"])
        self.assertFalse(delivery["school_content_publication_authority"])
        self.assertEqual(state["sequence"],1)
        self.assertEqual(len(state["delivered_keys"]),1)

    def test_repeat_cycle_is_idempotently_suppressed(self):
        first,_=forward_observations(seed_state(),[obs()],at="2026-09-30T14:00:01Z",cycle_id="C1",cycle_receipt_hash="sha256:"+"d"*64)
        second,receipt=forward_observations(first,[obs()],at="2026-09-30T14:01:01Z",cycle_id="C2",cycle_receipt_hash="sha256:"+"e"*64)
        self.assertEqual(receipt["deliveries"],[])
        self.assertEqual(len(receipt["duplicate_delivery_keys"]),1)
        self.assertEqual(second["sequence"],first["sequence"])

    def test_wrong_project_routing_fails_closed(self):
        with self.assertRaisesRegex(ProjectForwardingError,"wrong-project"):
            build_project_delivery(obs(),"PRJ-005",at="2026-09-30T14:00:01Z")

    def test_unchanged_observation_is_not_forwarded_as_new_project_progress(self):
        state,receipt=forward_observations(seed_state(),[obs(status="UNCHANGED")],at="2026-09-30T14:00:01Z",cycle_id="C1",cycle_receipt_hash="sha256:"+"d"*64)
        self.assertEqual(receipt["deliveries"],[])
        self.assertEqual(receipt["skipped_observations"],[{"repository_id":"REPO-003","status":"UNCHANGED"}])
        self.assertEqual(state["sequence"],0)

    def test_repo001_fans_out_only_to_its_six_registered_projects(self):
        o=obs(repo_id="REPO-001",adapter_id="ADP-001",full_name="P00NSMASHER/github-value-hunt-ledger",sha="1"*40)
        _,receipt=forward_observations(seed_state(),[o],at="2026-09-30T14:00:01Z",cycle_id="C1",cycle_receipt_hash="sha256:"+"d"*64)
        self.assertEqual({x["project_id"] for x in receipt["deliveries"]},{"PRJ-001","PRJ-002","PRJ-008","PRJ-009","PRJ-010","PRJ-011"})
        self.assertEqual(len(receipt["deliveries"]),6)

    def test_blocked_repository_never_forwards(self):
        blocked=obs(repo_id="REPO-006",adapter_id="ADP-006",full_name="P00NSMASHER/permitplate-state",status="BLOCKED")
        blocked["blocked_by"]="BLK-001";blocked["network_reads"]=0
        _,receipt=forward_observations(seed_state(),[blocked],at="2026-09-30T14:00:01Z",cycle_id="C1",cycle_receipt_hash="sha256:"+"d"*64)
        self.assertEqual(receipt["deliveries"],[])

if __name__=="__main__":
    unittest.main()
