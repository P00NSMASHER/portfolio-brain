"""Original source coverage is NOT proof of healthy CI; zero-network tests."""
import copy
import json
import unittest
from brain.adapters import GitHub, policy
from brain.coverage import original_coverage, validate_coverage
from brain.investigate import investigate
from brain.render import investigation_summary_lines
from brain.sidecar import summarize
from test_brain_evidence_gaps import verified, observe, check, T0, T1
from test_brain_investigate import Transport, report, REPO, OTHER, THIRD, SOURCE, NOW
from test_brain_continuation import FOURTH

REPOS = (REPO, OTHER, THIRD, FOURTH)


def samples(repo=REPO, *, old="success", new="success", t0=T0, t1=T1,
            kind="ACTUAL", revision=None, duplicate=False, renamed=False):
    before = observe(repo, t0, [check(repo, conclusion=old)])
    afterward = observe(repo, t1, [check(repo, conclusion=new,
                                         name="audit" if renamed else "validate",
                                         sha=revision or "b"*40)],
                        kind=kind, sha=revision or "b"*40)
    if duplicate:
        from brain.core import digest
        before["payload"]["checks"].append(copy.deepcopy(before["payload"]["checks"][0]))
        afterward["payload"]["checks"].append(copy.deepcopy(afterward["payload"]["checks"][0]))
        # Mutated synthetic payloads need fresh canonical event identities.
        # Never manipulate an original immutable SQLite event to fake a match.
        for item in (before, afterward):
            item["id"] = item["kind"] + ":" + digest({**item, "id": ""})
    return before, afterward


def assess(*events, include_history=True):
    report_data, ledger = verified(*events)
    before = copy.deepcopy((report_data, ledger))
    transport = Transport()
    result = investigate(report_data, now=NOW,
                         history=ledger if include_history else None,
                         api=GitHub(transport=transport))
    assert (report_data, ledger) == before
    return result, summarize(result, SOURCE, *["success"]*4), transport


class SourceCoverageTests(unittest.TestCase):
    def test_four_fresh_source_comparisons_no_gets_or_false_health_claim(self):
        all_events = [item for repo in REPOS for item in samples(repo)]
        result, public, transport = assess(*all_events)
        self.assertEqual(transport.calls, [])
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        c = result["original_comparison_coverage"]
        self.assertEqual(c["comparison_classes"], {"COMPARABLE_FRESH": 4})
        self.assertEqual(c["unassessed_repositories"], 0)
        self.assertFalse(c["healthy_ci_verified"])
        self.assertFalse(c["execution_authority"])
        self.assertEqual(c["provider_reads_added"], 0)
        self.assertTrue(validate_coverage(c))
        self.assertEqual(public["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(public["comparison_coverage_counts"],
                         {"COMPARABLE_FRESH": 4})
        self.assertEqual(public["unassessed_approved_repositories"], 0)

    def test_one_source_never_proves_other_three_healthy(self):
        result, public, transport = assess(*samples())
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(transport.calls, [])
        self.assertEqual(public["comparison_coverage_counts"],
                         {"COMPARABLE_FRESH": 1})
        self.assertEqual(public["unassessed_approved_repositories"], 3)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertNotIn(REPO, json.dumps(public))
        self.assertFalse(public["root_cause_verified"])

    def test_nonactual_and_two_unassessed_repos_are_partial(self):
        result, public, transport = assess(
            *samples(REPO), *samples(OTHER, kind="SIMULATED"))
        self.assertEqual(transport.calls, [])
        self.assertEqual(public["comparison_coverage_counts"], {
            "COMPARABLE_FRESH": 1, "NON_ACTUAL_SOURCE": 1})
        self.assertEqual(public["unassessed_approved_repositories"], 2)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")

    def test_stale_original_baseline_never_green(self):
        result, public, transport = assess(
            *samples(t0="2026-10-08T12:00:00Z"))
        self.assertEqual(transport.calls, [])
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(public["comparison_coverage_counts"],
                         {"STALE_SOURCE_EVIDENCE": 1})

    def test_same_report_cannot_reuse_expired_samples_as_current(self):
        evidence = report(REPO)
        unchanged = copy.deepcopy(evidence)
        water = original_coverage(
            evidence, now="2026-10-14T17:00:00Z", limits=policy())
        self.assertEqual(evidence, unchanged)
        self.assertEqual(water["comparison_classes"],
                         {"STALE_SOURCE_EVIDENCE": 1})
        self.assertTrue(water["limitations_present"])

    def test_source_transition_still_needs_same_commit_comparison(self):
        result, public, transport = assess(*samples(revision="c"*40))
        self.assertEqual(transport.calls, [])
        self.assertEqual(public["comparison_coverage_counts"],
                         {"REVISION_CHANGED": 1})
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")

    def test_duplicated_original_check_names_do_not_become_health(self):
        result, public, transport = assess(*samples(duplicate=True))
        self.assertEqual(transport.calls, [])
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(public["comparison_coverage_counts"],
                         {"DUPLICATE_NAME_QUARANTINE": 1})
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")

    def test_no_shared_check_names_keeps_limitation_explicit(self):
        result, public, transport = assess(*samples(renamed=True),
                                           include_history=False)
        self.assertEqual(transport.calls, [])
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(public["comparison_coverage_counts"],
                         {"NO_SHARED_CHECK_NAMES": 1})
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")

    def test_unapproved_repo_cannot_fill_approved_comparison_slots(self):
        source = report("other-org/unapproved")
        transport = Transport()
        result = investigate(source, now=NOW,
                             api=GitHub(transport=transport))
        status = summarize(result, SOURCE, *["success"]*4)
        self.assertEqual(transport.calls, [])
        self.assertEqual(status["unassessed_approved_repositories"], 4)
        self.assertEqual(status["comparison_coverage_counts"], {})
        self.assertEqual(status["status"], "PARTIAL_READ_ONLY")
        self.assertNotIn("other-org", str(status))

    def test_operator_review_discloses_comparison_gap_not_source_health(self):
        receipt, public, _ = assess(*samples())
        lines = "\n".join(investigation_summary_lines(receipt))
        self.assertIn("Original comparison coverage (not CI health)", lines)
        self.assertIn("3 unassessed", lines)
        self.assertIn("does NOT certify", lines)
        self.assertIn("LIMITED", lines)


class CoverageTamperTests(unittest.TestCase):
    def setUp(self):
        self.receipt, _, _ = assess(*samples())

    def test_forged_and_inconsistent_coverage_cannot_publish_complete_status(self):
        probes = [
            {"approved_repositories": True},
            {"approved_repositories": 5},
            {"compared_repositories": -1},
            {"unassessed_repositories": 0},
            {"comparison_classes": {"COMPARABLE_FRESH": 4}},
            {"comparison_classes": {"UNKNOWN": 1}},
            {"comparison_classes": {"COMPARABLE_FRESH": True}},
            {"comparison_classes": {"COMPARABLE_FRESH": 0}},
            {"limitations_present": False},
            {"healthy_ci_verified": True},
            {"root_cause_verified": True},
            {"execution_authority": True},
            {"provider_reads_added": 1},
            {"scope": "SIGNED_PRODUCTION_ACCEPTANCE"},
        ]
        for patch in probes:
            with self.subTest(patch=patch):
                forged = copy.deepcopy(self.receipt)
                forged["original_comparison_coverage"].update(patch)
                result = summarize(forged, SOURCE, *["success"]*4)
                self.assertEqual(result["status"],
                                 "BLOCKED_NO_VERIFIED_INVESTIGATION")
                self.assertEqual(result["comparison_coverage_counts"], {})
                self.assertIsNone(result["unassessed_approved_repositories"])
                self.assertFalse(result["execution_authority"])

    def test_explicit_null_is_invalid_not_an_optional_legacy_gap(self):
        forged = copy.deepcopy(self.receipt)
        forged["original_comparison_coverage"] = None
        result = summarize(forged, SOURCE, *["success"]*4)
        self.assertEqual(result["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")

    def test_legacy_receipt_without_new_coverage_remains_backward_compatible(self):
        from test_brain_sidecar import observation
        result = summarize(observation(), SOURCE, *["success"]*4)
        self.assertEqual(result["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(result["comparison_coverage_counts"], {})
        self.assertIsNone(result["comparison_coverage_limited"])

    def test_replayed_receipt_comparisons_never_modify_original_source(self):
        source = report(REPO)
        initial = copy.deepcopy(source)
        transport = Transport()
        result = investigate(source, now=NOW,
                             api=GitHub(transport=transport))
        self.assertEqual(source, initial)
        self.assertEqual(len(transport.calls), 4)
        self.assertEqual(result["original_comparison_coverage"]
                         ["compared_repositories"], 1)

if __name__ == "__main__":
    unittest.main()
