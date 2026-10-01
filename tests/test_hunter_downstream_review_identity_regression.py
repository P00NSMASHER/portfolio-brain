import unittest

from hunting.downstream_lifecycle import (
    APPROVAL_CODE,
    acceptance_source_ref,
    apply_reviews_and_acceptances,
    load_seed_state,
)
from hunting.proposal_review_state import digest
from hunting.steps10_12_live_acceptance import controlled_review, controlled_review_state
from repair.autonomous_repair import request_from_hunter_acceptance
from scheduler.autonomous_scheduler import policy as scheduler_policy


def refreshed_review_state(review):
    refreshed = dict(review)
    refreshed["review_id"] = "HREV-REFRESHED-IDENTITY"
    refreshed["source_execution_id"] = "WEXEC-REFRESHED-IDENTITY"
    refreshed["source_execution_receipt_hash"] = "sha256:" + "e" * 64
    body = dict(refreshed)
    body.pop("review_hash")
    refreshed["review_hash"] = digest(body)
    return controlled_review_state(refreshed)


def approval_ledger(review):
    return {
        "schema_version": "1.0.0",
        "ledger_id": "portfolio-owner-approvals",
        "approvals": [{
            "approval_id": "OAPR-CONTROLLED-HUNTER",
            "source_ref": acceptance_source_ref(review),
            "project_ids": ["PRJ-000"],
            "approval_requirements": [APPROVAL_CODE],
            "approved_by": "P00NSMASHER",
            "approved_at": "2026-09-30T14:05:00Z",
            "status": "ACTIVE",
            "reason_hash": "sha256:" + "d" * 64,
        }],
    }


class HunterDownstreamReviewIdentityRegressionTests(unittest.TestCase):
    def test_refreshed_review_does_not_break_existing_accepted_implementation(self):
        review = controlled_review()
        reviews = controlled_review_state(review)
        approvals = approval_ledger(review)
        base_sha = "d" * 40
        milestone = scheduler_policy()["external_milestones"][0]
        accepted, _ = apply_reviews_and_acceptances(
            load_seed_state(), reviews, approvals,
            base_sha=base_sha,
            current_repository="P00NSMASHER/portfolio-brain",
            source_branch="main",
            current_external_milestone=milestone,
        )
        acceptance = accepted["records"][0]["acceptance_receipt"]
        request = request_from_hunter_acceptance(
            {"work_type": "IMPLEMENTATION", "source_ref": acceptance["acceptance_id"]},
            accepted,
            base_sha=base_sha,
        )
        head = "a" * 40
        fingerprint = request["fingerprint"]
        evidence = {
            "status": "REPAIR_PR_FOUND",
            "source_ref": acceptance["acceptance_id"],
            "factory_work_id": (
                "AUTO-REPAIR-" + fingerprint.split(":", 1)[1][:16].upper() + "-1"
            ),
            "request_fingerprint": fingerprint,
            "base_sha": base_sha,
            "candidate_sha": head,
            "pr_number": 321,
            "head_sha": head,
            "head_ref": "factory/auto-repair-controlled/attempt-1",
            "evidence_refs": ["repair-pr:321"],
            "observed_at": "2026-09-30T14:06:00Z",
        }

        reconciled, report = apply_reviews_and_acceptances(
            accepted, refreshed_review_state(review), approvals,
            base_sha=base_sha,
            current_repository="P00NSMASHER/portfolio-brain",
            source_branch="main",
            current_external_milestone=milestone,
            reconcile_implementation=True,
            implementation_evidence_provider=lambda _source: evidence,
            observed_at="2026-09-30T14:06:00Z",
        )

        record = reconciled["records"][0]
        self.assertEqual(record["review_hash"], review["review_hash"])
        self.assertEqual(record["lifecycle"]["current_stage"], "IMPLEMENTED")
        self.assertEqual([row["stage"] for row in report["implementation_advancements"]], ["IMPLEMENTED"])

    def test_missing_original_review_does_not_rebind_reviewed_lifecycle(self):
        review = controlled_review()
        base_sha = "d" * 40
        milestone = scheduler_policy()["external_milestones"][0]
        reviewed, _ = apply_reviews_and_acceptances(
            load_seed_state(),
            controlled_review_state(review),
            {"schema_version": "1.0.0", "ledger_id": "portfolio-owner-approvals", "approvals": []},
            base_sha=base_sha,
            current_repository="P00NSMASHER/portfolio-brain",
            source_branch="main",
            current_external_milestone=milestone,
        )
        updated, report = apply_reviews_and_acceptances(
            reviewed,
            refreshed_review_state(review),
            approval_ledger(review),
            base_sha=base_sha,
            current_repository="P00NSMASHER/portfolio-brain",
            source_branch="main",
            current_external_milestone=milestone,
        )

        self.assertEqual(updated["records"][0]["review_hash"], review["review_hash"])
        self.assertEqual(updated["records"][0]["lifecycle"]["current_stage"], "REVIEWED")
        self.assertEqual(report["accepted_work"], [])


if __name__ == "__main__":
    unittest.main()
