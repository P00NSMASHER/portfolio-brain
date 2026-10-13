"""V7 continued adverse-check and observed-recovery follow-up (all synthetic)."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.adapters import GitHub, event
from brain.core import BrainError, Store
from brain.investigate import investigate
from test_brain_investigate import Transport, NOW, REPO, OTHER, THIRD, SOURCE, REV

T0 = "2026-10-12T14:00:00Z"
T1 = "2026-10-12T15:00:00Z"
FOURTH = "P00NSMASHER/github-value-hunt-ledger"


def snapshot(repo=REPO, when=T0, conclusion="failure", *, sha=REV,
             data_kind="ACTUAL", status="completed", duplicate=False):
    check = {
        "name": "validate", "status": status, "conclusion": conclusion,
        "head_sha": sha,
        "url": f"https://github.com/{repo}/actions/runs/10/job/20",
    }
    payload = {
        "repository": repo, "head_sha": sha, "default_branch": "main",
        "open_issues": 1, "source_ref": f"https://github.com/{repo}/commit/{sha}",
        "checks": [check, dict(check)] if duplicate else [check],
    }
    return event("repository", repo, payload, SOURCE, now=when, data_kind=data_kind)


class ContinuedEvidenceTests(unittest.TestCase):
    def report_events(self, *records):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "state.sqlite", visibility="PUBLIC")
            try:
                store.submit(list(records), now=NOW)
                store.drain()
                report = store.report(SOURCE, now=NOW)
                history, seq, chain = store._verified_events()
                self.assertEqual(seq, report["state_sequence"])
                self.assertEqual(chain, report["canonical_hash"])
                self.assertEqual(store.read_report(SOURCE, now=NOW), report)
            finally:
                store.close()
        return report, history

    def run_case(self, report, events, *, transport=None, **kwargs):
        transport = transport or Transport()
        result = investigate(report, history=events, api=GitHub(transport=transport),
                             now=NOW, **kwargs)
        return result, transport

    def test_two_distinct_actual_adverse_checks_continue_read_only_followup(self):
        report, events = self.report_events(
            snapshot(when=T0, conclusion="failure"),
            snapshot(when=T1, conclusion="failure"),
        )
        self.assertEqual(report["repository_changes"][0]["check_deteriorations"], [])
        before_report, before_history = copy.deepcopy(report), copy.deepcopy(events)
        receipt, transport = self.run_case(report, events)
        self.assertEqual(receipt["status"], "READ_ONLY_REVALIDATION_COMPLETE")
        self.assertEqual(receipt["eligible_count"], 1)
        row = receipt["investigations"][0]
        self.assertEqual(row["follow_up_kind"], "PERSISTENT_ADVERSE_OBSERVED")
        self.assertEqual(row["checks"][0]["outcome"], "STILL_ADVERSE")
        self.assertEqual(receipt["requests_used"], 4)
        self.assertEqual(receipt["github_mutations"], 0)
        self.assertEqual(receipt["events_written"], 0)
        self.assertEqual(receipt["paid_calls"], 0)
        self.assertFalse(receipt["root_cause_verified"])
        self.assertEqual(report, before_report)
        self.assertEqual(events, before_history)
        self.assertEqual(len(transport.calls), 4)

    def test_recovery_is_rechecked_but_never_establishes_resolution(self):
        report, history = self.report_events(
            snapshot(when=T0, conclusion="failure"),
            snapshot(when=T1, conclusion="success"),
        )
        receipt, transport = self.run_case(report, history, transport=Transport(conclusion="success"))
        row = receipt["investigations"][0]
        self.assertEqual(row["follow_up_kind"], "RECOVERY_OBSERVED_NOT_RESOLUTION")
        self.assertEqual(row["checks"][0]["outcome"], "SUCCESS_OBSERVED_NOT_RESOLUTION")
        self.assertFalse(receipt["root_cause_verified"])
        self.assertEqual(len(transport.calls), 4)

    def test_false_recovery_remains_adverse_and_new_source_requires_comparison(self):
        report, history = self.report_events(
            snapshot(when=T0, conclusion="failure"),
            snapshot(when=T1, conclusion="success"),
        )
        receipt, _ = self.run_case(report, history, transport=Transport(conclusion="failure"))
        self.assertEqual(receipt["investigations"][0]["checks"][0]["outcome"], "STILL_ADVERSE")
        receipt, _ = self.run_case(report, history, transport=Transport(revision="c" * 40))
        self.assertEqual(receipt["investigations"][0]["outcome"],
                         "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON")

    def test_new_deterioration_outranks_persistent_and_recovery(self):
        report, history = self.report_events(
            snapshot(REPO, T0, "failure"), snapshot(REPO, T1, "failure"),
            snapshot(OTHER, T0, "success"), snapshot(OTHER, T1, "failure"),
            snapshot(THIRD, T0, "failure"), snapshot(THIRD, T1, "success"),
        )
        receipt, _ = self.run_case(report, history)
        names = [r["repository"] for r in receipt["investigations"]]
        self.assertEqual(names, [OTHER, REPO, THIRD])
        self.assertEqual(receipt["eligible_count"], 3)
        self.assertEqual(receipt["requests_used"], 12)
        # Existing transition path keeps existing trusted human review semantics.
        self.assertNotIn("follow_up_kind", receipt["investigations"][0])

    def test_four_repositories_are_bounded_with_visible_deferral(self):
        records = []
        for repo in (FOURTH, REPO, THIRD, OTHER):
            records.extend((snapshot(repo,T0,"failure"),snapshot(repo,T1,"failure")))
        report, history = self.report_events(*records)
        receipt, _ = self.run_case(report, history)
        self.assertEqual(receipt["eligible_count"], 4)
        self.assertEqual(len(receipt["investigations"]), 3)
        self.assertEqual(receipt["deferred_count"], 1)
        self.assertEqual(receipt["status"],
                         "BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED")

    def test_initial_deterioration_and_simultaneous_recovery_share_one_read(self):
        def mixed(when, validate, audit):
            data = copy.deepcopy(snapshot(when=when, conclusion=validate)["payload"])
            data["checks"].append({
                "name": "audit", "status": "completed", "conclusion": audit,
                "head_sha": REV,
                "url": f"https://github.com/{REPO}/actions/runs/11/job/21",
            })
            return event("repository", REPO, data, SOURCE, now=when)
        report, history = self.report_events(
            mixed(T0, "success", "failure"),
            mixed(T1, "failure", "success"),
        )
        change = report["repository_changes"][0]
        self.assertEqual(len(change["check_deteriorations"]), 1)
        self.assertEqual(len(change["check_recoveries"]), 1)
        transport = Transport(conclusion="failure")
        transport.extra_checks = [{
            "id": 21, "name": "audit", "status": "completed",
            "conclusion": "success", "head_sha": REV,
            "html_url": f"https://github.com/{REPO}/actions/runs/11/job/21",
        }]
        receipt, transport = self.run_case(report, history, transport=transport)
        checks = {row["name"]: row["outcome"] for row in receipt["investigations"][0]["checks"]}
        self.assertEqual(checks, {
            "audit": "SUCCESS_OBSERVED_NOT_RESOLUTION",
            "validate": "STILL_ADVERSE",
        })
        self.assertEqual(receipt["eligible_count"], 1)
        self.assertEqual(len(transport.calls), 4)
        self.assertEqual(receipt["requests_used"], 4)

    def test_long_lived_four_repo_failures_rotate_without_starvation(self):
        records = []
        for repo in (FOURTH, REPO, THIRD, OTHER):
            records.extend((snapshot(repo,T0,"failure"),snapshot(repo,T1,"failure")))
        report, history = self.report_events(*records)
        skipped = set()
        for hour in (16, 17, 18, 19):
            current = f"2026-10-12T{hour:02d}:00:00Z"
            result = investigate(report, history=history, api=GitHub(transport=Transport()),
                                 now=current)
            self.assertEqual(result["eligible_count"], 4)
            self.assertEqual(len(result["investigations"]), 3)
            self.assertEqual(result["deferred_count"], 1)
            self.assertEqual(result["requests_used"], 12)
            found = {row["repository"] for row in result["investigations"]}
            skipped |= {FOURTH, REPO, THIRD, OTHER} - found
        self.assertEqual(skipped, {FOURTH, REPO, THIRD, OTHER})

    def test_nonactual_pending_ambiguous_and_changed_revisions_never_promote(self):
        cases = [
            (snapshot(when=T0), snapshot(when=T1,data_kind="SIMULATED")),
            (snapshot(when=T0), snapshot(when=T1,duplicate=True)),
            (snapshot(when=T0), snapshot(when=T1,sha="c" * 40)),
            (snapshot(when="2026-10-09T14:00:00Z"), snapshot(when=T1)),
        ]
        for pair in cases:
            with self.subTest(pair=pair[1]["payload"]):
                report, history = self.report_events(*pair)
                receipt, transport = self.run_case(report, history)
                self.assertEqual(receipt["status"], "NO_ELIGIBLE_FAILURES")
                self.assertEqual(transport.calls, [])

    def test_missing_or_forged_history_rejects_before_provider_access(self):
        report, history = self.report_events(snapshot(when=T0), snapshot(when=T1))
        for forged in (history[:1], list(reversed(history)),
                       [{**history[0], "key": OTHER}, history[1]]):
            transport = Transport()
            with self.subTest(history=forged), self.assertRaises(BrainError):
                self.run_case(report, forged, transport=transport)
            self.assertEqual(transport.calls, [])

    def test_old_pure_investigation_without_history_still_unchanged(self):
        report, history = self.report_events(snapshot(when=T0), snapshot(when=T1))
        transport = Transport()
        result = investigate(report, api=GitHub(transport=transport), now=NOW)
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(transport.calls, [])

    def test_history_disagreement_on_second_repository_fails_atomically(self):
        report, history = self.report_events(
            snapshot(REPO, T0), snapshot(REPO, T1),
            snapshot(OTHER, T0), snapshot(OTHER, T1),
        )
        altered = copy.deepcopy(report)
        altered["repository_changes"][1]["source_refs"][1] = "https://github.com/attacker/mismatched"
        transport = Transport()
        with self.assertRaises(BrainError):
            self.run_case(altered, history, transport=transport)
        self.assertEqual(transport.calls, [])

    def test_unrelated_code_never_executes_and_shields_policy(self):
        report, history = self.report_events(snapshot(when=T0),snapshot(when=T1))
        transport=Transport()
        result,_=self.run_case(report, history, transport=transport,
                               stop_requested=lambda: True)
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(transport.calls, [])


class SidecarClassificationTests(unittest.TestCase):
    report_events = ContinuedEvidenceTests.report_events
    run_case = ContinuedEvidenceTests.run_case
    def test_only_bounded_safe_followup_kinds_appear_in_public_summary(self):
        from brain.sidecar import summarize
        data, history = self.report_events(
            snapshot(when=T0), snapshot(when=T1))
        receipt, _ = self.run_case(data, history)
        result = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(result["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(result["observed_followup_kinds"],
                         {"PERSISTENT_ADVERSE_OBSERVED": 1})
        self.assertNotIn(REPO, str(result))
        self.assertFalse(result["root_cause_verified"])

        data, history = self.report_events(
            snapshot(when=T0, conclusion="failure"),
            snapshot(when=T1, conclusion="success"))
        receipt, _ = self.run_case(data, history, transport=Transport(conclusion="success"))
        result = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(result["observed_followup_kinds"],
                         {"RECOVERY_OBSERVED_NOT_RESOLUTION": 1})
        receipt["investigations"][0]["follow_up_kind"] = "EXECUTE_UNAUTHORIZED_ACTION"
        result = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(result["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")


class RealContinuationCliTests(unittest.TestCase):
    @unittest.skipUnless(__import__("os").name == "posix", "POSIX private report safety")
    def test_original_sqlite_preserved_and_private_persistent_receipt_created(self):
        import hashlib
        import io
        import json
        from contextlib import redirect_stdout, redirect_stderr
        from brain.investigate import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.sqlite"
            store = Store(original, visibility="PUBLIC")
            try:
                store.submit([snapshot(when=T0, conclusion="failure"),
                              snapshot(when=T1, conclusion="failure")], now=NOW)
                store.drain()
                store.report(SOURCE, now=NOW)
            finally:
                store.close()
            before = (hashlib.sha256(original.read_bytes()).hexdigest(),
                      original.stat().st_mtime_ns, original.stat().st_mode)
            fake = GitHub(transport=Transport())
            with patch("brain.__main__.source_sha", return_value=SOURCE), \
                 patch("brain.core.utcnow", return_value=NOW), \
                 patch("brain.investigate.utcnow", return_value=NOW), \
                 patch("brain.investigate.GitHub", return_value=fake), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main(["--db", str(original), "--expected-sha", SOURCE,
                             "--output", str(root / "followup")])
            self.assertEqual(code, 0)
            after = (hashlib.sha256(original.read_bytes()).hexdigest(),
                     original.stat().st_mtime_ns, original.stat().st_mode)
            self.assertEqual(before, after)
            receipt = json.loads((root / "followup" / "report.json").read_text())
            self.assertEqual(receipt["investigations"][0]["follow_up_kind"],
                             "PERSISTENT_ADVERSE_OBSERVED")
            self.assertEqual(receipt["investigations"][0]["checks"][0]["outcome"],
                             "STILL_ADVERSE")
            self.assertEqual(receipt["events_written"], 0)
            self.assertEqual(len(fake.transport.calls), 4)
            self.assertEqual((root / "followup").stat().st_mode & 0o777, 0o700)



if __name__ == "__main__":
    unittest.main()
