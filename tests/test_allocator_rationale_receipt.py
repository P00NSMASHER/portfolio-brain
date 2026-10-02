import copy
import unittest

from allocator.portfolio_allocator import build_allocation_snapshot
from allocator.rationale_receipt import (
    AllocationRationaleReceiptError,
    build_rationale_receipt,
)


class AllocationRationaleReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = build_allocation_snapshot(generated_at="2026-10-02T18:26:08Z")
        cls.plan = next(
            plan for plan in snapshot["plans"]
            if plan["resource_type"] == "RESEARCH"
        )

    def test_receipt_binds_to_existing_plan_and_preserves_evidence(self):
        receipt = build_rationale_receipt(
            self.plan,
            generated_at="2026-10-02T18:26:08Z",
            dependency_refs=["PRJ-009", "PRJ-008", "PRJ-009"],
        )
        self.assertEqual(receipt["source_plan_hash"], self.plan["plan_hash"])
        self.assertEqual(receipt["dependency_refs"], ["PRJ-008", "PRJ-009"])
        self.assertFalse(receipt["execution_authority_granted"])
        self.assertTrue(receipt["rationale_entries"])
        expected = {
            ref
            for recommendation in self.plan["recommendations"]
            for ref in recommendation["evidence_refs"]
        }
        actual = {
            ref
            for entry in receipt["rationale_entries"]
            for ref in entry["evidence_refs"]
        }
        self.assertEqual(actual, expected)

    def test_receipt_is_deterministic_and_dependency_sensitive(self):
        first = build_rationale_receipt(
            self.plan,
            generated_at="2026-10-02T18:26:08Z",
            dependency_refs=["PRJ-008"],
        )
        again = build_rationale_receipt(
            self.plan,
            generated_at="2026-10-02T18:26:08Z",
            dependency_refs=["PRJ-008"],
        )
        changed = build_rationale_receipt(
            self.plan,
            generated_at="2026-10-02T18:26:08Z",
            dependency_refs=["PRJ-008", "PRJ-009"],
        )
        self.assertEqual(first["receipt_hash"], again["receipt_hash"])
        self.assertNotEqual(first["receipt_hash"], changed["receipt_hash"])

    def test_receipt_never_accepts_an_opaque_score(self):
        plan = copy.deepcopy(self.plan)
        plan["score"] = 0.99
        with self.assertRaisesRegex(AllocationRationaleReceiptError, "opaque score"):
            build_rationale_receipt(
                plan,
                generated_at="2026-10-02T18:26:08Z",
            )


if __name__ == "__main__":
    unittest.main()
