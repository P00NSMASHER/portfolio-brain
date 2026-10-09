"""Regressions for deterministic portfolio movement, not speculative alerts."""
import json
import tempfile
import unittest
from pathlib import Path

from brain.adapters import event
from brain.core import BrainError, Store, canonical, digest
from brain.render import write_report

CODE_SHA = "a" * 40
REV_A = "b" * 40
REV_B = "c" * 40
T0 = "2026-10-08T18:00:00Z"
T1 = "2026-10-08T19:00:00Z"
T2 = "2026-10-08T20:00:00Z"
NOW = "2026-10-08T20:05:00Z"
REPO = "example/project"


def check(name="Foundation", status="completed", conclusion="success", sha=REV_A):
    return {
        "name": name, "status": status, "conclusion": conclusion,
        "head_sha": sha,
        "url": f"https://github.com/{REPO}/actions/runs/123",
    }


def observation(when, *, revision=REV_A, tally=3, checks=None,
                data_kind="ACTUAL", code_sha=CODE_SHA):
    payload = {
        "repository": REPO,
        "head_sha": revision,
        "default_branch": "main",
        "checks": [check(sha=revision)] if checks is None else checks,
        "open_issues": tally,
        "source_ref": f"https://github.com/{REPO}/commit/{revision}",
    }
    return event("repository", REPO, payload, code_sha, now=when,
                 data_kind=data_kind)


class RepositoryChangeEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.store = Store(self.dir / "state.sqlite", visibility="PUBLIC")
        self.addCleanup(self.store.close)

    def ingest(self, *observations):
        self.store.submit(list(observations), now=NOW)
        self.store.drain()

    def report(self, *, now=NOW, max_age=172800):
        return self.store.report(CODE_SHA, now=now, max_age=max_age)

    def test_first_snapshot_has_no_false_change_or_alert(self):
        self.ingest(observation(T1))
        result = self.report()
        self.assertEqual(result["repository_changes"], [])
        self.assertEqual(self.store.read_report(CODE_SHA, now=NOW), result)

    def test_revision_change_and_tracker_tally_do_not_claim_check_regression(self):
        self.ingest(
            observation(T0, tally=3),
            observation(T1, revision=REV_B, tally=5,
                        checks=[check(conclusion="failure", sha=REV_B)]),
        )
        result = self.report()
        change = result["repository_changes"][0]
        self.assertTrue(change["revision_changed"])
        self.assertEqual(change["change_types"],
                         ["REVISION_CHANGED", "OPEN_TRACKER_TALLY_CHANGED"])
        self.assertEqual(change["open_issue_pr_tally"]["net_delta"], 2)
        self.assertIn("INCLUDES_PULL_REQUESTS", change["open_issue_pr_tally"]["definition"])
        self.assertEqual(change["check_comparison"], "REVISION_CHANGED")
        self.assertEqual(change["check_deteriorations"], [])
        self.assertEqual(change["evidence_quality"], "ACTUAL_FRESH")
        self.assertEqual(self.store.read_report(CODE_SHA, now=NOW), result)

    def test_same_sha_terminal_check_deterioration_and_recovery(self):
        self.ingest(
            observation(T0),
            observation(T1, checks=[check(conclusion="failure")]),
        )
        change = self.report()["repository_changes"][0]
        self.assertEqual(change["change_types"], ["CHECK_DETERIORATED"])
        self.assertEqual(change["check_comparison"], "COMPARABLE")
        self.assertEqual(change["compared_check_names"], 1)
        self.assertEqual(change["check_deteriorations"][0]["name"], "Foundation")
        self.ingest(observation(T2))
        change = self.report()["repository_changes"][0]
        self.assertEqual(change["change_types"], ["CHECK_RECOVERED"])
        self.assertEqual(len(change["check_recoveries"]), 1)
        self.assertEqual(change["previous_observed_at"], T1)
        self.assertEqual(change["current_observed_at"], T2)

    def test_pending_or_disappearing_checks_never_imply_recovery(self):
        self.ingest(
            observation(T0, checks=[check(conclusion="failure")]),
            observation(T1, checks=[check(status="in_progress", conclusion=None)]),
        )
        change = self.report()["repository_changes"][0]
        self.assertEqual(change["check_recoveries"], [])
        self.assertEqual(change["change_types"], [])
        self.ingest(observation(T2, checks=[]))
        change = self.report()["repository_changes"][0]
        self.assertEqual(change["check_comparison"], "NO_SHARED_CHECK_NAMES")
        self.assertEqual(change["change_types"], [])

    def test_duplicate_check_names_are_ambiguous_not_regressed(self):
        self.ingest(
            observation(T0, checks=[check()]),
            observation(T1, checks=[
                check(conclusion="failure"),
                check(conclusion="failure"),
            ]),
        )
        change = self.report()["repository_changes"][0]
        self.assertEqual(change["check_comparison"], "PARTIAL_AMBIGUOUS_CHECK_NAMES")
        self.assertEqual(change["compared_check_names"], 0)
        self.assertEqual(change["check_deteriorations"], [])

    def test_out_of_order_delivery_uses_semantic_time_not_insert_order(self):
        self.ingest(observation(T1, tally=7), observation(T2, tally=8))
        self.ingest(observation(T0, tally=1))
        change = self.report()["repository_changes"][0]
        self.assertEqual(change["previous_observed_at"], T1)
        self.assertEqual(change["current_observed_at"], T2)
        self.assertEqual(change["open_issue_pr_tally"]["net_delta"], 1)

    def test_replayed_same_time_same_fact_is_not_a_second_sample(self):
        self.ingest(
            observation(T1),
            observation(T1, code_sha="d" * 40),
        )
        self.assertEqual(self.report()["repository_changes"], [])

    def test_old_same_time_conflict_is_rejected_at_ingestion(self):
        self.ingest(observation(T0, tally=1), observation(T1, tally=3))
        # The existing canonical write guard already catches this conflict,
        # even though a newer observation has since arrived.
        with self.assertRaisesRegex(BrainError, "AMBIGUOUS_OBSERVATION"):
            self.ingest(observation(T0, tally=2))
        result = self.report()
        self.assertEqual(result["repository_changes"][0]["open_issue_pr_tally"]["net_delta"], 2)
        self.assertEqual(result["state_sequence"], 2)

    def test_synthetic_and_stale_observations_cannot_claim_fresh_actual(self):
        self.ingest(
            observation(T0),
            observation(T1, tally=4, data_kind="SIMULATED"),
        )
        change = self.report()["repository_changes"][0]
        self.assertEqual(change["evidence_quality"], "NON_ACTUAL")
        self.assertEqual(change["open_issue_pr_tally"]["net_delta"], 1)

        separate = Store(self.dir / "stale.sqlite", visibility="PUBLIC")
        self.addCleanup(separate.close)
        separate.submit([observation(T0), observation(T1)], now=NOW)
        separate.drain()
        stale = separate.report(CODE_SHA, now="2026-10-08T22:00:00Z",
                                max_age=3600)
        self.assertEqual(stale["status"], "BLOCKED")
        self.assertEqual(stale["repository_changes"][0]["evidence_quality"], "HISTORICAL")

    def test_rehashed_fabricated_change_cannot_survive_independent_replay(self):
        self.ingest(observation(T0), observation(T1, tally=4))
        report = self.report()
        report["repository_changes"][0]["open_issue_pr_tally"]["net_delta"] = 999
        self.store.db.execute(
            "UPDATE reports SET body=?,hash=? WHERE id=1",
            (canonical(report), digest(report)),
        )
        with self.assertRaisesRegex(BrainError, "deterministic ledger replay"):
            self.store.read_report(CODE_SHA, now=NOW)

    def test_markdown_and_html_explain_limits(self):
        self.ingest(observation(T0), observation(T1, tally=4))
        report = self.report()
        write_report(report, self.dir / "report")
        markdown = (self.dir / "report" / "report.md").read_text()
        html = (self.dir / "report" / "report.html").read_text()
        machine = json.loads((self.dir / "report" / "report.json").read_text())
        self.assertIn("Repository changes since prior observation", markdown)
        self.assertIn("tally +1", markdown)
        self.assertIn("includes pull requests", markdown)
        self.assertIn("OBSERVED_DIFFERENCES_NOT_CAUSATION", str(machine))
        self.assertIn("Repository changes since prior observation", html)


if __name__ == "__main__":
    unittest.main()
