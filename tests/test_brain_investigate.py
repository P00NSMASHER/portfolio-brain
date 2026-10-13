"""Autonomous read-only follow-up contracts; all provider responses are synthetic."""
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from brain.adapters import GitHub
from brain.core import BrainError, Store, digest
from brain.investigate import investigate, main

SOURCE = "a" * 40
REV = "b" * 40
NOW = "2026-10-12T16:00:00Z"
REPO = "P00NSMASHER/portfolio-brain"
OTHER = "P00NSMASHER/abvmschoolstarworld"
THIRD = "P00NSMASHER/trading-platform"


def comparison(repo=REPO):
    ref = f"https://github.com/{repo}/commit/{REV}"
    return {
        "repository": repo,
        "previous_observed_at": "2026-10-12T14:00:00Z",
        "current_observed_at": "2026-10-12T15:00:00Z",
        "previous_revision": REV, "current_revision": REV,
        "revision_changed": False,
        "open_issue_pr_tally": {"previous": 1, "current": 1, "net_delta": 0},
        "check_comparison": "COMPARABLE", "compared_check_names": 1,
        "check_deteriorations": [{
            "name": "validate", "from_conclusion": "success",
            "to_conclusion": "failure",
            "source_ref": f"https://github.com/{repo}/actions/runs/10/job/20",
        }],
        "check_recoveries": [], "change_types": ["CHECK_DETERIORATED"],
        "evidence_quality": "ACTUAL_FRESH", "source_refs": [ref, ref],
    }


def report(*repos):
    return {
        "schema_version": 2, "status": "PASS", "source_sha": SOURCE,
        "state_sequence": 2, "pending_events": 0,
        "repository_changes": [comparison(repo) for repo in (repos or (REPO,))],
        "reuse_candidates": [],
    }


class Transport:
    def __init__(self, *, conclusion="failure", revision=REV):
        self.calls = []
        self.conclusion = conclusion
        self.revision = revision
        self.private = False
        self.check_mutation = None
        self.branch_calls = 0
        self.branch_moves = False
        self.provider_error = False
        self.extra_checks = []

    def __call__(self, path):
        self.calls.append(path)
        if self.provider_error:
            raise BrainError("SECRET_SENTINEL: private transport diagnostic")
        parts = path.split("/")
        repo = "/".join(parts[2:4])
        if len(parts) == 4:
            return {"full_name": repo, "private": self.private,
                    "default_branch": "main", "open_issues_count": 1}
        if "/branches/" in path:
            self.branch_calls += 1
            sha = "c" * 40 if self.branch_moves and self.branch_calls % 2 == 0 else self.revision
            return {"commit": {"sha": sha}}
        if "/check-runs?" in path:
            check = {"id": 20, "name": "validate", "status": "completed",
                     "conclusion": self.conclusion, "head_sha": self.revision,
                     "html_url": f"https://github.com/{repo}/actions/runs/10/job/20"}
            if self.check_mutation:
                self.check_mutation(check)
            checks = [check] + copy.deepcopy(self.extra_checks)
            return {"total_count": len(checks), "check_runs": checks}
        raise AssertionError("Unexpected endpoint: " + path)


class AutonomousInvestigationTests(unittest.TestCase):
    def run_case(self, value=None, transport=None, **kwargs):
        transport = transport or Transport()
        api = GitHub(transport=transport)
        result = investigate(value or report(), api=api, now=NOW, **kwargs)
        return result, transport

    def test_actual_adapter_rechecks_failure_without_state_or_write_authority(self):
        value = report()
        before = copy.deepcopy(value)
        result, transport = self.run_case(value)
        self.assertEqual(result["status"], "READ_ONLY_REVALIDATION_COMPLETE")
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"], "STILL_ADVERSE")
        self.assertEqual(result["requests_used"], 4)
        self.assertEqual(len(transport.calls), 4)
        self.assertEqual(value, before)
        self.assertIs(result["execution_authority"], False)
        self.assertIs(result["root_cause_verified"], False)
        self.assertEqual(result["github_mutations"], 0)
        self.assertEqual(result["events_written"], 0)
        self.assertEqual(result["paid_calls"], 0)
        self.assertTrue(all(path.startswith("/repos/" + REPO) for path in transport.calls))

    def test_success_observation_does_not_close_or_claim_resolved_incident(self):
        result, _ = self.run_case(transport=Transport(conclusion="success"))
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"], "SUCCESS_OBSERVED_NOT_RESOLUTION")
        self.assertIs(result["root_cause_verified"], False)

    def test_new_revision_is_not_misclassified_as_recovery(self):
        result, _ = self.run_case(transport=Transport(conclusion="success", revision="c" * 40))
        row = result["investigations"][0]
        self.assertEqual(row["outcome"], "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON")
        self.assertEqual(row["checks"], [])

    def test_pending_check_is_not_classified_as_success(self):
        transport = Transport(conclusion=None)
        transport.check_mutation = lambda row: row.update(status="in_progress")
        result, _ = self.run_case(transport=transport)
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"], "CHECK_NOT_COMPLETED")

    def test_neutral_skipped_cancelled_are_not_resolutions(self):
        for conclusion in ("neutral", "skipped", "cancelled", None):
            with self.subTest(conclusion=conclusion):
                result, _ = self.run_case(transport=Transport(conclusion=conclusion))
                self.assertEqual(result["investigations"][0]["checks"][0]["outcome"], "OTHER_CONCLUSION_NOT_RESOLUTION")

    def test_missing_check_is_unverified(self):
        transport = Transport()
        transport.check_mutation = lambda row: row.update(name="unrelated")
        result, _ = self.run_case(transport=transport)
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"], "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK")

    def test_duplicate_names_with_distinct_run_ids_are_not_confirmation(self):
        transport = Transport()
        transport.extra_checks = [{"id": 21, "name": "validate", "status": "completed",
                                   "conclusion": "success", "head_sha": REV,
                                   "html_url": f"https://github.com/{REPO}/actions/runs/11/job/21"}]
        result, _ = self.run_case(transport=transport)
        self.assertEqual(result["investigations"][0]["checks"][0]["outcome"], "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK")

    def test_branch_race_is_incomplete_not_a_pass(self):
        transport = Transport()
        transport.branch_moves = True
        result, _ = self.run_case(transport=transport)
        self.assertEqual(result["status"], "INCOMPLETE_READ_ONLY_REVALIDATION")
        self.assertEqual(result["investigations"][0]["outcome"], "UNVERIFIED_READ_FAILED")

    def test_provider_errors_are_sanitized_and_stop_further_reads(self):
        transport = Transport()
        transport.provider_error = True
        result, transport = self.run_case(report(REPO, OTHER), transport)
        self.assertEqual(result["status"], "INCOMPLETE_READ_ONLY_REVALIDATION")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(result["deferred_count"], 1)
        self.assertNotIn("SECRET_SENTINEL", json.dumps(result))

    def test_public_mode_refuses_private_provider_metadata(self):
        transport = Transport()
        transport.private = True
        result, transport = self.run_case(transport=transport)
        self.assertEqual(result["status"], "INCOMPLETE_READ_ONLY_REVALIDATION")
        self.assertEqual(len(transport.calls), 1)

    def test_cross_revision_provider_check_identity_is_rejected(self):
        transport = Transport()
        transport.check_mutation = lambda row: row.update(head_sha="c" * 40)
        result, _ = self.run_case(transport=transport)
        self.assertEqual(result["status"], "INCOMPLETE_READ_ONLY_REVALIDATION")

    def test_input_order_does_not_change_work_selection_or_receipt(self):
        first, _ = self.run_case(report(REPO, OTHER, THIRD))
        second, _ = self.run_case(report(THIRD, OTHER, REPO))
        self.assertEqual(first, second)
        self.assertEqual(len(first["investigations"]), 3)
        self.assertEqual(first["requests_used"], 12)

    def test_fixed_item_bound_and_explicit_deferred_count(self):
        value = report(REPO, OTHER, THIRD, "P00NSMASHER/github-value-hunt-ledger")
        result, _ = self.run_case(value, max_investigations=2)
        self.assertEqual(len(result["investigations"]), 2)
        self.assertEqual(result["eligible_count"], 4)
        self.assertEqual(result["deferred_count"], 2)
        for limit in (0, 4, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(BrainError):
                self.run_case(value, max_investigations=limit)

    def test_insufficient_worst_case_budget_defers_without_requests(self):
        transport = Transport()
        api = GitHub(transport=transport)
        api.requests = 9
        result = investigate(report(), api=api, now=NOW)
        self.assertEqual(result["status"], "REQUEST_BUDGET_DEFERRED")
        self.assertEqual(result["requests_used"], 0)
        self.assertEqual(result["deferred_count"], 1)
        self.assertEqual(transport.calls, [])

    def test_stop_signal_is_honored_before_any_provider_read(self):
        result, transport = self.run_case(stop_requested=lambda: True)
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(transport.calls, [])

    def test_stop_signal_between_repositories_preserves_completed_evidence(self):
        transport = Transport()
        result, _ = self.run_case(report(REPO, OTHER), transport,
                                  stop_requested=lambda: len(transport.calls) >= 4)
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(len(result["investigations"]), 1)
        self.assertEqual(result["deferred_count"], 1)

    def test_stale_nonactual_and_external_repositories_never_trigger_reads(self):
        for kind in ("HISTORICAL", "NON_ACTUAL", "ACTUAL_STALE_BASELINE"):
            value = report()
            value["repository_changes"][0]["evidence_quality"] = kind
            result, transport = self.run_case(value)
            self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
            self.assertEqual(transport.calls, [])
        result, transport = self.run_case(report("other-owner/unapproved"))
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(transport.calls, [])

    def test_forged_fresh_label_cannot_override_real_timestamp_age(self):
        for value in ("2026-10-09T14:00:00Z", "2026-10-13T14:00:00Z"):
            source = report()
            source["repository_changes"][0]["previous_observed_at"] = value
            transport = Transport()
            with self.assertRaises(BrainError):
                self.run_case(source, transport)
            self.assertEqual(transport.calls, [])

    def test_bad_report_state_or_source_never_reaches_provider(self):
        for field, value in (("status", "FAIL"), ("pending_events", 1),
                             ("pending_events", False), ("schema_version", True),
                             ("source_sha", "unknown")):
            source = report()
            source[field] = value
            transport = Transport()
            with self.subTest(field=field), self.assertRaises(BrainError):
                self.run_case(source, transport)
            self.assertEqual(transport.calls, [])

    def test_all_selected_evidence_is_validated_before_first_read(self):
        source = report(REPO, OTHER)
        source["repository_changes"][1]["source_refs"][0] = "https://github.com/attacker/unbound"
        transport = Transport()
        with self.assertRaises(BrainError):
            self.run_case(source, transport)
        self.assertEqual(transport.calls, [])

    def test_duplicate_repository_evidence_is_rejected_before_reads(self):
        transport = Transport()
        with self.assertRaises(BrainError):
            self.run_case(report(REPO, REPO), transport)
        self.assertEqual(transport.calls, [])

    def test_nonfailure_source_code_queue_never_executes_discovered_code(self):
        value = report()
        value["repository_changes"] = []
        result, transport = self.run_case(value)
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(transport.calls, [])


class InvestigationCliTests(unittest.TestCase):
    def make_state(self, path):
        with patch("brain.core.utcnow", return_value=NOW):
            store = Store(path, visibility="PUBLIC")
            try:
                for index, conclusion in enumerate(("success", "failure")):
                    payload = {"repository": REPO, "head_sha": REV,
                               "default_branch": "main", "open_issues": 1,
                               "source_ref": f"https://github.com/{REPO}/commit/{REV}",
                               "checks": [{"name": "validate", "status": "completed",
                                           "conclusion": conclusion, "head_sha": REV,
                                           "url": f"https://github.com/{REPO}/actions/runs/10/job/20"}]}
                    observation = {"id": "", "kind": "repository", "key": REPO,
                                   "observed_at": f"2026-10-12T{14 + index}:00:00Z",
                                   "source_sha": SOURCE, "visibility": "PUBLIC",
                                   "data_kind": "ACTUAL", "payload": payload}
                    observation["id"] = "repository:" + digest(observation)
                    store.submit([observation])
                    store.drain()
                store.report(SOURCE)
            finally:
                store.close()

    def test_cli_reads_original_without_mutation_and_writes_private_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "state.sqlite"
            self.make_state(database)
            before = (hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns, database.stat().st_mode)
            api = GitHub(transport=Transport())
            with patch("brain.__main__.source_sha", return_value=SOURCE), \
                 patch("brain.core.utcnow", return_value=NOW), \
                 patch("brain.investigate.utcnow", return_value=NOW), \
                 patch("brain.investigate.GitHub", return_value=api), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = main(["--db", str(database), "--expected-sha", SOURCE, "--output", str(root / "receipt")])
            self.assertEqual(result, 0)
            after = (hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns, database.stat().st_mode)
            self.assertEqual(before, after)
            receipt = json.loads((root / "receipt" / "report.json").read_text())
            self.assertEqual(receipt["investigations"][0]["checks"][0]["outcome"], "STILL_ADVERSE")
            self.assertEqual(os.stat(root / "receipt").st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(root / "receipt" / "report.json").st_mode & 0o777, 0o600)

    def test_missing_state_is_not_bootstrapped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.sqlite"
            with patch("brain.__main__.source_sha", return_value=SOURCE), \
                 patch("brain.investigate.GitHub") as provider, \
                 redirect_stderr(io.StringIO()):
                result = main(["--db", str(path), "--output", str(Path(folder) / "out")])
            self.assertEqual(result, 1)
            self.assertFalse(path.exists())
            provider.assert_not_called()

    def test_output_cannot_replace_the_original_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            self.make_state(path)
            before = path.read_bytes()
            with patch("brain.__main__.source_sha", return_value=SOURCE), \
                 patch("brain.investigate.GitHub") as provider, \
                 redirect_stderr(io.StringIO()):
                result = main(["--db", str(path), "--output", folder])
            self.assertEqual(result, 1)
            self.assertEqual(path.read_bytes(), before)
            provider.assert_not_called()

    def test_expired_canonical_report_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite"
            self.make_state(path)
            before = path.read_bytes()
            with patch("brain.__main__.source_sha", return_value=SOURCE), \
                 patch("brain.core.utcnow", return_value="2026-10-15T16:00:00Z"), \
                 patch("brain.investigate.GitHub") as provider, \
                 redirect_stderr(io.StringIO()):
                result = main(["--db", str(path), "--output", str(Path(folder) / "out")])
            self.assertEqual(result, 1)
            self.assertEqual(path.read_bytes(), before)
            provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
