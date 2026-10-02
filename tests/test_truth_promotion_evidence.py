import copy
import hashlib
import json
import math
import unittest

from events.validate_event import validate_evidence
from truth.promotion_evidence import PromotionEvidenceError, promoted_fact_evidence
from truth.truth_adapter import load_pin

H = "a" * 64

def resign_receipt(value):
    payload = {
        "claim_id": value["claim_id"],
        "claim_hash": value["claim_hash"],
        "verdict": value["verdict"],
        "evaluated_at": value["evaluated_at"],
        "findings": value["findings"],
        "evidence_set_hash": value["evidence_set_hash"],
    }
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    value["receipt_hash"] = hashlib.sha256(raw).hexdigest()
    return value

def finding(status, support_ids=None):
    return {
        "key": "k",
        "required": True,
        "status": status,
        "reason": "reason",
        "supporting_evidence_ids": list(support_ids or []),
        "contradicting_evidence_ids": ["contra"] if status in {"CONFLICTED", "CONTRADICTED"} else [],
        "stale_evidence_ids": ["stale"] if status == "STALE" else [],
        "inadmissible_evidence_ids": [],
    }

def receipt(verdict="PROVEN", status="SATISFIED", support_ids=None, evaluated_at=200.0):
    return resign_receipt({
        "claim_id": "claim-1",
        "claim_hash": H,
        "verdict": verdict,
        "evaluated_at": evaluated_at,
        "findings": [finding(status, support_ids or ["upstream-a", "upstream-b"])],
        "evidence_set_hash": "b" * 64,
        "receipt_hash": "",
    })

def emit(value, bindings=None):
    pin = load_pin()
    return promoted_fact_evidence(
        value,
        project_id="PRJ-001",
        source_revision=pin["source_revision"],
        source_blob_sha=pin["source_blob_sha"],
        source_receipt_ref="ai-business-os://truth/receipt/1",
        basis_bindings=bindings or [
            {"upstream_evidence_id": "upstream-a", "portfolio_evidence_id": "EVD-BASIS-00000001"},
            {"upstream_evidence_id": "upstream-b", "portfolio_evidence_id": "EVD-BASIS-00000002"},
        ],
    )

class TruthPromotionEvidenceTests(unittest.TestCase):
    def test_promoted_fact_conforms_to_existing_evidence_schema(self):
        row = emit(receipt())
        validate_evidence(row)
        self.assertEqual(row["evidence_type"], "DETERMINISTIC_DERIVATION")
        self.assertEqual(row["evidence_state"], "VERIFIED")
        self.assertEqual(row["verification"]["method"], "INDEPENDENT_VERIFIER")
        self.assertEqual(
            row["verification"]["basis_evidence_ids"],
            ["EVD-BASIS-00000001", "EVD-BASIS-00000002"],
        )
        self.assertEqual(row["actor"]["actor_id"], "portfolio-truth-promotion-adapter")
        self.assertNotEqual(row["verification"]["verifier_actor_id"], row["actor"]["actor_id"])
        self.assertEqual(row["source"]["retrieved_at"], "1970-01-01T00:03:20Z")
        self.assertTrue(row["evidence_hash"].startswith("sha256:"))

    def test_binding_order_does_not_change_evidence_identity(self):
        value = receipt()
        bindings = [
            {"upstream_evidence_id": "upstream-b", "portfolio_evidence_id": "EVD-BASIS-00000002"},
            {"upstream_evidence_id": "upstream-a", "portfolio_evidence_id": "EVD-BASIS-00000001"},
        ]
        self.assertEqual(emit(value), emit(copy.deepcopy(value), bindings))

    def test_hold_decision_cannot_emit_verified_evidence(self):
        with self.assertRaisesRegex(PromotionEvidenceError, "only PROMOTE"):
            emit(receipt("NOT_PROVEN", "STALE", ["upstream-a", "upstream-b"]))

    def test_basis_mapping_must_exactly_cover_required_upstream_support(self):
        with self.assertRaisesRegex(PromotionEvidenceError, "exactly cover"):
            emit(receipt(), [
                {"upstream_evidence_id": "upstream-a", "portfolio_evidence_id": "EVD-BASIS-00000001"},
            ])
        with self.assertRaisesRegex(PromotionEvidenceError, "exactly cover"):
            emit(receipt(), [
                {"upstream_evidence_id": "upstream-a", "portfolio_evidence_id": "EVD-BASIS-00000001"},
                {"upstream_evidence_id": "upstream-b", "portfolio_evidence_id": "EVD-BASIS-00000002"},
                {"upstream_evidence_id": "upstream-c", "portfolio_evidence_id": "EVD-BASIS-00000003"},
            ])

    def test_duplicate_or_invalid_portfolio_basis_ids_fail_closed(self):
        with self.assertRaisesRegex(PromotionEvidenceError, "duplicate portfolio"):
            emit(receipt(), [
                {"upstream_evidence_id": "upstream-a", "portfolio_evidence_id": "EVD-BASIS-00000001"},
                {"upstream_evidence_id": "upstream-b", "portfolio_evidence_id": "EVD-BASIS-00000001"},
            ])
        with self.assertRaisesRegex(PromotionEvidenceError, "must satisfy EVIDENCE_SCHEMA"):
            emit(receipt(), [
                {"upstream_evidence_id": "upstream-a", "portfolio_evidence_id": "not-an-evidence-id"},
                {"upstream_evidence_id": "upstream-b", "portfolio_evidence_id": "EVD-BASIS-00000002"},
            ])

    def test_promotion_requires_explicit_upstream_support_identities(self):
        value = receipt(support_ids=[])
        value["findings"][0]["supporting_evidence_ids"] = []
        resign_receipt(value)
        with self.assertRaisesRegex(PromotionEvidenceError, "explicit upstream support"):
            emit(value, [])

    def test_nonfinite_evaluation_time_cannot_become_schema_evidence(self):
        value = receipt(evaluated_at=math.nan)
        with self.assertRaisesRegex(PromotionEvidenceError, "finite and non-negative"):
            emit(value)

if __name__ == "__main__":
    unittest.main()
