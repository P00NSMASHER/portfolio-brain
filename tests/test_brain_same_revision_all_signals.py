"""V7 original-ledger multi-signal tests: one GET, no state mutation, no false green."""
import copy
import unittest

from brain.adapters import GitHub
from brain.core import BrainError
from brain.investigate import investigate
from brain.sidecar import summarize
from test_brain_evidence_gaps import check, observe, verified, T0, T1
from test_brain_investigate import (
    Transport, REPO, OTHER, THIRD, REV, SOURCE, NOW,
)
from test_brain_continuation import FOURTH


def fact(repo, instant, conclusions):
    checks = []
    for name, conclusion in sorted(conclusions.items()):
        status = "in_progress" if conclusion is None else "completed"
        checks.append(check(repo, name=name, conclusion=conclusion, status=status))
    return observe(repo, instant, checks)


def sample(*, missing=True, pending=False, repo=REPO):
    past = {
        "validate": "success", "persist": "failure", "audit": "failure",
    }
    new = {
        "validate": "failure", "persist": "failure", "audit": "success",
    }
    if missing:
        past["orphan"] = "success"
    if pending:
        past["queued"] = "success"
        new["queued"] = None
    return verified(fact(repo, T0, past), fact(repo, T1, new))


def transport():
    provider = Transport(conclusion="failure")
    provider.extra_checks = [
        {"id": 21, "name": "persist", "status": "completed",
         "conclusion": "failure", "head_sha": REV,
         "html_url": f"https://github.com/{REPO}/actions/runs/11/job/21"},
        {"id": 22, "name": "audit", "status": "completed",
         "conclusion": "success", "head_sha": REV,
         "html_url": f"https://github.com/{REPO}/actions/runs/12/job/22"},
    ]
    return provider


class FullSingleRepositorySignalTests(unittest.TestCase):
    def run_case(self, report, events, *, provider=None, moment=NOW, **extra):
        provider = provider or transport()
        api = GitHub(transport=provider)
        result = investigate(report, history=events, api=api, now=moment, **extra)
        return result, provider

    def test_four_distinct_signals_rechecked_by_one_provider_observation(self):
        report, history = sample(missing=True)
        untouched = copy.deepcopy((report, history))
        receipt, provider = self.run_case(report, history)
        self.assertEqual((report, history), untouched)
        self.assertEqual(receipt["status"], "READ_ONLY_REVALIDATION_COMPLETE")
        self.assertEqual(receipt["eligible_count"], 1)
        self.assertEqual(receipt["deferred_count"], 0)
        self.assertEqual(receipt["requests_used"], 4)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(receipt["github_mutations"], 0)
        self.assertEqual(receipt["events_written"], 0)
        self.assertEqual(receipt["paid_calls"], 0)
        self.assertFalse(receipt["execution_authority"])
        self.assertFalse(receipt["root_cause_verified"])
        row = receipt["investigations"][0]
        self.assertNotIn("follow_up_kind", row)
        reasons = {
            "validate": "INITIAL_ADVERSE_TRANSITION",
            "persist": "PERSISTENT_ADVERSE_OBSERVED",
            "audit": "RECOVERY_OBSERVED_NOT_RESOLUTION",
            "orphan": "EVIDENCE_GAP_REVALIDATION",
        }
        self.assertEqual(row["check_names"], sorted(reasons))
        self.assertEqual(row["check_evidence_classes"], reasons)
        self.assertEqual(
            {entry["name"]: entry["original_evidence_class"]
             for entry in row["checks"]}, reasons)
        self.assertEqual(
            {entry["name"]: entry["outcome"] for entry in row["checks"]},
            {
                "validate": "STILL_ADVERSE",
                "persist": "STILL_ADVERSE",
                "audit": "SUCCESS_OBSERVED_NOT_RESOLUTION",
                "orphan": "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK",
            }
        )

    def test_missing_signal_stays_partial_with_complete_aggregate_provenance(self):
        report, history = sample(missing=True)
        receipt, _ = self.run_case(report, history)
        summary = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(summary["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(summary["observed_followup_kinds"],
                         {"INITIAL_ADVERSE_TRANSITION": 1})
        self.assertEqual(summary["observed_check_evidence_classes"], {
            "INITIAL_ADVERSE_TRANSITION": 1,
            "PERSISTENT_ADVERSE_OBSERVED": 1,
            "RECOVERY_OBSERVED_NOT_RESOLUTION": 1,
            "EVIDENCE_GAP_REVALIDATION": 1
        })
        self.assertNotIn(REPO, str(summary))
        self.assertNotIn("orphan", str(summary))
        self.assertFalse(summary["root_cause_verified"])
        self.assertEqual(summary["events_written"], 0)

    def test_no_gap_retains_all_three_evidence_classes_in_complete_read_only_result(self):
        report, events = sample(missing=False)
        receipt, provider = self.run_case(report, events)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(receipt["investigations"][0]["check_names"],
                         ["audit", "persist", "validate"])
        summary = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(summary["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(summary["observed_check_evidence_classes"], {
            "INITIAL_ADVERSE_TRANSITION": 1,
            "PERSISTENT_ADVERSE_OBSERVED": 1,
            "RECOVERY_OBSERVED_NOT_RESOLUTION": 1,
        })

    def test_queued_check_is_also_rechecked_without_changing_budget(self):
        report, history = sample(missing=False, pending=True)
        provider = transport()
        provider.extra_checks.append({
            "id": 23, "name": "queued", "status": "in_progress",
            "conclusion": None, "head_sha": REV,
            "html_url": f"https://github.com/{REPO}/actions/runs/13/job/23"
        })
        receipt, provider = self.run_case(report, history, provider=provider)
        self.assertEqual(receipt["requests_used"], 4)
        self.assertEqual(len(provider.calls), 4)
        row = receipt["investigations"][0]
        self.assertEqual(row["check_evidence_classes"]["queued"],
                         "EVIDENCE_GAP_REVALIDATION")
        self.assertEqual(
            next(x for x in row["checks"] if x["name"] == "queued")["outcome"],
            "CHECK_NOT_COMPLETED")
        self.assertEqual(summarize(receipt, SOURCE, *["success"] * 4)["status"],
                         "PARTIAL_READ_ONLY")

    def test_zero_continuation_signals_does_not_add_provider_requests(self):
        report, events = verified(
            fact(REPO, T0, {"validate": "success"}),
            fact(REPO, T1, {"validate": "failure"})
        )
        provider = Transport()
        result, provider = self.run_case(report, events, provider=provider)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["requests_used"], 4)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(result["investigations"][0]["check_evidence_classes"],
                         {"validate": "INITIAL_ADVERSE_TRANSITION"})

    def test_without_history_original_fresh_regressions_still_work(self):
        report, _ = sample(missing=True)
        provider = Transport()
        result = investigate(report, api=GitHub(transport=provider), now=NOW)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["requests_used"], 4)
        self.assertEqual(result["investigations"][0]["check_names"],
                         ["audit", "validate"])
        self.assertEqual(result["investigations"][0]["check_evidence_classes"],
                         {
                             "validate": "INITIAL_ADVERSE_TRANSITION",
                             "audit": "RECOVERY_OBSERVED_NOT_RESOLUTION"
                         })

    def test_foreign_or_forged_original_ledger_fails_before_any_git_read(self):
        report, events = sample(missing=True)
        altered = copy.deepcopy(events)
        altered[-1]["payload"]["open_issues"] += 1
        provider = transport()
        with self.assertRaises(BrainError):
            self.run_case(report, altered, provider=provider)
        self.assertEqual(provider.calls, [])

    def test_revised_provider_source_never_closes_any_of_four_original_signals(self):
        report, history = sample(missing=True)
        provider = Transport(revision="c" * 40)
        receipt, provider = self.run_case(report, history, provider=provider)
        self.assertEqual(receipt["investigations"][0]["outcome"],
                         "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON")
        self.assertEqual(len(provider.calls), 4)
        public = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertFalse(public["root_cause_verified"])

    def test_mixed_repositories_respect_three_slot_budget_with_deferred(self):
        other_events = []
        for repository in (OTHER, THIRD, FOURTH):
            other_events += [
                fact(repository, T0, {"validate": "success"}),
                fact(repository, T1, {"validate": "failure"}),
            ]
        record, history = sample(missing=True)
        # Build a joint canonical ledger and report with all four sources.
        joint, events = verified(
            fact(REPO, T0, {"validate": "success", "persist": "failure",
                             "audit": "failure", "orphan": "success"}),
            fact(REPO, T1, {"validate": "failure", "persist": "failure",
                             "audit": "success"}),
            *other_events
        )
        result, provider = self.run_case(joint, events)
        self.assertEqual(result["eligible_count"], 4)
        self.assertEqual(result["deferred_count"], 1)
        self.assertEqual(len(result["investigations"]), 3)
        self.assertEqual(result["requests_used"], 12)
        self.assertEqual(len(provider.calls), 12)
        self.assertEqual(len({r["repository"] for r in result["investigations"]}), 3)
        self.assertEqual(result["github_mutations"], 0)


if __name__ == "__main__":
    unittest.main()
