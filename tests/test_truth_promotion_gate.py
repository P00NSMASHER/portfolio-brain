import copy
import hashlib
import json
import unittest

from truth.promotion_gate import load_contract, promotion_decision
from truth.truth_adapter import TruthIntegrationError, load_pin

H="a"*64

def resign_receipt(value):
    payload={
        "claim_id":value["claim_id"],
        "claim_hash":value["claim_hash"],
        "verdict":value["verdict"],
        "evaluated_at":value["evaluated_at"],
        "findings":value["findings"],
        "evidence_set_hash":value["evidence_set_hash"],
    }
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    value["receipt_hash"]=hashlib.sha256(raw).hexdigest()
    return value

def finding(status):
    return {
        "key":"k",
        "required":True,
        "status":status,
        "reason":"reason",
        "supporting_evidence_ids":["support"] if status in {"SATISFIED","CONFLICTED"} else [],
        "contradicting_evidence_ids":["contra"] if status in {"CONFLICTED","CONTRADICTED"} else [],
        "stale_evidence_ids":["stale"] if status=="STALE" else [],
        "inadmissible_evidence_ids":["inad"] if status=="INADMISSIBLE" else [],
    }

def receipt(verdict,status):
    return resign_receipt({
        "claim_id":"claim-1",
        "claim_hash":H,
        "verdict":verdict,
        "evaluated_at":200.0,
        "findings":[finding(status)],
        "evidence_set_hash":"b"*64,
        "receipt_hash":"",
    })

def decide(value, *, source_revision=None, source_blob_sha=None):
    pin=load_pin()
    return promotion_decision(
        value,
        project_id="PRJ-001",
        source_revision=source_revision or pin["source_revision"],
        source_blob_sha=source_blob_sha or pin["source_blob_sha"],
        source_receipt_ref="ai-business-os://truth/receipt/1",
    )

class TruthPromotionGateTests(unittest.TestCase):
    def test_contract_is_fail_closed_and_grants_no_authority(self):
        contract=load_contract()
        self.assertEqual(contract["promotable_truth_states"],["VERIFIED"])
        self.assertEqual(contract["held_truth_states"],["UNKNOWN","STALE","CONTRADICTED"])
        self.assertTrue(contract["requires_exact_pinned_source_identity"])
        self.assertEqual(contract["authority_change"],"NONE")

    def test_verified_projection_is_promotable(self):
        decision=decide(receipt("PROVEN","SATISFIED"))
        self.assertEqual(decision["promotion_decision"],"PROMOTE")
        self.assertTrue(decision["trusted_fact_eligible"])
        self.assertEqual(decision["reason_code"],"PINNED_TRUTH_ENGINE_VERIFIED")
        self.assertEqual(decision["authority_change"],"NONE")
        self.assertTrue(decision["projection_hash"].startswith("sha256:"))
        self.assertTrue(decision["promotion_hash"].startswith("sha256:"))

    def test_unknown_stale_and_contradicted_truth_are_held(self):
        cases=[
            ("NOT_PROVEN","INSUFFICIENT_SUPPORT","TRUTH_UNKNOWN_NOT_PROOF"),
            ("NOT_PROVEN","STALE","TRUTH_STALE_NOT_PROOF"),
            ("CONTESTED","CONFLICTED","TRUTH_CONTRADICTED_NOT_PROOF"),
        ]
        for verdict,status,reason in cases:
            with self.subTest(status=status):
                decision=decide(receipt(verdict,status))
                self.assertEqual(decision["promotion_decision"],"HOLD")
                self.assertFalse(decision["trusted_fact_eligible"])
                self.assertEqual(decision["reason_code"],reason)

    def test_tampered_upstream_receipt_cannot_reach_promotion(self):
        value=receipt("PROVEN","SATISFIED")
        value["findings"][0]["reason"]="tampered after upstream evaluation"
        with self.assertRaisesRegex(TruthIntegrationError,"does not bind"):
            decide(value)

    def test_source_revision_drift_cannot_reach_promotion(self):
        with self.assertRaisesRegex(TruthIntegrationError,"source revision drifted"):
            decide(receipt("PROVEN","SATISFIED"),source_revision="0"*40)

    def test_source_blob_drift_cannot_reach_promotion(self):
        with self.assertRaisesRegex(TruthIntegrationError,"source blob mismatch"):
            decide(receipt("PROVEN","SATISFIED"),source_blob_sha="0"*40)

    def test_promotion_receipt_is_deterministic(self):
        value=receipt("PROVEN","SATISFIED")
        self.assertEqual(decide(value),decide(copy.deepcopy(value)))

if __name__=="__main__":
    unittest.main()
