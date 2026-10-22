"""An incomplete public GitHub search cannot poison every scheduled cycle.

Synthetic provider responses only. Alternate sources must be independently
verified; this is not evidence that an upstream incomplete search succeeded.
"""
import tempfile
import unittest
from pathlib import Path

from brain.__main__ import research
from brain.adapters import GitHub
from brain.core import BrainError, Store
from test_brain_research_target_recovery import SearchFixture, GOOD, SHA


class IncompleteSearch(SearchFixture):
    def __init__(self, *, all_incomplete=False, alternate="source"):
        super().__init__(alternate=alternate)
        self.all_incomplete = all_incomplete

    def __call__(self, path):
        if path.startswith("/search/repositories?") and (
            self.all_incomplete or "freight%20invoice%20audit" in path
        ):
            self.paths.append(path)
            # A partial response can contain appealing results. They must
            # NEVER become source evidence from this incomplete response.
            return {"incomplete_results": True,
                    "items": [self.hit(GOOD, 42)]}
        return super().__call__(path)


class IncompleteSearchFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state.sqlite",
                           visibility="PUBLIC")
        self.addCleanup(self.store.close)
        self.output = Path(self.temp.name) / "research"

    def test_partial_primary_search_uses_only_hash_verified_alternate(self):
        transport = IncompleteSearch()
        api = GitHub(transport=transport)
        result = research(self.store, SHA, self.output, api=api)
        op = result["operation"]
        self.assertEqual(op["original_target"], "freight-recovery")
        self.assertEqual(op["target"], "agent-products")
        self.assertEqual(op["result"], "VERIFIED_ALTERNATE_SOURCE_AFTER_SEARCH_FAILURE")
        self.assertEqual(op["candidates_observed"], 1)
        self.assertEqual(op["requests"], 5)
        self.assertEqual(len(transport.paths), 5)
        self.assertEqual(op["prior_unavailable_targets"][0]["classification"],
                         "PUBLIC_SEARCH_INCOMPLETE")
        self.assertEqual(op["prior_unavailable_targets"][0]["source_gaps"],
                         [{"stage": "search",
                           "reason": "GITHUB_SEARCH_INCOMPLETE_RESULTS"}])
        events, _, _ = self.store._verified_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["repository"], GOOD)
        self.assertEqual(events[0]["payload"]["target"], "agent-products")
        self.assertEqual(self.store.pending(), 0)

    def test_no_complete_alternate_retains_original_failure_and_no_events(self):
        transport = IncompleteSearch(all_incomplete=True)
        api = GitHub(transport=transport)
        with self.assertRaisesRegex(BrainError, "^DISCOVERY_INCOMPLETE$"):
            research(self.store, SHA, self.output, api=api)
        self.assertEqual(api.requests, 3)
        self.assertEqual(len(transport.paths), 3)
        self.assertEqual(self.store.pending(), 0)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_incomplete_then_empty_alternates_cannot_forge_recovery(self):
        transport = IncompleteSearch(alternate="no_matches")
        api = GitHub(transport=transport)
        with self.assertRaisesRegex(BrainError, "^DISCOVERY_INCOMPLETE$"):
            research(self.store, SHA, self.output, api=api)
        self.assertEqual(api.requests, 3)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_low_remaining_budget_retains_initial_failure_without_extra_reads(self):
        transport = IncompleteSearch()
        api = GitHub(transport=transport)
        api.requests = 18
        with self.assertRaisesRegex(BrainError, "^DISCOVERY_INCOMPLETE$"):
            research(self.store, SHA, self.output, api=api)
        self.assertEqual(api.requests, 19)
        self.assertEqual(len(transport.paths), 1)
        self.assertEqual(self.store.pending(), 0)

    def test_adapter_direct_discovery_still_rejects_incomplete_results(self):
        transport = IncompleteSearch()
        api = GitHub(transport=transport)
        target = {"project": "freight-recovery", "query": "freight invoice audit",
                  "terms": ["freight", "invoice", "audit"]}
        with self.assertRaisesRegex(BrainError, "^DISCOVERY_INCOMPLETE$"):
            api.discover(target)
        self.assertEqual(api.requests, 1)
        self.assertEqual(len(transport.paths), 1)
        self.assertEqual(api.discovery_unavailable, [])


if __name__ == "__main__":
    unittest.main()
