import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from truth.truth_adapter import (
    TruthIntegrationError, load_pin, project_receipt, project_truth_state,
    validate_pin, validate_source_receipt_ref, validate_upstream_receipt,
    verify_source_identity,
)

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
    return resign_receipt({
        "claim_id":"claim-1",
        "claim_hash":H,
        "verdict":verdict,
        "evaluated_at":200.0,
        "findings":[finding(status)],
        "evidence_set_hash":"b"*64,
        "receipt_hash":"",
    })

def receipt_ref(value):
    return "ai-business-os://truth/receipt/sha256/"+value["receipt_hash"]

class TruthIntegrationTests(unittest.TestCase):
    def test_pin_is_exact_and_source_is_not_copied(self):
        pin=load_pin()
        self.assertEqual(pin["source_revision"],"c6276c80828d2632d5fee37cdaaf65f1d5b36427")
        self.assertEqual(pin["source_blob_sha"],"9b3eaa9412ece784c05e9c93dfcea04e1ec96105")
        self.assertFalse(pin["copied_source_code"])
        self.assertEqual(pin["receipt_namespace"],{
            "scheme":"ai-business-os",
            "authority":"truth",
            "path_prefix":"/receipt",
            "digest_algorithm":"sha256",
            "max_length":512,
        })
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

    def test_evidence_id_cannot_support_and_contradict_same_finding(self):
        r=receipt("PROVEN","SATISFIED")
        r["findings"][0]["contradicting_evidence_ids"]=["support"]
        resign_receipt(r)
        with self.assertRaisesRegex(TruthIntegrationError,"cannot span lineage buckets"):
            project_truth_state(r)

    def test_repeated_support_does_not_change_verdict_without_upstream_proof(self):
        r=receipt("NOT_PROVEN","INSUFFICIENT_INDEPENDENCE")
        r["findings"][0]["supporting_evidence_ids"]=["a","b","c","d","e"]
        resign_receipt(r)
        validate_upstream_receipt(r)
        self.assertEqual(project_truth_state(r),"UNKNOWN")

    def test_non_finite_or_boolean_evaluated_at_is_invalid(self):
        for invalid in (True,False,float("nan"),float("inf"),float("-inf")):
            with self.subTest(evaluated_at=invalid):
                r=receipt("PROVEN","SATISFIED")
                r["evaluated_at"]=invalid
                resign_receipt(r)
                with self.assertRaisesRegex(TruthIntegrationError,"finite numeric"):
                    project_truth_state(r)

    def test_oversized_signed_integer_timestamps_reject_with_stable_error(self):
        # Signed JSON remains hash-valid; arbitrary-size timestamps must not
        # leak a raw OverflowError or lose numeric identity by float coercion.
        for invalid in (10**309,-(10**309),2**53,-(2**53)):
            with self.subTest(value=invalid):
                row=receipt("PROVEN","SATISFIED")
                row["evaluated_at"]=invalid
                resign_receipt(row)
                with self.assertRaisesRegex(TruthIntegrationError,"finite numeric"):
                    project_truth_state(row)
        for valid in (0,1,-1,1700000000,(2**53)-1,-((2**53)-1)):
            with self.subTest(valid=valid):
                row=receipt("PROVEN","SATISFIED")
                row["evaluated_at"]=valid
                resign_receipt(row)
                self.assertEqual(project_truth_state(row),"VERIFIED")
                self.assertEqual(row["evaluated_at"],valid)

    def test_tampered_receipt_body_fails_closed_even_when_shape_is_valid(self):
        r=receipt("PROVEN","SATISFIED")
        original_hash=r["receipt_hash"]
        r["findings"][0]["reason"]="tampered after upstream evaluation"
        self.assertEqual(r["receipt_hash"],original_hash)
        with self.assertRaisesRegex(TruthIntegrationError,"does not bind"):
            project_truth_state(r)

    def test_model_confidence_field_cannot_upgrade_receipt(self):
        r=receipt("NOT_PROVEN","INSUFFICIENT_SUPPORT")
        r["model_confidence"]=0.999999
        self.assertEqual(project_truth_state(r),"UNKNOWN")

    def test_projection_binds_upstream_provenance(self):
        pin=load_pin()
        source=receipt("PROVEN","SATISFIED")
        p=project_receipt(
            source,
            project_id="PRJ-001",
            source_revision=pin["source_revision"],
            source_blob_sha=pin["source_blob_sha"],
            source_receipt_ref=receipt_ref(source),
        )
        self.assertEqual(p["truth_state"],"VERIFIED")
        self.assertEqual(p["upstream_source"]["revision"],pin["source_revision"])
        self.assertEqual(p["upstream_source"]["blob_sha"],pin["source_blob_sha"])
        self.assertTrue(p["projection_hash"].startswith("sha256:"))

    def test_projection_hash_changes_when_source_receipt_changes(self):
        pin=load_pin()
        first=receipt("PROVEN","SATISFIED")
        second=receipt("PROVEN","SATISFIED")
        second["claim_id"]="claim-2"
        resign_receipt(second)
        a=project_receipt(first,project_id="PRJ-001",source_revision=pin["source_revision"],source_blob_sha=pin["source_blob_sha"],source_receipt_ref=receipt_ref(first))
        b=project_receipt(second,project_id="PRJ-001",source_revision=pin["source_revision"],source_blob_sha=pin["source_blob_sha"],source_receipt_ref=receipt_ref(second))
        self.assertNotEqual(a["projection_hash"],b["projection_hash"])

    def test_receipt_reference_namespace_and_digest_fail_closed(self):
        source=receipt("PROVEN","SATISFIED")
        expected="sha256:"+source["receipt_hash"]
        valid=receipt_ref(source)
        self.assertEqual(validate_source_receipt_ref(valid,expected_receipt_hash=expected),valid)
        invalid=(
            None,"","   ",42,
            "javascript://truth/receipt/sha256/"+source["receipt_hash"],
            "file://localhost/etc/sha256/"+source["receipt_hash"],
            "https://127.0.0.1/receipt/sha256/"+source["receipt_hash"],
            valid+"?token=SYNTHETIC",
            valid+"#fragment",
            valid+"\nRECOVERY-INJECTION",
            "AI-business-os://truth/receipt/sha256/"+source["receipt_hash"],
            "ai-business-os://truth/other/sha256/"+source["receipt_hash"],
            "ai-business-os://truth/receipt/sha256/"+"0"*64,
        )
        for value in invalid:
            with self.subTest(value=str(value)[:80]):
                with self.assertRaises(TruthIntegrationError):
                    validate_source_receipt_ref(value,expected_receipt_hash=expected)

    def test_optional_stale_finding_does_not_override_required_satisfied(self):
        r=receipt("PROVEN","SATISFIED")
        r["findings"].append(finding("STALE",required=False))
        resign_receipt(r)
        self.assertEqual(project_truth_state(r),"VERIFIED")

if __name__=="__main__":
    unittest.main()
