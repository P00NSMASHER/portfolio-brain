"""V7 source-bound incident fingerprints and bounded cross-repo CI coincidences.

The original check names/observations are synthetic and never diagnose shared
root cause, deployed impact, repairs, spending or license permission.
"""
import copy
import unittest

from brain.review import review_packet, review_lines
from test_brain_review import SHA, REV, REPOS, check, observation, receipt

CHECK = "validate"
OTHER = "P00NSMASHER/trading-platform"
THIRD = "P00NSMASHER/abvmschoolstarworld"


def real_check(repo, *, name=CHECK, outcome="STILL_ADVERSE",
               original="PERSISTENT_ADVERSE_OBSERVED", job=1):
    row = check(name=name, outcome=outcome, original=original)
    row["source_ref"] = (
        f"https://github.com/{repo}/actions/runs/4242/job/{job}"
    )
    return row


def row(repo, *checks, revision=REV, outcome="OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE"):
    result = observation(*checks, repo=repo, outcome=outcome)
    result["expected_revision"] = revision
    result["source_refs"] = [f"https://github.com/{repo}/commit/{revision}"]
    return result


class IncidentIdentityTests(unittest.TestCase):
    def test_identity_stable_across_observation_time_or_outcome(self):
        initial = receipt(row(REPOS[0], real_check(REPOS[0])))
        later = copy.deepcopy(initial)
        later["checked_at"] = "2026-10-13T14:00:00Z"
        later["investigations"][0]["checks"][0]["outcome"] = (
            "SUCCESS_OBSERVED_NOT_RESOLUTION"
        )
        first = review_packet(initial)["items"][0]
        second = review_packet(later)["items"][0]
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["case_key"], second["case_key"])
        self.assertEqual(len(first["case_key"]), 24)
        self.assertEqual(first["case_identity_scope"],
                         "SOURCE_REVISION_CHECK_NAME_NOT_PERSISTED_CASE")
        self.assertFalse(first["execution_authority"])

    def test_check_repo_revision_changes_produce_separate_cases(self):
        base = review_packet(
            receipt(row(REPOS[0], real_check(REPOS[0])))
        )["items"][0]["case_key"]
        altered_name = review_packet(
            receipt(row(REPOS[0], real_check(REPOS[0], name="security")))
        )["items"][0]["case_key"]
        altered_repo = review_packet(
            receipt(row(OTHER, real_check(OTHER)))
        )["items"][0]["case_key"]
        altered_rev = review_packet(
            receipt(row(REPOS[0], real_check(REPOS[0]),
                        revision="c"*40))
        )["items"][0]["case_key"]
        self.assertEqual(len({base, altered_name, altered_repo, altered_rev}), 4)

    def test_unavailable_repo_level_evidence_has_distinct_stable_key(self):
        current = receipt(row(REPOS[0],
                              outcome="SOURCE_CHANGED_REQUIRES_NEW_COMPARISON"))
        first = review_packet(current)["items"][0]
        repeated = copy.deepcopy(current)
        repeated["checked_at"] = "2026-10-13T14:00:00Z"
        self.assertEqual(first["case_key"],
                         review_packet(repeated)["items"][0]["case_key"])
        self.assertIsNone(first["check_name"])


class CrossRepositoryCheckReviewTests(unittest.TestCase):
    def two(self, left="STILL_ADVERSE", right="STILL_ADVERSE",
            left_name=CHECK, right_name=CHECK):
        return receipt(
            row(REPOS[0], real_check(REPOS[0], name=left_name, outcome=left)),
            row(OTHER, real_check(OTHER, name=right_name, outcome=right)),
        )

    def test_matching_adverse_check_names_get_only_advisory_coincidence(self):
        result = review_packet(self.two())
        self.assertEqual(len(result["same_name_adverse_coincidences"]), 1)
        g = result["same_name_adverse_coincidences"][0]
        self.assertEqual(g["check_name"], CHECK)
        self.assertEqual(g["repositories"], sorted([REPOS[0], OTHER]))
        self.assertEqual(g["status"], "SAME_NAME_OBSERVED_IN_MULTIPLE_REPOS")
        self.assertEqual(g["interpretation"],
                         "NAME_MATCH_NOT_SHARED_ROOT_CAUSE")
        self.assertEqual(len(g["source_bound_case_keys"]), 2)
        self.assertEqual(len(g["source_refs"]), 2)
        self.assertEqual(g["provider_reads_added"], 0)
        self.assertIs(g["execution_authority"], False)
        self.assertEqual(result["get_requests_added"], 0)
        self.assertEqual(result["external_state_writes"], 0)
        self.assertFalse(result["incident_closed"])
        self.assertFalse(result["root_cause_verified"])

    def test_green_pending_missing_or_differently_named_never_correlate(self):
        for left, right, ln, rn in (
            ("STILL_ADVERSE", "SUCCESS_OBSERVED_NOT_RESOLUTION", CHECK, CHECK),
            ("CHECK_NOT_COMPLETED", "STILL_ADVERSE", CHECK, CHECK),
            ("STILL_ADVERSE", "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK", CHECK, CHECK),
            ("STILL_ADVERSE", "STILL_ADVERSE", "validate", "audit"),
            ("OTHER_CONCLUSION_NOT_RESOLUTION", "STILL_ADVERSE", CHECK, CHECK),
        ):
            with self.subTest(left=left, right=right, names=(ln, rn)):
                self.assertEqual(
                    review_packet(self.two(left, right, ln, rn))
                    ["same_name_adverse_coincidences"], [])

    def test_provider_failure_with_no_check_name_never_becomes_coincidence(self):
        packet = review_packet(receipt(
            row(REPOS[0], outcome="UNVERIFIED_READ_FAILED"),
            row(OTHER, outcome="UNVERIFIED_READ_FAILED"),
            status="INCOMPLETE_READ_ONLY_REVALIDATION",
        ))
        self.assertEqual(packet["same_name_adverse_coincidences"], [])
        self.assertFalse(packet["business_impact_verified"])

    def test_three_distinct_repo_same_named_check_one_group(self):
        packet = review_packet(receipt(
            row(REPOS[0], real_check(REPOS[0])),
            row(OTHER, real_check(OTHER)),
            row(THIRD, real_check(THIRD)),
        ))
        matches = packet["same_name_adverse_coincidences"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["repositories"],
                         sorted([REPOS[0], OTHER, THIRD]))
        self.assertEqual(len(matches[0]["source_bound_case_keys"]), 3)

    def test_cross_repo_grouping_independent_of_receipt_order(self):
        a = row(REPOS[0], real_check(REPOS[0], name="check-x"))
        b = row(OTHER, real_check(OTHER, name="check-x"))
        c = row(THIRD, real_check(THIRD, name="check-x"))
        first = review_packet(receipt(a, b, c))
        second = review_packet(receipt(c, b, a))
        self.assertEqual(first, second)

    def test_untrusted_check_name_markdown_is_escaped(self):
        dangerous = "<script> [click](https://evil.example) *fail*"
        packet = receipt(
            row(REPOS[0], real_check(REPOS[0], name=dangerous)),
            row(OTHER, real_check(OTHER, name=dangerous)),
        )
        result = review_packet(packet)
        self.assertEqual(result["same_name_adverse_coincidences"][0]["check_name"],
                         dangerous)
        lines = "\n".join(review_lines(packet))
        self.assertNotIn("<script>", lines)
        self.assertNotIn("[click]", lines)
        self.assertNotIn("*fail*", lines)
        self.assertIn(r"\<script\>", lines)
        self.assertIn("not evidence of a shared cause", lines.lower())

    def test_correlations_respect_selected_review_bounds(self):
        # Ten checks per repository, four human review items per repo.
        names = [f"check-{i:02d}" for i in range(10)]
        rows = [
            row(repo, *(real_check(repo, name=n, job=i+1)
                        for i, n in enumerate(names)))
            for repo in (REPOS[0], OTHER, THIRD)
        ]
        packet = review_packet(receipt(*rows))
        self.assertEqual(len(packet["items"]), 12)
        self.assertLessEqual(len(packet["same_name_adverse_coincidences"]), 4)
        self.assertTrue(all(item["check_name"] in names[:4]
                            for item in packet["same_name_adverse_coincidences"]))
        self.assertGreater(packet["omitted_due_to_review_bounds"], 0)

    def test_no_cross_repo_hypotheses_when_original_check_ref_not_source_bound(self):
        good = real_check(REPOS[0])
        no_link = real_check(OTHER)
        no_link["source_ref"] = "https://untrusted.example/bad"
        packet = review_packet(receipt(
            row(REPOS[0], good), row(OTHER, no_link)
        ))
        self.assertEqual(packet["same_name_adverse_coincidences"], [])

    def test_no_new_provider_or_automation_or_writes(self):
        packet = review_packet(self.two())
        self.assertEqual(packet["get_requests_added"], 0)
        self.assertEqual(packet["external_state_writes"], 0)
        self.assertIs(packet["execution_authority"], False)
        self.assertIs(packet["incident_closed"], False)
        self.assertIs(packet["business_impact_verified"], False)
        for group in packet["same_name_adverse_coincidences"]:
            self.assertNotIn("auto_close", group)
            self.assertNotIn("shared_cause_confirmed", group)


if __name__ == "__main__":
    unittest.main()
