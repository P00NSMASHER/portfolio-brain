"""Hostile synthetic tests for INERT two-stage native auto-merge review design."""
import copy
from pathlib import Path
import unittest

from brain.v9 import native_enrollment_plan as design


HEAD = "a" * 40
OTHER = "b" * 40


def sample():
    return {
        "repository": design.REPOSITORY,
        "repository_id": design.REPOSITORY_ID,
        "ruleset_id": design.RULESET_ID,
        "main_sha": design.SOURCE_SHA,
        "source_acceptance_sha": design.SOURCE_SHA,
        "protected_main": True,
        "required_check_issuers": dict(design.CHECK_ISSUERS),
        **{key: True for key in design.PROOF_KEYS},
        "pr": {
            "number": 999991,
            "state": "open",
            "draft": False,
            "merged": False,
            "mergeable": True,
            "base_branch": "main",
            "base_sha": design.SOURCE_SHA,
            "head_sha": HEAD,
            "author": "P00NSMASHER",
            "auto_merge": None,
            "labels": [design.LABEL],
            "rest_mergeable_state": "blocked",
            "graphql_merge_state": "BLOCKED",
            "viewer_can_enable_auto_merge": True,
        },
        "check_runs": [
            {"name": "portfolio-phase1-gate", "app_id": 5121826,
             "head_sha": HEAD, "status": "completed", "conclusion": "success"},
            {"name": "validate", "app_id": 15368, "head_sha": HEAD,
             "status": "in_progress", "conclusion": None},
        ]
    }


def decision(initial=None, final=None):
    first = copy.deepcopy(initial if initial is not None else sample())
    last = copy.deepcopy(final if final is not None else first)
    return design.plan_early_enrollment(first, last)


class NativeAdmissionReviewTests(unittest.TestCase):

    def assert_hold(self, snap, code, *, change_final=False):
        actual = decision(final=snap) if change_final else decision(initial=snap, final=snap)
        self.assertEqual(actual.status, "HOLD")
        self.assertIn(code, actual.reason)
        self.assertEqual(actual.provider_writes, 0)
        self.assertFalse(actual.merge_authorized)

    def test_only_one_independent_success_and_one_pending_is_review_candidate(self):
        result = decision()
        self.assertEqual(result.status, "REVIEW_ONLY_EARLY_ADMISSION_CANDIDATE")
        self.assertEqual(result.provider_writes, 0)
        self.assertFalse(result.merge_authorized)

    def test_pending_other_issuer_variant_can_be_review_candidate(self):
        snap = sample()
        snap["check_runs"][0]["status"] = "queued"
        snap["check_runs"][0]["conclusion"] = None
        snap["check_runs"][1]["status"] = "completed"
        snap["check_runs"][1]["conclusion"] = "success"
        self.assertEqual(decision(snap).status, "REVIEW_ONLY_EARLY_ADMISSION_CANDIDATE")

    def test_clean_even_with_both_green_is_not_eligible(self):
        snap = sample()
        snap["pr"]["rest_mergeable_state"] = "clean"
        snap["pr"]["graphql_merge_state"] = "CLEAN"
        snap["pr"]["viewer_can_enable_auto_merge"] = False
        snap["check_runs"][1]["status"] = "completed"
        snap["check_runs"][1]["conclusion"] = "success"
        self.assert_hold(snap, "GITHUB_NATIVE_EARLY_ELIGIBILITY_NOT_PROVEN")

    def test_behind_branch_is_not_a_safe_candidate_despite_viewer_true(self):
        snap = sample()
        snap["pr"]["rest_mergeable_state"] = "behind"
        snap["pr"]["graphql_merge_state"] = "BEHIND"
        self.assert_hold(snap, "GITHUB_NATIVE_EARLY_ELIGIBILITY_NOT_PROVEN")

    def test_two_green_checks_do_not_create_a_fake_early_window(self):
        snap = sample()
        snap["check_runs"][1].update(status="completed", conclusion="success")
        self.assert_hold(snap, "MUST_HAVE_ONE_SUCCESS_AND_ONE_GENUINELY_PENDING_CHECK")

    def test_two_pending_checks_fail_until_first_independent_success(self):
        snap = sample()
        snap["check_runs"][0].update(status="queued", conclusion=None)
        self.assert_hold(snap, "MUST_HAVE_ONE_SUCCESS_AND_ONE_GENUINELY_PENDING_CHECK")

    def test_failed_cancelled_skipped_and_ambiguous_check_cannot_pass(self):
        for status, conclusion in [
            ("completed", "failure"), ("completed", "cancelled"),
            ("completed", "neutral"), ("completed", "skipped"),
            ("completed", None), ("in_progress", "failure"),
            ("waiting", None), (True, "success"),
        ]:
            with self.subTest(status=status, conclusion=conclusion):
                snap = sample()
                snap["check_runs"][1].update(status=status, conclusion=conclusion)
                self.assert_hold(snap, "REQUIRED_CHECK_FAILED_AMBIGUOUS_OR_CANCELLED")

    def test_wrong_issuer_wrong_sha_and_type_spoofs_fail(self):
        for key, value in [
            ("app_id", 0), ("app_id", True), ("app_id", 5121826),
            ("head_sha", OTHER), ("head_sha", "A" * 40),
        ]:
            with self.subTest(key=key, value=value):
                snap = sample()
                snap["check_runs"][1][key] = value
                self.assert_hold(snap, "REQUIRED_CHECK_WRONG_HEAD_OR_ISSUER")

    def test_absent_duplicate_and_malformed_check_census_fail(self):
        cases = []
        s = sample()
        s["check_runs"] = [s["check_runs"][0]]
        cases.append(s)
        s = sample()
        s["check_runs"].append(dict(s["check_runs"][1]))
        cases.append(s)
        s = sample()
        s["check_runs"] = {}
        cases.append(s)
        s = sample()
        s["check_runs"].append(None)
        cases.append(s)
        for candidate in cases:
            with self.subTest(shape=str(candidate["check_runs"])[:70]):
                actual = decision(candidate)
                self.assertEqual(actual.status, "HOLD")
                self.assertEqual(actual.provider_writes, 0)

    def test_untrusted_author_missing_label_draft_and_merged_fail(self):
        changes = [
            ("author", "untrusted-fork"),
            ("labels", []),
            ("draft", True),
            ("merged", True),
            ("state", "closed"),
            ("auto_merge", {"merge_method": "squash"}),
            ("base_sha", OTHER),
            ("head_sha", design.SOURCE_SHA),
            ("base_branch", "unsafe"),
        ]
        for key, value in changes:
            with self.subTest(key=key):
                snap = sample()
                snap["pr"][key] = value
                self.assert_hold(snap, "ORIGINAL_PR_ADMISSION_IDENTITY_UNVERIFIED")

    def test_missing_acceptance_and_wrong_main_fail(self):
        for key,value in [
            ("main_sha", OTHER),
            ("source_acceptance_sha", OTHER),
            ("protected_main", False),
            ("protected_main", 1),
        ]:
            with self.subTest(key=key):
                snap=sample()
                snap[key]=value
                self.assert_hold(snap, "CURRENT_SOURCE_ACCEPTANCE_UNVERIFIED")

    def test_all_provider_derived_flags_are_required_but_cannot_confer_authority(self):
        for key in design.PROOF_KEYS:
            for value in (False, None, 1, "true"):
                with self.subTest(key=key,value=value):
                    snap=sample()
                    snap[key]=value
                    self.assert_hold(snap, key.upper())
        self.assertFalse(decision().merge_authorized)

    def test_wrong_repository_ruleset_or_issuer_policy_fail(self):
        for key,value,code in [
            ("repository", "P00NSMASHER/other", "RULESET_IDENTITY"),
            ("repository_id", 42, "RULESET_IDENTITY"),
            ("ruleset_id", 1, "RULESET_IDENTITY"),
            ("required_check_issuers", {"validate": 15368}, "CHECK_ISSUERS_CHANGED"),
        ]:
            with self.subTest(key=key):
                snap=sample()
                snap[key]=value
                self.assert_hold(snap, code)

    def test_final_head_or_pr_number_race_fails(self):
        for key,value in [("head_sha", OTHER), ("number", 77776)]:
            with self.subTest(key=key):
                last = sample()
                last["pr"][key]=value
                if key == "head_sha":
                    for check in last["check_runs"]:
                        check["head_sha"] = OTHER
                got = decision(final=last)
                self.assertEqual(got.status, "HOLD")
                self.assertIn("CHANGED_BETWEEN_READS", got.reason)

    def test_final_eligibility_revocation_fails_before_any_mutation(self):
        last = sample()
        last["pr"]["viewer_can_enable_auto_merge"]=False
        self.assert_hold(last, "FINAL_GITHUB_NATIVE_EARLY_ELIGIBILITY_NOT_PROVEN",
                         change_final=True)

    def test_pending_check_finishes_before_final_check_refuses_enrollment(self):
        last = sample()
        last["check_runs"][1].update(status="completed", conclusion="success")
        self.assert_hold(last, "FINAL_MUST_HAVE_ONE_SUCCESS_AND_ONE_GENUINELY_PENDING_CHECK",
                         change_final=True)

    def test_production_controller_and_workflow_are_not_modified(self):
        module = Path("brain/v9/native_enrollment_plan.py").read_text()
        self.assertNotIn("http.client", module)
        self.assertNotIn("urllib.request", module)
        self.assertNotIn("subprocess", module)
        self.assertNotIn("os.environ", module)
        self.assertNotIn("ENABLE_MUTATION =", module)
        self.assertNotIn("def run(api", module)
        self.assertNotIn("github_token", module.lower())
        self.assertIn("REVIEW_ONLY_NO_EXECUTABLE_ENROLLMENT", module)

    def test_uncertain_no_enrollment_remains_hold_not_retry(self):
        readback={"number":999991, "head_sha":HEAD,
                  "base_sha":design.SOURCE_SHA, "state":"open",
                  "merged":False,"auto_merge":None}
        got=design.interpret_provider_readback(readback,expected_number=999991,
                                                  expected_head=HEAD)
        self.assertEqual(got.status, "HOLD")
        self.assertIn("DO_NOT_RETRY", got.reason)

    def test_original_provider_enrollment_visible_never_grants_merge(self):
        readback={"number":999991, "head_sha":HEAD,
                  "base_sha":design.SOURCE_SHA, "state":"open",
                  "merged":False,"auto_merge":{"merge_method":"squash"}}
        got=design.interpret_provider_readback(readback,expected_number=999991,
                                                  expected_head=HEAD)
        self.assertEqual(got.status,"GITHUB_NATIVE_ENROLLMENT_VISIBLE")
        self.assertFalse(got.merge_authorized)
        self.assertEqual(got.provider_writes,0)

    def test_post_merge_provider_observation_is_not_independent_certificate(self):
        readback={"number":999991, "head_sha":HEAD,
                  "base_sha":design.SOURCE_SHA, "state":"closed",
                  "merged":True,"merge_commit_sha":OTHER}
        got=design.interpret_provider_readback(readback,expected_number=999991,
                                                  expected_head=HEAD)
        self.assertIn("INDEPENDENT_PROVENANCE",got.status)
        self.assertFalse(got.merge_authorized)

    def test_ambiguous_or_wrong_head_readback_fails(self):
        for record in [
            None,
            {},
            {"number":999991,"head_sha":OTHER,"base_sha":design.SOURCE_SHA},
            {"number":999991,"head_sha":HEAD,"base_sha":OTHER},
            {"number":999991,"head_sha":HEAD,"base_sha":design.SOURCE_SHA,
             "state":"open","merged":False,"auto_merge":{"merge_method":"rebase"}},
        ]:
            with self.subTest(record=record):
                got=design.interpret_provider_readback(record,expected_number=999991,
                                                      expected_head=HEAD)
                self.assertEqual(got.status,"HOLD")
                self.assertEqual(got.provider_writes,0)

    def test_all_paths_return_zero_writes_and_never_authorize_merge(self):
        cases=[(sample(),sample())]
        good=sample()
        bad=sample()
        bad["check_runs"][1]["status"]="completed"
        bad["check_runs"][1]["conclusion"]="failure"
        cases += [(bad,bad),(good,bad)]
        for a,b in cases:
            with self.subTest(status=a["check_runs"][1]["status"]):
                x=design.plan_early_enrollment(a,b)
                self.assertFalse(x.merge_authorized)
                self.assertEqual(x.provider_writes,0)


if __name__=="__main__":
    unittest.main()
