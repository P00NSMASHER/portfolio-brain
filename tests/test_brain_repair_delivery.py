"""Exact-commit independent release assessment, no bypassing merge gates."""
from __future__ import annotations
import copy
import unittest

from brain.core import BrainError
from brain.repair_delivery import evaluate_delivery
from brain.repair_patch_executor import generate
from test_brain_repair_patch_executor import FIXTURE, request, PATH, REPO

BASE = "a" * 40
HEAD = "b" * 40
MERGE = "c" * 40


def fixture():
    patch = generate(request(), FIXTURE.encode())
    pr = {
        "number": 72, "state": "open", "merged": False, "draft": False,
        "mergeable": True, "mergeable_state": "clean",
        "merge_commit_sha": None,
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
        "base": {"ref": "main", "sha": BASE, "repo": {"full_name": REPO}},
    }
    files = {
        patch["source_path"]: patch["changed_sha256"],
        patch["test_path"]: patch["test_sha256"],
    }
    names = ("test", "browser", "manufacturing", "pilot", "candidate-build")
    checks = {
        "total_count": 6,
        "check_runs": [
            {"id": i+1, "name": name, "head_sha": HEAD,
             "app": {"id": 15368}, "status": "completed",
             "conclusion": "success"}
            for i, name in enumerate(names)
        ] + [
            {"id": 7, "name": "portfolio-phase1-gate", "head_sha": HEAD,
             "app": {"id": 5121826}, "status": "completed",
             "conclusion": "success"},
        ],
    }
    checks["total_count"] = len(checks["check_runs"])
    return patch, pr, files, checks


def evaluate(patch, pr, files, checks, **kwargs):
    return evaluate_delivery(patch, pr, files, checks,
                             original_source_bytes=FIXTURE.encode(), **kwargs)


class ClosedLoopDeliveryTests(unittest.TestCase):
    def test_green_exact_source_and_separate_gate_offer_sha_guarded_owner_request(self):
        patch, pr, files, checks = fixture()
        result = evaluate(patch, pr, files, checks)
        self.assertEqual(result["status"],
                         "SAFE_SOURCE_VERIFIED_FOR_GUARDED_OWNER_ACTION")
        self.assertEqual(result["merge_request"], {
            "repository": REPO, "pr_number": 72,
            "expected_head_sha": HEAD, "merge_method": "squash",
        })
        self.assertTrue(result["independent_gate_verified"])
        self.assertFalse(result["merge_or_release_authority_granted"])
        self.assertFalse(result["technical_main_verified"])
        self.assertFalse(result["actual_customer_value_verified"])

    def test_missing_independent_app_or_wrong_app_cannot_self_certify(self):
        for change in ("remove", "wrong_app", "wrong_conclusion", "wrong_sha"):
            patch, pr, files, checks = fixture()
            if change == "remove":
                checks["check_runs"].pop()
                checks["total_count"] -= 1
            elif change == "wrong_app":
                checks["check_runs"][-1]["app"]["id"] = 15368
            elif change == "wrong_conclusion":
                checks["check_runs"][-1]["conclusion"] = "failure"
            elif change == "wrong_sha":
                checks["check_runs"][-1]["head_sha"] = BASE
            with self.subTest(change=change):
                if change == "wrong_sha":
                    with self.assertRaises(BrainError):
                        evaluate(patch, pr, files, checks)
                else:
                    result = evaluate(patch, pr, files, checks)
                    self.assertEqual(result["status"], "HOLD")
                    self.assertIsNone(result["merge_request"])

    def test_draft_or_conflicted_branch_is_not_eligible(self):
        for key, val in (
            ("draft", True), ("mergeable", False),
            ("mergeable_state", "dirty"),
        ):
            patch, pr, files, checks = fixture()
            pr[key] = val
            result = evaluate(patch, pr, files, checks)
            self.assertEqual(result["status"], "HOLD")
            self.assertIsNone(result["merge_request"])

    def test_protected_base_drift_triggers_replay_not_bypass(self):
        patch, pr, files, checks = fixture()
        pr["base"]["sha"] = "d" * 40
        result = evaluate(patch, pr, files, checks)
        self.assertEqual(result["next_action"],
                         "REBASE_AND_REPLAY_PATCH_ON_CURRENT_MAIN")
        self.assertIsNone(result["merge_request"])

    def test_real_ci_failure_or_missing_required_job_blocks_merge(self):
        for bad in ("fail", "missing", "skipped", "wrong_app"):
            patch, pr, files, checks = fixture()
            row = checks["check_runs"][0]
            if bad == "fail": row["conclusion"] = "failure"
            elif bad == "missing":
                checks["check_runs"].pop(0);checks["total_count"]-=1
            elif bad == "skipped":row["conclusion"]="skipped"
            else: row["app"]["id"]=999
            result = evaluate(patch, pr, files, checks)
            self.assertEqual(result["status"],"HOLD")
            self.assertEqual(result["next_action"],
                             "REPAIR_EXACT_HEAD_CI_OR_RESTORE_REQUIRED_TESTS")

    def test_forged_patch_or_cross_sha_blob_is_rejected_before_ci(self):
        for action in ("patch", "test", "file_hash", "repo", "head"):
            patch, pr, files, checks = fixture()
            if action == "patch":
                patch["changed_content"] += "  contents: write\n"
                import hashlib
                patch["changed_sha256"] = hashlib.sha256(
                    patch["changed_content"].encode()).hexdigest()
                files[patch["source_path"]] = patch["changed_sha256"]
            elif action == "test":
                patch["test_content"] += "\n# disable real tests"
                import hashlib
                patch["test_sha256"] = hashlib.sha256(
                    patch["test_content"].encode()).hexdigest()
                files[patch["test_path"]] = patch["test_sha256"]
            elif action == "file_hash":
                files[patch["source_path"]] = "d" * 64
            elif action == "repo": pr["head"]["repo"]["full_name"] = "attacker/fork"
            elif action == "head": pr["head"]["sha"] = BASE
            with self.subTest(action=action),self.assertRaises(BrainError):
                evaluate(patch, pr, files, checks)

    def test_closed_unmerged_draft_is_not_delivery(self):
        patch,pr,files,checks=fixture()
        pr["state"] = "closed"
        pr["merged"] = False
        result=evaluate(patch,pr,files,checks)
        self.assertEqual(result["next_action"],
                         "CLOSED_UNMERGED_IS_NOT_A_FIX")
        self.assertFalse(result["technical_main_verified"])

    def test_original_merge_main_checks_are_required_separately(self):
        patch,pr,files,checks=fixture()
        pr["state"]="closed";pr["merged"]=True
        pr["merge_commit_sha"]=MERGE
        for case in ("no_main","advanced","no_checks","pass"):
            if case == "no_main": kwargs = {}
            elif case == "advanced": kwargs = {"current_main_sha": "d"*40}
            elif case == "no_checks": kwargs = {"current_main_sha": MERGE}
            else:
                mainchecks=copy.deepcopy(checks)
                for row in mainchecks["check_runs"]:
                    row["head_sha"]=MERGE
                kwargs={"current_main_sha":MERGE,"main_checks":mainchecks}
            with self.subTest(case=case):
                result=evaluate(patch,pr,files,checks,**kwargs)
                self.assertEqual(result["technical_main_verified"],case=="pass")
                self.assertFalse(result["live_service_verified"])
                self.assertFalse(result["actual_customer_value_verified"])

    def test_closed_source_with_adverse_main_is_not_verified(self):
        patch,pr,files,checks=fixture()
        pr["state"]="closed";pr["merged"]=True
        pr["merge_commit_sha"]=MERGE
        main=copy.deepcopy(checks)
        for row in main["check_runs"]:
            row["head_sha"]=MERGE
        main["check_runs"][1]["conclusion"]="failure"
        result=evaluate(patch,pr,files,checks,
                        current_main_sha=MERGE,main_checks=main)
        self.assertFalse(result["technical_main_verified"])
        self.assertEqual(result["next_action"],
                         "RESTORE_ORIGINAL_MAIN_REGRESSION_GATES")


if __name__ == "__main__":
    unittest.main()
