"""V7 bounded evidence-gap revalidation, using synthetic original ledger history."""
from __future__ import annotations
import copy
import tempfile
import unittest
from pathlib import Path
from brain.adapters import GitHub, event
from brain.core import BrainError, Store
from brain.investigate import investigate
from brain.sidecar import summarize
from test_brain_investigate import Transport, SOURCE, REV, REPO, OTHER, THIRD, NOW

T0 = "2026-10-12T14:00:00Z"
T1 = "2026-10-12T15:00:00Z"
FOURTH = "P00NSMASHER/github-value-hunt-ledger"


def check(repo, *, conclusion="failure", name="validate", status="completed", sha=REV):
    return {"name": name, "status": status, "conclusion": conclusion,
            "head_sha": sha,
            "url": f"https://github.com/{repo}/actions/runs/10/job/20"}


def observe(repo, when, checks, *, kind="ACTUAL", sha=REV):
    payload = {"repository": repo, "head_sha": sha, "default_branch": "main",
               "open_issues": 1, "source_ref": f"https://github.com/{repo}/commit/{sha}",
               "checks": checks}
    return event("repository", repo, payload, SOURCE, now=when, data_kind=kind)


def verified(*events):
    with tempfile.TemporaryDirectory() as folder:
        db = Store(Path(folder) / "state.sqlite", visibility="PUBLIC")
        try:
            db.submit(list(events), now=NOW)
            db.drain()
            report = db.report(SOURCE, now=NOW)
            history, _, _ = db._verified_events()
            assert db.read_report(SOURCE, now=NOW) == report
        finally:
            db.close()
    return report, history


class EvidenceGapTests(unittest.TestCase):
    def investigate_history(self, report, history, transport=None, **options):
        transport = transport if transport is not None else Transport()
        result = investigate(report, history=history, api=GitHub(transport=transport),
                             now=NOW, **options)
        return result, transport

    def test_missing_previously_adverse_check_revalidated_without_false_closure(self):
        report, events = verified(
            observe(REPO, T0, [check(REPO)]), observe(REPO, T1, []))
        self.assertEqual(report["repository_changes"][0]["check_comparison"],
                         "NO_SHARED_CHECK_NAMES")
        before = copy.deepcopy(report), copy.deepcopy(events)
        result, transport = self.investigate_history(report, events)
        self.assertEqual(result["status"], "READ_ONLY_REVALIDATION_COMPLETE")
        self.assertEqual(result["investigations"][0]["follow_up_kind"],
                         "EVIDENCE_GAP_REVALIDATION")
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"], "STILL_ADVERSE")
        self.assertEqual(result["requests_used"], 4)
        self.assertEqual(result["github_mutations"], 0)
        self.assertEqual((report, events), before)
        self.assertEqual(len(transport.calls), 4)
        public = summarize(result, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(public["observed_followup_kinds"],
                         {"EVIDENCE_GAP_REVALIDATION": 1})
        self.assertNotIn("validate", str(public))
        self.assertFalse(public["root_cause_verified"])

    def test_missing_success_check_is_a_gap_not_a_regression_or_recovery(self):
        report, events = verified(
            observe(REPO, T0, [check(REPO, conclusion="success")]),
            observe(REPO, T1, []))
        result, _ = self.investigate_history(report, events, Transport(conclusion="success"))
        self.assertEqual(result["investigations"][0]["follow_up_kind"], "EVIDENCE_GAP_REVALIDATION")
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"],
                         "SUCCESS_OBSERVED_NOT_RESOLUTION")

    def test_stalled_check_is_not_treated_as_success(self):
        report, events = verified(
            observe(REPO, T0, [check(REPO)]),
            observe(REPO, T1, [check(REPO, status="in_progress", conclusion=None)]))
        transport = Transport(conclusion=None)
        transport.check_mutation = lambda item: item.update(status="in_progress")
        result, _ = self.investigate_history(report, events, transport)
        self.assertEqual(result["investigations"][0]["follow_up_kind"], "EVIDENCE_GAP_REVALIDATION")
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"], "CHECK_NOT_COMPLETED")

    def test_still_missing_is_unverified_and_changed_revision_requires_comparison(self):
        report, history = verified(observe(REPO, T0, [check(REPO)]), observe(REPO, T1, []))
        transport = Transport()
        transport.check_mutation = lambda item: item.update(name="other")
        result, _ = self.investigate_history(report, history, transport)
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"],
                         "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK")
        result, _ = self.investigate_history(report, history, Transport(revision="c" * 40))
        self.assertEqual(result["investigations"][0]["outcome"],
                         "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON")

    def test_new_regression_before_gap_before_persistent_before_recovery(self):
        report, history = verified(
            observe(REPO, T0, [check(REPO, conclusion="success")]),
            observe(REPO, T1, [check(REPO)]),
            observe(OTHER, T0, [check(OTHER)]), observe(OTHER, T1, []),
            observe(THIRD, T0, [check(THIRD)]),
            observe(THIRD, T1, [check(THIRD)]),
            observe(FOURTH, T0, [check(FOURTH)]),
            observe(FOURTH, T1, [check(FOURTH, conclusion="success")]),
        )
        result, _ = self.investigate_history(report, history)
        self.assertEqual([x["repository"] for x in result["investigations"]],
                         [REPO, OTHER, THIRD])
        self.assertEqual(result["eligible_count"], 4)
        self.assertEqual(result["deferred_count"], 1)
        self.assertEqual(result["requests_used"], 12)

    def test_four_gaps_rotate_without_starvation_and_within_limits(self):
        repos = (REPO, OTHER, THIRD, FOURTH)
        records = []
        for repo in repos:
            records.extend([observe(repo, T0, [check(repo)]), observe(repo, T1, [])])
        report, history = verified(*records)
        omitted = set()
        for hour in range(16, 20):
            result = investigate(report, history=history, api=GitHub(transport=Transport()),
                                 now=f"2026-10-12T{hour:02d}:00:00Z")
            self.assertEqual(result["eligible_count"], 4)
            self.assertEqual(result["deferred_count"], 1)
            self.assertEqual(result["requests_used"], 12)
            omitted.update(set(repos) - {r["repository"] for r in result["investigations"]})
        self.assertEqual(omitted, set(repos))

    def test_nonactual_changed_revision_or_ambiguous_samples_not_promoted(self):
        candidates = (
            [observe(REPO, T0, [check(REPO)]), observe(REPO, T1, [], kind="SIMULATED")],
            [observe(REPO, T0, [check(REPO)]),
             observe(REPO, T1, [], sha="c" * 40)],
            [observe(REPO, T0, [check(REPO), check(REPO)]),
             observe(REPO, T1, [])],
        )
        for originals in candidates:
            with self.subTest(kind=originals[-1]["data_kind"]):
                report, history = verified(*originals)
                result, transport = self.investigate_history(report, history)
                self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
                self.assertEqual(transport.calls, [])

    def test_forged_original_report_fails_before_provider_read(self):
        report, history = verified(observe(REPO, T0, [check(REPO)]), observe(REPO, T1, []))
        forged = copy.deepcopy(report)
        forged["repository_changes"][0]["current_revision"] = "c" * 40
        transport = Transport()
        with self.assertRaises(BrainError):
            self.investigate_history(forged, history, transport)
        self.assertEqual(transport.calls, [])
        result = investigate(report, api=GitHub(transport=transport), now=NOW)
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
