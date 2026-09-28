import copy
import unittest

from hunting.proposal_review_state import (
    HunterProposalReviewError,
    apply_execution_receipts,
    digest,
    load_seed_state,
    validate_state,
)


def review_receipt():
    result={
      "proposal_id":"HEXP-TEST-REVIEW",
      "finding_id":"HFD-TEST-REVIEW",
      "repository_full_name":"public/example",
      "repository_id":123,
      "revision":"a"*40,
      "tree_sha":"b"*40,
      "rank_score":9,
      "rank_band":"HIGH",
      "capability_key":"capability-coverage:freight-recovery",
      "license_spdx_id":"MIT",
      "license_name":"MIT License",
      "license_state":"LICENSE_METADATA_PRESENT_INFORMATIONAL",
      "rights_state":"OPERATOR_ASSUMED",
      "reuse_authorized":False,
      "implementation_authorized":False,
      "code_execution_performed":False,
      "downstream_mutation_performed":False,
    }
    body={
      "schema_version":"1.0.0",
      "execution_id":"WEXEC-TEST-REVIEW",
      "scheduler_work_id":"SWORK-TEST-REVIEW",
      "fingerprint":"sha256:"+"1"*64,
      "work_type":"RESEARCH",
      "assigned_agent_id":"AGT-RESEARCHER",
      "project_ids":["PRJ-002"],
      "started_at":"2026-09-27T07:20:00Z",
      "finished_at":"2026-09-27T07:20:05Z",
      "status":"SUCCESS",
      "result_kind":"HUNTER_PROPOSAL_PUBLIC_EVIDENCE_REVIEW",
      "result":result,
      "evidence_refs":[
        "hunter-proposal:HEXP-TEST-REVIEW",
        "hunter-finding:HFD-TEST-REVIEW",
        "github:public/example@"+"a"*40,
        "git-tree:"+"b"*40,
        "license-metadata:MIT",
      ],
      "authority_granted":False,
    }
    return {**body,"receipt_hash":digest(body)}


class HunterProposalReviewStateTests(unittest.TestCase):
    def test_successful_scheduler_review_becomes_durable_sanitized_state(self):
        state,report=apply_execution_receipts(load_seed_state(),[review_receipt()])
        validate_state(state)
        self.assertEqual(report["status"],"UPDATED")
        self.assertEqual(state["sequence"],1)
        self.assertEqual(len(state["reviews"]),1)
        row=state["reviews"][0]
        self.assertEqual(row["proposal_id"],"HEXP-TEST-REVIEW")
        self.assertEqual(row["license_spdx_id"],"MIT")
        self.assertEqual(row["rights_state"],"OPERATOR_ASSUMED")
        self.assertFalse(row["reuse_authorized"])
        self.assertFalse(row["implementation_authorized"])
        self.assertFalse(row["code_execution_performed"])
        self.assertFalse(row["downstream_mutation_performed"])
        self.assertFalse(report["authority_granted"])
        self.assertTrue(report["rights_resolved"])

    def test_same_execution_receipt_is_idempotent(self):
        state,first=apply_execution_receipts(load_seed_state(),[review_receipt()])
        sequence=state["sequence"]
        state,second=apply_execution_receipts(state,[review_receipt()])
        self.assertEqual(first["status"],"UPDATED")
        self.assertEqual(second["status"],"NO_NEW_REVIEWS")
        self.assertEqual(state["sequence"],sequence)
        self.assertEqual(len(state["reviews"]),1)

    def test_non_review_scheduler_receipts_are_ignored(self):
        receipt=review_receipt()
        receipt["result_kind"]="REPOSITORY_OBSERVATION"
        body=dict(receipt);body.pop("receipt_hash")
        receipt["receipt_hash"]=digest(body)
        state,report=apply_execution_receipts(load_seed_state(),[receipt])
        self.assertEqual(report["status"],"NO_NEW_REVIEWS")
        self.assertEqual(state["reviews"],[])

    def test_tampered_scheduler_execution_receipt_fails_closed(self):
        receipt=review_receipt()
        receipt["result"]["rights_state"]="LICENSED"
        with self.assertRaises(HunterProposalReviewError):
            apply_execution_receipts(load_seed_state(),[receipt])

    def test_rights_or_execution_upgrade_is_rejected_even_with_rehashed_receipt(self):
        for field,value in (
            ("reuse_authorized",True),
            ("implementation_authorized",True),
            ("code_execution_performed",True),
            ("downstream_mutation_performed",True),
        ):
            receipt=copy.deepcopy(review_receipt())
            receipt["result"][field]=value
            body=dict(receipt);body.pop("receipt_hash")
            receipt["receipt_hash"]=digest(body)
            with self.assertRaises(HunterProposalReviewError):
                apply_execution_receipts(load_seed_state(),[receipt])

    def test_source_receipt_cannot_self_attest_authority(self):
        receipt=review_receipt()
        receipt["authority_granted"]=True
        body=dict(receipt);body.pop("receipt_hash")
        receipt["receipt_hash"]=digest(body)
        with self.assertRaises(HunterProposalReviewError):
            apply_execution_receipts(load_seed_state(),[receipt])

    def test_source_receipt_cannot_persist_private_or_injected_evidence(self):
        for unsafe in ("email:buyer@example.com","safe\n::error title=PWNED::"):
            receipt=review_receipt()
            receipt["evidence_refs"].append(unsafe)
            body=dict(receipt);body.pop("receipt_hash")
            receipt["receipt_hash"]=digest(body)
            with self.assertRaises(HunterProposalReviewError):
                apply_execution_receipts(load_seed_state(),[receipt])

    def test_source_receipt_requires_bounded_projects_and_chronology(self):
        for field,value in (
            ("project_ids",["../../PRJ-002"]),
            ("finished_at","not-a-timestamp"),
            ("authority_granted","false"),
        ):
            receipt=review_receipt()
            receipt[field]=value
            body=dict(receipt);body.pop("receipt_hash")
            receipt["receipt_hash"]=digest(body)
            with self.assertRaises(HunterProposalReviewError):
                apply_execution_receipts(load_seed_state(),[receipt])

    def test_restored_state_rejects_timestamp_and_applied_id_projection_tampering(self):
        state,_=apply_execution_receipts(load_seed_state(),[review_receipt()])
        rolled=copy.deepcopy(state)
        rolled["updated_at"]="2026-09-27T07:19:59Z"
        with self.assertRaises(HunterProposalReviewError):
            validate_state(rolled)
        detached=copy.deepcopy(state)
        detached["applied_execution_ids"]=[]
        with self.assertRaises(HunterProposalReviewError):
            validate_state(detached)

    def test_restored_state_rejects_rehashed_semantically_unbound_evidence(self):
        state,_=apply_execution_receipts(load_seed_state(),[review_receipt()])
        poisoned=copy.deepcopy(state)
        row=poisoned["reviews"][0]
        row["evidence_refs"]=["hunter-proposal:HEXP-TEST-REVIEW"]
        body=dict(row);body.pop("review_hash")
        row["review_hash"]=digest(body)
        with self.assertRaises(HunterProposalReviewError):
            validate_state(poisoned)


if __name__=="__main__":
    unittest.main()
