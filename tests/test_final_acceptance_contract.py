import copy
import unittest

from acceptance.final_acceptance import (
    FinalAcceptanceError,
    bind_receipt,
    validate_bundle,
    validate_step21,
    validate_step22,
    validate_step23,
    validate_step24,
    validate_step25,
    _load_policy,
)


SHA = "a" * 40
H = "sha256:" + "b" * 64


def stage(stage_id, n):
    return {
        "stage_id": stage_id,
        "status": "PASS",
        "occurred_at": f"2026-09-30T14:{n:02d}:00Z",
        "run_ids": [1000 + n],
        "pr_numbers": [],
        "check_run_ids": [],
        "artifact_hashes": [H],
        "state_hashes": [H],
        "source_shas": [SHA],
    }


def step21():
    p = _load_policy()
    stages = [stage(x, i) for i, x in enumerate(p["step21_stages"])]
    by = {x["stage_id"]: x for x in stages}
    by["tests"]["check_run_ids"] = [500]
    by["independent_verifier"]["check_run_ids"] = [501]
    by["protected_promotion"]["pr_numbers"] = [77]
    return bind_receipt({
        "schema_version": "1.0.0",
        "step": 21,
        "status": "PASS",
        "exact_main_sha": SHA,
        "fixture_kind": "HARMLESS_BOUNDED",
        "bounded_authority": True,
        "protected_promotion": True,
        "hosted_verifier_app_id": 5121826,
        "canary_id": "CANARY-TEST-1",
        "candidate_pr_number": 77,
        "candidate_head_sha": SHA,
        "promotion_merge_sha": SHA,
        "foundation_check": {
            "check_run_id": 500, "name": "validate", "app_id": 15368,
            "head_sha": SHA, "status": "completed", "conclusion": "success",
        },
        "hosted_verifier_check": {
            "check_run_id": 501, "name": "portfolio-phase1-gate", "app_id": 5121826,
            "head_sha": SHA, "status": "completed", "conclusion": "success",
        },
        "stages": stages,
    })


def step22():
    p = _load_policy()
    stages = [stage(x, i) for i, x in enumerate(p["step22_stages"])]
    by = {x["stage_id"]: x for x in stages}
    by["repair_pr_opened"]["pr_numbers"] = [88]
    by["foundation_exact_head"]["check_run_ids"] = [601]
    by["hosted_verifier_gate"]["check_run_ids"] = [602]
    return bind_receipt({
        "schema_version": "1.0.0",
        "step": 22,
        "status": "PASS",
        "exact_main_sha": SHA,
        "fault_mechanism": "CONTROLLED_REPRODUCIBLE_FIXTURE",
        "production_main_damaged": False,
        "fault_reversible": True,
        "new_regression_added": True,
        "full_test_suite_passed": True,
        "repair_branch_prefix": "factory/auto-repair-",
        "hosted_verifier_app_id": 5121826,
        "human_verifier_required": False,
        "laptop_verifier_required": False,
        "repair_pr_actor_kind": "BOT",
        "repair_pr_number": 88,
        "repair_head_sha": SHA,
        "repair_merge_sha": SHA,
        "protected_merge": True,
        "foundation_check": {
            "check_run_id": 601, "name": "validate", "app_id": 15368,
            "head_sha": SHA, "status": "completed", "conclusion": "success",
        },
        "hosted_verifier_check": {
            "check_run_id": 602, "name": "portfolio-phase1-gate", "app_id": 5121826,
            "head_sha": SHA, "status": "completed", "conclusion": "success",
        },
        "stages": stages,
    })


def step23():
    p = _load_policy()
    runs = []
    run_id = 100
    run_minute = 1
    for workflow in p["step23"]["required_workflows"]:
        for _ in range(3):
            runs.append({
                "workflow": workflow,
                "event": "schedule",
                "classification": "SUCCESS",
                "classification_reason": "COMPLETED_SUCCESSFULLY",
                "superseding_run_id": None,
                "run_id": run_id,
                "head_sha": SHA,
                "created_at": f"2026-09-30T15:{run_minute:02d}:00Z",
                "artifact_hash": H,
            })
            run_id += 1
            run_minute += 1
    reducer_ids = [
        row["run_id"] for row in runs
        if row["workflow"] == "portfolio-state-reducer" and row["classification"] == "SUCCESS"
    ]
    return bind_receipt({
        "schema_version": "1.0.0",
        "step": 23,
        "status": "PASS",
        "exact_main_sha": SHA,
        "run_classification_policy": "EXPLICIT",
        "hash_traceability_pass": True,
        "dashboard_fresh": True,
        "dashboard_observed_at": "2026-09-30T15:40:00Z",
        "dashboard_hash": H,
        "window_started_at": "2026-09-30T15:00:00Z",
        "window_ended_at": "2026-09-30T18:00:00Z",
        "all_scheduled_runs_in_window_included": True,
        "runs": runs,
        "canonical_samples": [
            {"run_id": reducer_ids[0], "observed_at": "2026-09-30T15:00:00Z", "sequence": 10, "state_hash": H, "source_sha": SHA},
            {"run_id": reducer_ids[1], "observed_at": "2026-09-30T16:00:00Z", "sequence": 11, "state_hash": H, "source_sha": SHA},
            {"run_id": reducer_ids[2], "observed_at": "2026-09-30T17:00:00Z", "sequence": 12, "state_hash": H, "source_sha": SHA},
        ],
        "pending_events_start": 4,
        "pending_events_final": 0,
        "handler_execution_counts": {"REPAIR": 1, "TEST": 1, "VERIFICATION": 1},
        "hunter_substantive_work_count": 1,
    })


def step24():
    p = _load_policy()
    return bind_receipt({
        "schema_version": "1.0.0",
        "step": 24,
        "status": "PASS",
        "exact_main_sha": SHA,
        "independent_review": True,
        "reviewer_independence_group": "security-reviewer",
        "implementation_independence_group": "implementation-worker",
        "security_review_id": "portfolio-step24-least-privilege-v1",
        "security_review_status": "READY_FOR_INDEPENDENT_SIGNOFF",
        "security_review_hash": H,
        "security_review_exact_main_sha": SHA,
        "controls": [
            {"control_id": control, "status": "PASS", "observed_at": "2026-09-30T18:00:00Z", "evidence_refs": [f"evidence:{control}"]}
            for control in p["step24_controls"]
        ],
        "findings": [],
    })


def step25(prerequisite_hashes=None):
    return bind_receipt({
        "schema_version": "1.0.0",
        "step": 25,
        "status": "PASS",
        "exact_main_sha": SHA,
        "prerequisites": {"21": "COMPLETE", "22": "COMPLETE", "23": "COMPLETE", "24": "COMPLETE"},
        "prerequisite_receipt_hashes": prerequisite_hashes or {"21": H, "22": H, "23": H, "24": H},
        "canonical_history_preserved": True,
        "historical_evidence_preserved": True,
        "regression_suite_passed": True,
        "removed_paths": ["legacy/dead_adapter.py"],
        "closed_superseded_prs": [10],
        "coverage_evidence_refs": ["check:full-regression"],
    })


class FinalAcceptanceContractTests(unittest.TestCase):
    def test_valid_complete_bundle(self):
        receipts = {
            "21": step21(),
            "22": step22(),
            "23": step23(),
            "24": step24(),
        }
        bundle = {
            "schema_version": "1.0.0",
            "bundle_id": "portfolio-final-acceptance-evidence-v1",
            "step21": receipts["21"],
            "step22": receipts["22"],
            "step23": receipts["23"],
            "step24": receipts["24"],
            "step25": step25({key: value["receipt_hash"] for key, value in receipts.items()}),
        }
        self.assertEqual(set(validate_bundle(bundle).values()), {"COMPLETE"})

    def test_bundle_does_not_fake_missing_steps(self):
        result = validate_bundle({
            "schema_version": "1.0.0",
            "bundle_id": "portfolio-final-acceptance-evidence-v1",
        })
        self.assertTrue(all(value == "MISSING" for value in result.values()))

    def test_step21_requires_exact_chain(self):
        receipt = step21()
        body = copy.deepcopy(receipt)
        body["stages"] = body["stages"][:-1]
        receipt = bind_receipt(body)
        with self.assertRaises(FinalAcceptanceError):
            validate_step21(receipt)

    def test_step21_requires_hosted_verifier_trust_anchor(self):
        receipt = step21()
        receipt["hosted_verifier_app_id"] = 1
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "verifier App"):
            validate_step21(receipt)

    def test_step21_rejects_spoofed_hosted_verifier_app(self):
        receipt = step21()
        receipt["hosted_verifier_check"]["app_id"] = 15368
        with self.assertRaisesRegex(FinalAcceptanceError, "App identity mismatch"):
            validate_step21(bind_receipt(receipt))

    def test_step21_rejects_foundation_check_not_bound_to_tests_stage(self):
        receipt = step21()
        receipt["stages"][4]["check_run_ids"] = []
        with self.assertRaisesRegex(FinalAcceptanceError, "not bound to tests stage"):
            validate_step21(bind_receipt(receipt))

    def test_step22_rejects_human_or_laptop_dependency(self):
        receipt = step22()
        receipt["laptop_verifier_required"] = True
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "laptop"):
            validate_step22(receipt)

    def test_step22_rejects_hosted_check_on_other_head(self):
        receipt = step22()
        receipt["hosted_verifier_check"]["head_sha"] = "c" * 40
        with self.assertRaisesRegex(FinalAcceptanceError, "exact candidate head"):
            validate_step22(bind_receipt(receipt))

    def test_step22_rejects_destructive_fault(self):
        receipt = step22()
        receipt["production_main_damaged"] = True
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "damaged production main"):
            validate_step22(receipt)

    def test_step23_rejects_canonical_regression(self):
        receipt = step23()
        receipt["canonical_samples"][2]["sequence"] = 9
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "sequence regressed"):
            validate_step23(receipt)

    def test_step23_accepts_classified_coalescing_but_still_requires_three_successes(self):
        receipt = step23()
        receipt["runs"].append({
            "workflow": "portfolio-state-reducer",
            "event": "schedule",
            "classification": "CANCELLED_COALESCED",
            "classification_reason": "CONCURRENCY_COALESCED",
            "superseding_run_id": 100,
            "run_id": 99,
            "head_sha": SHA,
            "created_at": "2026-09-30T15:00:30Z",
            "artifact_hash": H,
        })
        validate_step23(bind_receipt(receipt))

    def test_step23_rejects_coalesced_run_pointing_to_other_workflow(self):
        receipt = step23()
        receipt["runs"].append({
            "workflow": "portfolio-state-reducer",
            "event": "schedule",
            "classification": "CANCELLED_COALESCED",
            "classification_reason": "CONCURRENCY_COALESCED",
            "superseding_run_id": next(
                row["run_id"] for row in receipt["runs"]
                if row["workflow"] == "runtime-hourly-sync"
            ),
            "run_id": 99,
            "head_sha": SHA,
            "created_at": "2026-09-30T15:00:30Z",
            "artifact_hash": H,
        })
        with self.assertRaisesRegex(FinalAcceptanceError, "another workflow"):
            validate_step23(bind_receipt(receipt))

    def test_step23_rejects_run_from_other_main(self):
        receipt = step23()
        receipt["runs"][0]["head_sha"] = "c" * 40
        with self.assertRaisesRegex(FinalAcceptanceError, "exact soak main"):
            validate_step23(bind_receipt(receipt))

    def test_step23_rejects_canonical_sample_from_other_main(self):
        receipt = step23()
        receipt["canonical_samples"][0]["source_sha"] = "c" * 40
        with self.assertRaisesRegex(FinalAcceptanceError, "canonical sample is not bound"):
            validate_step23(bind_receipt(receipt))

    def test_step23_rejects_incomplete_run_listing_claim(self):
        receipt = step23()
        receipt["all_scheduled_runs_in_window_included"] = False
        with self.assertRaisesRegex(FinalAcceptanceError, "listing is not proven complete"):
            validate_step23(bind_receipt(receipt))

    def test_step23_rejects_run_outside_soak_window(self):
        receipt = step23()
        receipt["runs"][0]["created_at"] = "2026-09-30T14:59:59Z"
        with self.assertRaisesRegex(FinalAcceptanceError, "outside soak window"):
            validate_step23(bind_receipt(receipt))

    def test_step23_rejects_dashboard_observation_outside_soak_window(self):
        receipt = step23()
        receipt["dashboard_observed_at"] = "2026-09-30T18:00:01Z"
        with self.assertRaisesRegex(FinalAcceptanceError, "dashboard observation is outside"):
            validate_step23(bind_receipt(receipt))

    def test_step23_rejects_heartbeat_only_hunter(self):
        receipt = step23()
        receipt["hunter_substantive_work_count"] = 0
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "no substantive work"):
            validate_step23(receipt)

    def test_step24_rejects_unresolved_critical(self):
        receipt = step24()
        receipt["findings"] = [{"severity": "CRITICAL", "status": "OPEN"}]
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "unresolved critical"):
            validate_step24(receipt)

    def test_step24_rejects_unresolved_high(self):
        receipt = step24()
        receipt["findings"] = [{"severity": "HIGH", "status": "OPEN"}]
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "unresolved high"):
            validate_step24(receipt)

    def test_step24_rejects_blocked_security_review(self):
        receipt = step24()
        receipt["security_review_status"] = "BLOCKED"
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "not ready for independent signoff"):
            validate_step24(receipt)

    def test_step24_rejects_security_review_from_other_main(self):
        receipt = step24()
        receipt["security_review_exact_main_sha"] = "c" * 40
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "not bound to exact main"):
            validate_step24(receipt)

    def test_step25_refuses_canonical_history_deletion(self):
        receipt = step25()
        receipt["removed_paths"] = ["state_journal/archive/canonical-seq-00000032.json.gz"]
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "protected canonical history"):
            validate_step25(receipt)

    def test_step25_refuses_immutable_audit_baseline_deletion(self):
        for path in ("docs/AUTOMATION_GAP_AUDIT.md", "docs/AUTOMATION_GAP_EVIDENCE.json"):
            receipt = step25()
            receipt["removed_paths"] = [path]
            with self.assertRaisesRegex(FinalAcceptanceError, "protected canonical history"):
                validate_step25(bind_receipt(receipt))

    def test_step25_refuses_archive_root_deletion_without_trailing_slash(self):
        receipt = step25()
        receipt["removed_paths"] = ["state_journal/archive"]
        with self.assertRaisesRegex(FinalAcceptanceError, "protected canonical history"):
            validate_step25(bind_receipt(receipt))

    def test_step25_refuses_premature_cleanup(self):
        receipt = step25()
        receipt["prerequisites"]["24"] = "BLOCKED"
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "before acceptance/security"):
            validate_step25(receipt)

    def test_bundle_rejects_step25_prerequisite_hash_claim_not_matching_receipt(self):
        receipts = {
            "21": step21(),
            "22": step22(),
            "23": step23(),
            "24": step24(),
        }
        wrong = {key: value["receipt_hash"] for key, value in receipts.items()}
        wrong["23"] = H
        bundle = {
            "schema_version": "1.0.0",
            "bundle_id": "portfolio-final-acceptance-evidence-v1",
            "step21": receipts["21"],
            "step22": receipts["22"],
            "step23": receipts["23"],
            "step24": receipts["24"],
            "step25": step25(wrong),
        }
        with self.assertRaisesRegex(FinalAcceptanceError, "Step 23 receipt hash mismatch"):
            validate_bundle(bundle)

    def test_step21_rejects_candidate_head_not_bound_to_verifier(self):
        receipt = step21()
        receipt["candidate_head_sha"] = "c" * 40
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "not bound to candidate head"):
            validate_step21(receipt)

    def test_step22_rejects_check_not_bound_to_repair_head(self):
        receipt = step22()
        receipt["repair_head_sha"] = "c" * 40
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "Foundation check is not bound"):
            validate_step22(receipt)

    def test_step23_rejects_duplicate_canonical_cycle_sample(self):
        receipt = step23()
        receipt["canonical_samples"][1]["run_id"] = receipt["canonical_samples"][0]["run_id"]
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "duplicated a reducer cycle"):
            validate_step23(receipt)

    def test_step23_rejects_coalesced_run_without_evidenced_successor(self):
        receipt = step23()
        receipt["runs"].append({
            "workflow": "portfolio-state-reducer",
            "event": "schedule",
            "classification": "CANCELLED_COALESCED",
            "classification_reason": "CONCURRENCY_COALESCED",
            "superseding_run_id": 999999,
            "run_id": 99,
            "head_sha": SHA,
            "created_at": "2026-09-30T15:00:30Z",
            "artifact_hash": H,
        })
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "points outside soak evidence"):
            validate_step23(receipt)

    def test_step24_rejects_same_independence_group(self):
        receipt = step24()
        receipt["reviewer_independence_group"] = receipt["implementation_independence_group"]
        receipt = bind_receipt(receipt)
        with self.assertRaisesRegex(FinalAcceptanceError, "not independent"):
            validate_step24(receipt)


if __name__ == "__main__":
    unittest.main()
