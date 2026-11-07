import sqlite3
import tempfile
import unittest
from pathlib import Path

from brain.v11.owner_decisions import changes, incidents
from tests.test_brain_v11_currentness_window import Provider, REPO, RUN, SOURCE, PATH, original
from tests.test_brain_v11_owner_inbox import report


class DecisionTests(unittest.TestCase):
    def test_restart_dedup_and_three_changed_items(self):
        rows = [{"id": str(n), "state": "BLOCKED", "owner_decision": "AWAITING_CHAT_DECISION"}
                for n in range(4)]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.sqlite"
            with sqlite3.connect(path) as db:
                self.assertEqual(len(changes(db, rows)["decisions"]), 3)
            with sqlite3.connect(path) as db:
                self.assertEqual([r["id"] for r in changes(db, rows)["decisions"]], ["3"])
                rows[0]["head"] = "different-source-same-block"
                self.assertEqual(changes(db, rows)["decisions"], [])
                rows[0]["state"] = "MERGED_AWAITING_TARGET_PROOF"
                self.assertEqual([r["id"] for r in changes(db, rows)["decisions"]], ["0"])

    def test_historical_or_truncated_permitplate_failure_stays_quiet(self):
        doc = report()
        job = doc["owner_jobs"][0]
        job["source_sha"] = SOURCE
        proof = job["failure_evidence"]
        proof.update(run_id=RUN, source_sha=SOURCE, workflow_path=PATH, job_name="verify",
                     url=f"https://github.com/{REPO}/actions/runs/{RUN}/job/{proof['job_id']}")
        for api in (Provider([original(), original(RUN+1, conclusion="success")]),
                    Provider([original(RUN+1, source="e"*40)], count=500)):
            self.assertEqual(list(incidents(doc, api, 0)), [])
            self.assertEqual(api.reads, 3)
        self.assertEqual(len(list(incidents(doc, Provider([original()]), 0))), 1)

    def test_scheduled_writers_held_and_recovery_still_enabled(self):
        directory = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        core = (directory / "brain-cycle.yml").read_text()
        self.assertNotIn("python -m brain evolve", core)
        self.assertNotIn("pull-requests: write", core)
        self.assertIn("python -m brain.v11.owner_decisions", core)
        scoped = (directory / "v8-scoped-repair.yml").read_text()
        self.assertNotIn("python -m brain.v11.owner_executor", scoped)
        self.assertIn("false && github.repository", scoped.split("  propose-only:", 1)[1].split("runs-on:", 1)[0])
        self.assertEqual(scoped.count("false && steps.request.outputs.artifact"), 2)
        self.assertEqual(scoped.count("false && steps.recipe.outputs.eligible"), 2)
        self.assertIn("python -m brain.hunter_schedule_watchdog --dispatch", scoped)
        native = (directory / "v9-guarded-native-automerge.yml").read_text()
        self.assertNotIn("pull-requests: write", native)
        self.assertNotIn("contents: write", native)
        self.assertEqual(native.count("if: ${{ false"), 2)
        foundation = (directory / "foundation-ci.yml").read_text()
        self.assertIn("startsWith(github.head_ref, 'factory/auto-repair-')", foundation)
        self.assertIn("startsWith(github.ref_name, 'factory/auto-repair-')", foundation)
        self.assertLess(foundation.index("Hold reserved"), foundation.index("actions/checkout"))
