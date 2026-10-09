"""V5 shadow-only integration of reviewed knowledge and experiment candidates.

No external network, real invoices, production state writes, trading authority,
paid services, or implied release acceptance.
"""
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from brain.adapters import event
from brain.core import Store, digest
from brain.experiments import invoice_dedup_experiment
from brain.upgrades import build_knowledge


SOURCE = "a" * 40
REVIEWED = "b" * 40
NOW = "2026-10-09T13:00:00Z"


def candidate(project, index, owner):
    repository = f"{owner}/sources"
    path = f"src/invoice_match_{index:03}.py"
    return {
        "repository": repository,
        "head_sha": REVIEWED,
        "path": path,
        "blob_sha": "c" * 40,
        "code_sha256": "d" * 64,
        "bytes": 2048,
        "test_paths": [f"tests/test_invoice_match_{index:03}.py"],
        "license": "MIT",
        "source_ref": f"https://github.com/{repository}/blob/{REVIEWED}/{path}",
        "target": project,
        "query": "invoice match research",
        "matched_terms": ["invoice", "match"],
    }


def observed_repository():
    repo = "ExampleOrg/portfolio-source"
    return event("repository", repo, {
        "repository": repo,
        "head_sha": REVIEWED,
        "default_branch": "main",
        "checks": [],
        "open_issues": 0,
        "source_ref": f"https://github.com/{repo}/commit/{REVIEWED}",
    }, SOURCE, now=NOW)


class CombinedV5ResearchIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite"
        self.store = Store(self.path, visibility="PUBLIC")
        self.addCleanup(self.store.close)

    def test_balanced_research_and_simulated_experiment_share_verified_ledger(self):
        rows = [
            candidate("school-tools", i, "AAA") for i in range(14)
        ] + [
            candidate("agent-products", i, "ZZZ") for i in (201, 202)
        ] + [
            candidate("freight-recovery", 301, "ZZZ")
        ]
        items = [observed_repository()]
        for row in rows:
            key = row["repository"] + ":" + row["path"]
            items.append(event("candidate", key, row, SOURCE, now=NOW))
        synthetic = invoice_dedup_experiment(1000)
        items.append(event(
            "experiment", synthetic["experiment"], synthetic, SOURCE,
            data_kind="SIMULATED", now=NOW,
        ))
        self.assertEqual(len(items), 19)
        self.store.submit(items, now=NOW)
        self.assertEqual(self.store.drain(), len(items))
        report = self.store.report(SOURCE, now=NOW)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["pending_events"], 0)
        self.assertEqual(report["state_sequence"], len(items))
        self.assertEqual(report["learning"]["events"], len(items))
        self.assertEqual(report["learning"]["experiments"], [synthetic])
        self.assertIsNone(report["learning"]["verified_revenue"])
        self.assertIsNone(report["learning"]["prediction_confidence"])
        self.assertFalse(report["learning"]["autonomous_code_execution"])
        self.assertEqual(synthetic["duplicate_cases"], 124)
        self.assertIn("NON-EQUIVALENT", synthetic["scope"])
        self.assertIn("not benchmark timings or a verified speedup", synthetic["scope"].lower())

        knowledge = build_knowledge(report)
        self.assertEqual(knowledge["schema_version"], 2)
        self.assertEqual(knowledge["fingerprint"], digest(knowledge["sources"]))
        self.assertEqual(len(knowledge["sources"]), 12)
        self.assertEqual(Counter(item["target"] for item in knowledge["sources"]), {
            "school-tools": 9,
            "agent-products": 2,
            "freight-recovery": 1,
        })
        self.assertEqual(
            [item["target"] for item in knowledge["sources"][:3]],
            ["agent-products", "freight-recovery", "school-tools"],
        )
        self.assertEqual(self.store.read_report(SOURCE, now=NOW), report)
        before_bytes = self.path.read_bytes()
        before_source_events = [
            json.loads(row[0])
            for row in self.store.db.execute("SELECT body FROM events ORDER BY seq")
        ]
        self.assertEqual(before_source_events[-1]["data_kind"], "SIMULATED")
        self.assertEqual(
            len(self.store.db.execute("SELECT 1 FROM reports").fetchall()), 1
        )
        self.assertEqual(self.path.read_bytes(), before_bytes)

        # Read/replay the persisted authority after a normal close/reopen.
        self.store.close()
        reopened = Store(self.path, visibility="PUBLIC")
        try:
            self.assertEqual(reopened.read_report(SOURCE, now=NOW), report)
            self.assertEqual(reopened.pending(), 0)
        finally:
            reopened.close()

    def test_historical_simulated_experiment_bytes_remain_immutable(self):
        historical = invoice_dedup_experiment(100)
        historical["scope"] = (
            "Archived SIMULATED test-only observation; counts are NOT "
            "performance benchmarks or verified commercial value."
        )
        # The new synthetic fixture must not retroactively rewrite a former
        # experiment payload or infer a past measured performance result.
        old_event = event(
            "experiment", historical["experiment"], historical, REVIEWED,
            data_kind="SIMULATED", now="2026-10-09T12:58:00Z",
        )
        new = invoice_dedup_experiment(100)
        new_event = event(
            "experiment", new["experiment"], new, SOURCE,
            data_kind="SIMULATED", now=NOW,
        )
        self.store.submit([observed_repository(), old_event, new_event], now=NOW)
        self.store.drain()
        original_event_body = self.store.db.execute(
            "SELECT body FROM events WHERE id=?", (old_event["id"],)
        ).fetchone()[0]
        report = self.store.report(SOURCE, now=NOW)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["learning"]["experiments"], [new])
        self.assertEqual(report["state_sequence"], 3)
        self.assertIsNone(report["learning"]["verified_revenue"])
        self.assertEqual(
            self.store.db.execute(
                "SELECT body FROM events WHERE id=?", (old_event["id"],)
            ).fetchone()[0],
            original_event_body,
        )
        self.assertEqual(self.store.read_report(SOURCE, now=NOW), report)


if __name__ == "__main__":
    unittest.main()
