"""Adversarial GitHub snapshot identity tests for the V5 GET-only monitor.

All provider responses are local stubs; no GitHub writes, real credentials,
schedulers, paid services, customers or production data.
"""
import tempfile
import unittest
from pathlib import Path

from brain.__main__ import monitor
from brain.adapters import GitHub, event
from brain.core import BrainError, Store
from brain.intelligence import validate_payload
from brain.projects import _check_evidence


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
    def test_monitor_accepts_actions_nonterminal_states_without_claiming_recovery(self):
        for status in ("queued", "in_progress", "waiting", "requested", "pending"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder:
                prior = check(1)
                prior["conclusion"] = "failure"
                payload, _ = GitHub(transport=Provider([prior])).observe(REPO)
                current = check(2)
                current.update(status=status, conclusion=None)
                api = GitHub(transport=Provider([current]))
                store = Store(Path(folder) / "state.sqlite", visibility="PUBLIC")
                try:
                    store.submit([event(
                        "repository", REPO, payload, SHA,
                        now="2026-10-09T15:00:00Z",
                    )])
                    store.drain()
                    report = monitor(
                        store, SHA, Path(folder) / "report", api=api,
                        repositories=[REPO],
                    )
                    self.assertEqual(report["operation"]["errors"], [])
                    self.assertEqual(store.pending(), 0)
                    self.assertEqual(report["state_sequence"], 2)
                    observed = report["repositories"][0]
                    self.assertEqual(observed["checks"][0]["status"], status)
                    self.assertIsNone(observed["checks"][0]["conclusion"])
                    self.assertEqual(
                        _check_evidence(observed),
                        "INCOMPLETE_OR_INCONCLUSIVE_CHECKS_OBSERVED",
                    )
                    change = report["repository_changes"][0]
                    self.assertEqual(change["check_recoveries"], [])
                    self.assertEqual(change["check_deteriorations"], [])
                    self.assertEqual(change["change_types"], [])
                    attempt = store.db.execute(
                        "SELECT status FROM attempts WHERE operation='monitor' "
                        "ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    self.assertEqual(attempt["status"], "PASS")
                    self.assertEqual(api.requests, 4)
                finally:
                    store.close()

    def test_unknown_or_malformed_check_status_remains_rejected(self):
        for status in (None, True, 0, "success", "expected", "waiting ", [], {}):
            with self.subTest(status=status):
                row = check(1)
                row.update(status=status, conclusion=None)
                payload, _ = GitHub(transport=Provider([row])).observe(REPO)
                with self.assertRaisesRegex(BrainError, "check status invalid"):
                    validate_payload("repository", payload, "2026-10-09T16:00:00Z")

    def test_nonterminal_status_with_a_conclusion_remains_rejected(self):
        for status in ("queued", "in_progress", "waiting", "requested", "pending"):
            for conclusion in ("success", "failure", "neutral", "cancelled", "skipped",
                               "timed_out", "action_required", "stale", "startup_failure"):
                with self.subTest(status=status, conclusion=conclusion):
                    row = check(1)
                    row.update(status=status, conclusion=conclusion)
                    payload, _ = GitHub(transport=Provider([row])).observe(REPO)
                    with self.assertRaisesRegex(BrainError, "nonterminal check has a conclusion"):
                        validate_payload("repository", payload, "2026-10-09T16:00:00Z")

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


class CheckHistoryCapacityTests(unittest.TestCase):
    def test_532_checks_survive_monitor_persistence_and_restart(self):
        rows = [check(i) for i in range(1, 533)]
        # Do not discard an adverse result on the last page.
        rows[-1]["conclusion"] = "failure"
        api = GitHub(transport=Provider(rows))
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "state.sqlite"
            store = Store(db, visibility="PUBLIC")
            try:
                report = monitor(store, SHA, Path(folder) / "report",
                                 api=api, repositories=[REPO])
                self.assertEqual(report["operation"]["errors"], [])
                self.assertEqual(len(report["repositories"][0]["checks"]), 532)
                self.assertEqual(api.requests, 9)
                self.assertEqual(store.pending(), 0)
            finally:
                store.close()
            restored = Store(db, visibility="PUBLIC")
            try:
                result = restored.report(SHA)
                checks = result["repositories"][0]["checks"]
                self.assertEqual(len(checks), 532)
                self.assertEqual(checks[-1]["conclusion"], "failure")
                self.assertEqual(restored.read_report(SHA)["canonical_hash"],
                                 result["canonical_hash"])
            finally:
                restored.close()

    def test_current_four_repository_load_fits_shared_budget(self):
        counts = [532, 119, 9, 17]
        providers = {}
        for index, count in enumerate(counts):
            providers[f"example/repo{index}"] = Provider(
                [check(i) for i in range(1, count + 1)])

        def transport(path):
            repo = "/".join(path.split("/")[2:4])
            result = providers[repo](path.replace(repo, REPO))
            if path == "/repos/" + repo:
                result["full_name"] = repo
            for row in result.get("check_runs", []):
                row["html_url"] = row["html_url"].replace(REPO, repo)
            return result

        api = GitHub(transport=transport)
        for repo, count in zip(providers, counts):
            payload, _ = api.observe(repo)
            validate_payload("repository", payload, "2026-10-26T16:00:00Z")
            self.assertEqual(len(payload["checks"]), count)
        self.assertEqual(api.requests, 22)

    def test_maximum_complete_snapshot_uses_exactly_24_requests(self):
        api = GitHub(transport=Provider([check(i) for i in range(1, 2101)]))
        payload, _ = api.observe(REPO)
        validate_payload("repository", payload, "2026-10-26T16:00:00Z")
        self.assertEqual(len(payload["checks"]), 2100)
        self.assertEqual(api.requests, 24)

    def test_over_capacity_fails_before_fetching_more_pages(self):
        for count, budget in ((2101, 24), (532, 8)):
            with self.subTest(count=count, budget=budget):
                provider = Provider([check(i) for i in range(1, count + 1)])
                api = GitHub(transport=provider, max_requests=budget)
                with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_BUDGET_EXCEEDED"):
                    api.observe(REPO)
                self.assertEqual(api.requests, 3)
                self.assertEqual(provider.calls.count(BRANCH), 1)

    def test_prior_reads_reduce_capacity_without_resetting_budget(self):
        api = GitHub(transport=Provider([check(i) for i in range(1, 533)]))
        api.requests = 16
        with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_BUDGET_EXCEEDED"):
            api.observe(REPO)
        self.assertEqual(api.requests, 19)

    def test_short_middle_page_cannot_be_compensated_by_long_final_page(self):
        provider = Provider([check(i) for i in range(1, 202)])
        def transport(path):
            result = provider(path)
            if path.endswith("&page=2"):
                result["check_runs"] = result["check_runs"][:-1]
            elif path.endswith("&page=3"):
                result["check_runs"].insert(0, check(200))
            return result
        with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_TRUNCATED"):
            GitHub(transport=transport).observe(REPO)
        self.assertFalse(any(path.endswith("&page=3") for path in provider.calls))

    def test_duplicate_cross_revision_and_count_drift_on_sixth_page_fail(self):
        for mutation in ("duplicate", "revision", "total", "shape"):
            with self.subTest(mutation=mutation):
                provider = Provider([check(i) for i in range(1, 533)])
                def transport(path):
                    result = provider(path)
                    if path.endswith("&page=6"):
                        if mutation == "duplicate": result["check_runs"][-1] = check(1)
                        elif mutation == "revision": result["check_runs"][-1] = check(532, revision=OTHER)
                        elif mutation == "total": result["total_count"] = 533
                        else: return []
                    return result
                with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_(AMBIGUOUS|CHANGED)"):
                    GitHub(transport=transport).observe(REPO)
                self.assertEqual(provider.calls.count(BRANCH), 1)

    def test_malformed_first_page_remains_rejected(self):
        for value in (None, [], {"total_count": True, "check_runs": []},
                      {"total_count": -1, "check_runs": []}):
            with self.subTest(value=value):
                provider = Provider()
                def transport(path):
                    return value if "/check-runs?" in path else provider(path)
                with self.assertRaisesRegex(BrainError, "CHECK_COVERAGE_UNAVAILABLE"):
                    GitHub(transport=transport).observe(REPO)

    def test_state_validator_rejects_history_beyond_collectable_bound(self):
        payload, _ = GitHub(transport=Provider([check(1)])).observe(REPO)
        payload["checks"] *= 2101
        with self.assertRaisesRegex(BrainError, "checks invalid"):
            validate_payload("repository", payload, "2026-10-26T16:00:00Z")


if __name__ == "__main__":
    unittest.main()
