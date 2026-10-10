"""Adversarial GitHub snapshot identity tests for the V5 GET-only monitor.

All provider responses are local stubs; no GitHub writes, real credentials,
schedulers, paid services, customers or production data.
"""
import tempfile
import unittest
from pathlib import Path

from brain.__main__ import monitor
from brain.adapters import GitHub
from brain.core import BrainError, Store
from brain.intelligence import validate_payload


REPO = "example/repository"
SHA = "a" * 40
OTHER = "b" * 40
ROOT = "/repos/" + REPO
BRANCH = ROOT + "/branches/main"
CHECKS = ROOT + "/commits/" + SHA + "/check-runs?per_page=100"


def check(run_id, *, revision=SHA):
    return {
        "id": run_id,
        "name": "validate",
        "status": "completed",
        "conclusion": "success",
        "head_sha": revision,
        "html_url": f"https://github.com/{REPO}/runs/{run_id}",
    }


class Provider:
    def __init__(self, rows=(), branch_heads=(SHA, SHA), page_totals=None):
        self.rows = list(rows)
        self.branch_heads = list(branch_heads)
        self.calls = []
        self.page_totals = page_totals or {}

    def __call__(self, path):
        self.calls.append(path)
        if path == ROOT:
            return {
                "full_name": REPO, "private": False,
                "default_branch": "main", "open_issues_count": 4,
            }
        if path == BRANCH:
            position = self.calls.count(BRANCH) - 1
            if position >= len(self.branch_heads):
                raise AssertionError("unexpected provider branch reread")
            return {"commit": {"sha": self.branch_heads[position]}}
        if path.startswith(CHECKS):
            page = int(path.split("&page=", 1)[1]) if "&page=" in path else 1
            return {
                "total_count": self.page_totals.get(page, len(self.rows)),
                "check_runs": self.rows[(page - 1) * 100:page * 100],
            }
        raise AssertionError("unexpected endpoint: " + path)


class GitHubSnapshotIntegrityTests(unittest.TestCase):
    def test_stable_two_check_snapshot_is_accepted_and_branch_is_rechecked(self):
        provider = Provider([check(1), check(2)])
        api = GitHub(transport=provider)
        result, private = api.observe(REPO)
        self.assertFalse(private)
        self.assertEqual(api.requests, 4)
        self.assertEqual(provider.calls, [ROOT, BRANCH, CHECKS, BRANCH])
        self.assertEqual(result["head_sha"], SHA)
        self.assertEqual(len(result["checks"]), 2)
        validate_payload("repository", result, "2026-10-09T16:00:00Z")

    def test_empty_checks_still_verify_the_branch_identity(self):
        provider = Provider()
        result, _ = GitHub(transport=provider).observe(REPO)
        self.assertEqual(result["checks"], [])
        self.assertEqual(provider.calls.count(BRANCH), 2)

    def test_duplicate_provider_check_id_on_single_page_is_refused(self):
        provider = Provider([check(5), check(5)])
        api = GitHub(transport=provider)
        with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_AMBIGUOUS"):
            api.observe(REPO)
        self.assertEqual(api.requests, 3)
        self.assertEqual(provider.calls.count(BRANCH), 1)

    def test_malformed_provider_check_identity_is_refused_for_small_samples(self):
        for value in (None, True, 0, -1, 1.5, "1"):
            with self.subTest(run_id=value):
                provider = Provider([check(value)])
                with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_AMBIGUOUS"):
                    GitHub(transport=provider).observe(REPO)

    def test_cross_revision_check_run_is_not_trusted(self):
        provider = Provider([check(10), check(11, revision=OTHER)])
        with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_AMBIGUOUS"):
            GitHub(transport=provider).observe(REPO)

    def test_duplicate_provider_ids_across_two_pages_are_refused(self):
        provider = Provider([check(i) for i in range(1, 101)] + [check(1)])
        with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_AMBIGUOUS"):
            GitHub(transport=provider).observe(REPO)
        self.assertEqual(provider.calls.count(BRANCH), 1)

    def test_branch_movement_after_check_fetch_blocks_entire_snapshot(self):
        provider = Provider([check(12)], branch_heads=(SHA, OTHER))
        api = GitHub(transport=provider)
        with self.assertRaisesRegex(BrainError, "SOURCE_REVISION_CHANGED"):
            api.observe(REPO)
        self.assertEqual(provider.calls.count(BRANCH), 2)
        self.assertEqual(api.requests, 4)

    def test_unavailable_final_branch_identity_cannot_verify_freshness(self):
        provider = Provider([check(12)], branch_heads=(SHA, None))
        with self.assertRaisesRegex(BrainError, "SOURCE_REVISION_CHANGED"):
            GitHub(transport=provider).observe(REPO)

    def test_all_five_pages_have_exact_identity_and_stay_within_budget(self):
        provider = Provider([check(i) for i in range(1, 501)])
        api = GitHub(transport=provider)
        result, _ = api.observe(REPO)
        self.assertEqual(len(result["checks"]), 500)
        self.assertEqual(api.requests, 8)
        self.assertEqual(provider.calls.count(BRANCH), 2)
        validate_payload("repository", result, "2026-10-09T16:00:00Z")

    def test_mutated_pagination_total_fails_without_branch_certification(self):
        provider = Provider(
            [check(i) for i in range(1, 102)],
            page_totals={1: 101, 2: 102},
        )
        with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_CHANGED"):
            GitHub(transport=provider).observe(REPO)
        self.assertEqual(provider.calls.count(BRANCH), 1)

    def test_monitor_retains_no_claim_on_branch_race(self):
        provider = Provider([check(8)], branch_heads=(SHA, OTHER))
        api = GitHub(transport=provider)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "state.sqlite", visibility="PUBLIC")
            try:
                with self.assertRaisesRegex(BrainError, "MONITOR_INCOMPLETE"):
                    monitor(
                        store, SHA, Path(folder) / "report", api=api,
                        repositories=[REPO],
                    )
                self.assertEqual(store.pending(), 0)
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM events").fetchone()[0],
                    0,
                )
                attempt = store.db.execute(
                    "SELECT status FROM attempts "
                    "WHERE operation='monitor' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                self.assertEqual(attempt["status"], "FAIL")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
