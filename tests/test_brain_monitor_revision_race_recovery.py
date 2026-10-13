"""Synthetic tests: bounded V7 monitor recovery from a moving Git branch."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from brain.__main__ import monitor
from brain.adapters import GitHub
from brain.core import BrainError, Store
from brain.monitor_resilience import observe_after_bounded_revision_race
from test_brain_source_snapshot import REPO, SHA, OTHER

ROOT = "/repos/" + REPO
BRANCH = ROOT + "/branches/main"


class MovingHead:
    def __init__(self, heads=(SHA, OTHER, OTHER, OTHER), fail=None, size=1):
        self.heads = heads
        self.calls = []
        self.fail = fail
        self.size = size

    def __call__(self, path):
        self.calls.append(path)
        if self.fail:
            raise BrainError(self.fail)
        if path == ROOT:
            return {"full_name": REPO, "private": False,
                    "default_branch": "main", "open_issues_count": 0}
        if path == BRANCH:
            number = self.calls.count(BRANCH)
            if number > len(self.heads):
                raise AssertionError("Excessive branch observation")
            return {"commit": {"sha": self.heads[number-1]}}
        if "/check-runs?" in path:
            sha = path.split("/commits/")[1].split("/check-runs?")[0]
            page = int(path.split("&page=")[1]) if "&page=" in path else 1
            items = [{"id": n, "name": f"check-{n}", "status": "completed",
                      "conclusion": "success", "head_sha": sha,
                      "html_url": f"https://github.com/{REPO}/runs/{n}"}
                     for n in range(1, self.size+1)]
            return {"total_count": self.size,
                    "check_runs": items[(page-1)*100:page*100]}
        raise AssertionError("Unknown GET route")


class RevisionRetryTests(unittest.TestCase):
    def run_public(self, provider, injected=False):
        api = GitHub(transport=provider)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/"state.sqlite", visibility="PUBLIC")
            try:
                output = Path(tmp)/"report"
                if injected:
                    report = monitor(store, SHA, output,
                                     api=api, repositories=[REPO])
                else:
                    with patch("brain.__main__.GitHub", return_value=api):
                        report = monitor(store, SHA, output,
                                         repositories=[REPO])
                events = [json.loads(row["body"]) for row in
                          store.db.execute("SELECT body FROM events")]
                return report, events, api.requests
            finally:
                store.close()

    def test_one_race_restarts_from_new_commit_without_partial_event(self):
        report, events, requests = self.run_public(MovingHead())
        self.assertEqual(requests, 8)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["head_sha"], OTHER)
        self.assertEqual(events[0]["source_sha"], SHA)
        self.assertEqual(report["operation"]["source_revision_rechecks"], [REPO])
        self.assertEqual(report["operation"]["errors"], [])

    def test_stable_source_uses_only_original_four_gets(self):
        report, events, requests = self.run_public(MovingHead((SHA, SHA)))
        self.assertEqual(requests, 4)
        self.assertEqual(events[0]["payload"]["head_sha"], SHA)
        self.assertEqual(report["operation"]["source_revision_rechecks"], [])

    def test_second_race_still_fails_after_one_bounded_recheck(self):
        api = GitHub(transport=MovingHead((SHA, OTHER, OTHER, SHA)))
        with self.assertRaisesRegex(BrainError, "SOURCE_REVISION_CHANGED"):
            observe_after_bounded_revision_race(api, REPO)
        self.assertEqual(api.requests, 8)

    def test_budget_exhaustion_refuses_retry(self):
        provider = MovingHead((SHA, OTHER))
        api = GitHub(transport=provider)
        api.requests = 5
        with self.assertRaisesRegex(BrainError, "SOURCE_REVISION_CHANGED"):
            observe_after_bounded_revision_race(api, REPO)
        self.assertEqual(api.requests, 9)
        self.assertEqual(len(provider.calls), 4)

    def test_full_five_page_snapshot_stays_under_24_gets(self):
        provider = MovingHead(size=500)
        api = GitHub(transport=provider)
        observation, used_retry = observe_after_bounded_revision_race(api, REPO)
        self.assertTrue(used_retry)
        self.assertEqual(len(observation[0]["checks"]), 500)
        self.assertEqual(observation[0]["head_sha"], OTHER)
        self.assertEqual(api.requests, 16)

    def test_other_source_error_never_retried(self):
        provider = MovingHead(fail="SOURCE_API_403")
        api = GitHub(transport=provider)
        with self.assertRaises(BrainError):
            observe_after_bounded_revision_race(api, REPO)
        self.assertEqual(len(provider.calls), 1)

    def test_explicit_provider_keeps_existing_monitor_behavior(self):
        with self.assertRaisesRegex(BrainError, "MONITOR_INCOMPLETE"):
            self.run_public(MovingHead((SHA, OTHER)), injected=True)

    def test_bad_counter_blocks_before_any_get(self):
        for counter in (-1, True, 25):
            with self.subTest(counter=counter):
                provider = MovingHead()
                api = GitHub(transport=provider)
                api.requests = counter
                with self.assertRaises(BrainError):
                    observe_after_bounded_revision_race(api, REPO)
                self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
