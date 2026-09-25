import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from truth.truth_adapter import (
    TruthIntegrationError, load_pin, project_receipt, project_truth_state,
    validate_pin, validate_upstream_receipt, verify_source_identity,
)

H="a"*64

def finding(status, *, required=True):
    return {
        "key":"k",
        "required":required,
        "status":status,
        "reason":"reason",
        "supporting_evidence_ids":["support"] if status in {"SATISFIED","CONFLICTED"} else [],
        "contradicting_evidence_ids":["contra"] if status in {"CONFLICTED","CONTRADICTED"} else [],
        "stale_evidence_ids":["stale"] if status=="STALE" else [],
        "inadmissible_evidence_ids":["inad"] if status=="INADMISSIBLE" else [],
    }

def receipt(verdict,status):
    return {
        "claim_id":"claim-1",
        "claim_hash":H,
        "verdict":verdict,
        "evaluated_at":200.0,
        "findings":[finding(status)],
        "evidence_set_hash":"b"*64,
        "receipt_hash":"c"*64,
    }

class TruthIntegrationTests(unittest.TestCase):
    def test_pin_is_exact_and_source_is_not_copied(self):
        pin=load_pin()
        self.assertEqual(pin["source_revision"],"9533769a669429d2553302df6068b4b1f8099e89")
        self.assertEqual(pin["source_blob_sha"],"9b3eaa9412ece784c05e9c93dfcea04e1ec96105")
        self.assertFalse(pin["copied_source_code"])
        validate_pin(pin)

    def test_source_revision_drift_fails_closed(self):
        pin=load_pin()
        with self.assertRaises(TruthIntegrationError):
            verify_source_identity(pin,source_revision="0"*40,source_blob_sha=pin["source_blob_sha"])

    def test_source_blob_drift_fails_closed(self):
        pin=load_pin()
        with self.assertRaises(TruthIntegrationError):
            verify_source_identity(pin,source_revision=pin["source_revision"],source_blob_sha="0"*40)

    def test_proven_maps_to_verified_only_when_required_findings_satisfied(self):
        self.assertEqual(project_truth_state(receipt("PROVEN","SATISFIED")),"VERIFIED")
        bad=receipt("PROVEN","MISSING")
        with self.assertRaises(TruthIntegrationError):
            project_truth_state(bad)

    def test_not_proven_is_unknown_not_false(self):
        self.assertEqual(project_truth_state(receipt("NOT_PROVEN","INSUFFICIENT_SUPPORT")),"UNKNOWN")
        self.assertEqual(project_truth_state(receipt("NOT_PROVEN","INADMISSIBLE")),"UNKNOWN")

    def test_unknown_requires_missing_required_evidence(self):
        self.assertEqual(project_truth_state(receipt("UNKNOWN","MISSING")),"UNKNOWN")
        with self.assertRaises(TruthIntegrationError):
            project_truth_state(receipt("UNKNOWN","INADMISSIBLE"))

    def test_stale_is_preserved(self):
        self.assertEqual(project_truth_state(receipt("NOT_PROVEN","STALE")),"STALE")

    def test_contradiction_is_preserved(self):
        self.assertEqual(project_truth_state(receipt("CONTESTED","CONFLICTED")),"CONTRADICTED")
        self.assertEqual(project_truth_state(receipt("CONTESTED","CONTRADICTED")),"CONTRADICTED")

    def test_repeated_support_does_not_change_verdict_without_upstream_proof(self):
        r=receipt("NOT_PROVEN","INSUFFICIENT_INDEPENDENCE")
        r["findings"][0]["supporting_evidence_ids"]=["a","b","c","d","e"]
        validate_upstream_receipt(r)
        self.assertEqual(project_truth_state(r),"UNKNOWN")

    def test_model_confidence_field_cannot_upgrade_receipt(self):
        r=receipt("NOT_PROVEN","INSUFFICIENT_SUPPORT")
        r["model_confidence"]=0.999999
        self.assertEqual(project_truth_state(r),"UNKNOWN")

    def test_projection_binds_upstream_provenance(self):
        pin=load_pin()
        p=project_receipt(
            receipt("PROVEN","SATISFIED"),
            project_id="PRJ-001",
            source_revision=pin["source_revision"],
            source_blob_sha=pin["source_blob_sha"],
            source_receipt_ref="ai-business-os://truth/receipt/1",
        )
        self.assertEqual(p["truth_state"],"VERIFIED")
        self.assertEqual(p["upstream_source"]["revision"],pin["source_revision"])
        self.assertEqual(p["upstream_source"]["blob_sha"],pin["source_blob_sha"])
        self.assertTrue(p["projection_hash"].startswith("sha256:"))

    def test_projection_hash_changes_when_source_receipt_changes(self):
        pin=load_pin()
        a=project_receipt(receipt("PROVEN","SATISFIED"),project_id="PRJ-001",source_revision=pin["source_revision"],source_blob_sha=pin["source_blob_sha"],source_receipt_ref="receipt/1")
        b=project_receipt(receipt("PROVEN","SATISFIED"),project_id="PRJ-001",source_revision=pin["source_revision"],source_blob_sha=pin["source_blob_sha"],source_receipt_ref="receipt/2")
        self.assertNotEqual(a["projection_hash"],b["projection_hash"])

    def test_optional_stale_finding_does_not_override_required_satisfied(self):
        r=receipt("PROVEN","SATISFIED")
        r["findings"].append(finding("STALE",required=False))
        self.assertEqual(project_truth_state(r),"VERIFIED")

if __name__=="__main__":
    unittest.main()
