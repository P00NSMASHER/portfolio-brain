"""Cross-project coverage and measurement-contract regressions."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.__main__ import main, projects
from brain.adapters import event, policy
from brain.core import Store
from brain.projects import build_project_portfolio, extended_repositories, load_project_registry

SHA = "a" * 40

def repo_row(repository):
    return {
        "key": repository,
        "observed_at": "2026-10-13T20:00:00Z",
        "data_kind": "ACTUAL",
        "repository": repository,
        "head_sha": SHA,
        "default_branch": "main",
        "checks": [],
        "open_issues": 0,
        "source_ref": f"https://github.com/{repository}/commit/{SHA}",
    }

def canonical_report(candidates=None, outcomes=None):
    return {
        "schema_version": 2,
        "status": "PASS",
        "source_sha": SHA,
        "state_sequence": 10,
        "pending_events": 0,
        "repositories": [repo_row(repo) for repo in policy()["repositories"]],
        "reuse_candidates": candidates or [],
        "learning": {"outcomes": outcomes or [], "experiments": []},
    }

class ProjectRegistryTests(unittest.TestCase):
    def test_registry_covers_eight_repo_bindings_without_widening_core(self):
        document = load_project_registry()
        repositories = {row["repository"] for row in document["projects"]}
        self.assertEqual(len(repositories), 8)
        self.assertEqual(len(policy()["repositories"]), 4)
        self.assertEqual(set(extended_repositories()), {
            "P00NSMASHER/PipsQuestWorld",
            "P00NSMASHER/permitplate-nyc",
            "P00NSMASHER/StarBlox",
            "P00NSMASHER/capturebrief",
        })

    def test_queue_never_invents_baseline_or_value(self):
        result = build_project_portfolio(
            canonical_report(),
            [repo_row(repo) for repo in extended_repositories()],
            source_sha=SHA,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["repository_count"], 8)
        self.assertIsNone(result["verified_revenue"])
        for item in result["projects"]:
            self.assertIsNone(item["baseline_value"])
            self.assertIsNone(item["measured_result"])
            self.assertFalse(item["downstream_write_authority"])
            self.assertFalse(item["production_merge_authority"])

    def test_candidate_feedback_is_scoped_by_project_target(self):
        candidate = {
            "key": "example/repo:invoice.py",
            "freshness": "CURRENT",
            "target": "freight-recovery",
        }
        outcome = {
            "candidate_key": candidate["key"],
            "outcome": "USEFUL",
            "basis": "OPERATOR_REPORTED",
            "evidence_ref": "operator evidence",
            "engineering_seconds_saved": None,
        }
        result = build_project_portfolio(
            canonical_report([candidate], [outcome]),
            [repo_row(repo) for repo in extended_repositories()],
            source_sha=SHA,
        )
        retally = next(row for row in result["projects"] if row["id"] == "retally")
        self.assertEqual(retally["status"], "MEASURED_OUTCOME_RECORDED")
        research_labs = next(row for row in result["projects"] if row["id"] == "research-labs")
        self.assertEqual(research_labs["operator_outcome_count"], 0)
        starblox = next(row for row in result["projects"] if row["id"] == "starblox")
        self.assertEqual(starblox["operator_outcome_count"], 0)

    def test_missing_extended_source_blocks_project_queue_only(self):
        result = build_project_portfolio(canonical_report(), [], source_sha=SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(set(result["missing_repositories"]), set(extended_repositories()))

class ProjectStageTests(unittest.TestCase):
    def test_projects_reads_only_extended_repositories_within_existing_budget(self):
        class Store:
            visibility = "PUBLIC"
            def read_report(self, sha):
                return canonical_report()

        class API:
            requests = 0
            def __init__(self):
                self.seen = []
            def observe(self, repository):
                self.seen.append(repository)
                self.requests += 4
                payload = dict(repo_row(repository))
                payload.pop("key")
                payload.pop("observed_at")
                payload.pop("data_kind")
                return payload, False

        api = API()
        with tempfile.TemporaryDirectory() as directory:
            result = projects(Store(), SHA, Path(directory) / "projects", api=api)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(tuple(api.seen), extended_repositories())
        self.assertEqual(api.requests, 16)
        self.assertLessEqual(api.requests, policy()["max_requests_per_operation"])

    def test_cli_projects_never_mutates_original_canonical_sqlite(self):
        class API:
            requests = 0
            def observe(self, repository):
                self.requests += 4
                payload = dict(repo_row(repository))
                payload.pop("key")
                payload.pop("observed_at")
                payload.pop("data_kind")
                return payload, False

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite"
            store = Store(database, visibility="PUBLIC")
            try:
                events = []
                for repository in policy()["repositories"]:
                    payload = dict(repo_row(repository))
                    payload.pop("key")
                    payload.pop("observed_at")
                    payload.pop("data_kind")
                    events.append(event("repository", repository, payload, SHA,
                                        now="2026-10-13T20:00:00Z"))
                store.submit(events, now="2026-10-13T20:00:00Z")
                store.drain()
                store.report(SHA, now="2026-10-13T20:00:00Z")
            finally:
                store.close()
            before = database.read_bytes()
            before_mtime = database.stat().st_mtime_ns
            with patch("brain.__main__.source_sha", return_value=SHA), \
                 patch("brain.__main__.GitHub", return_value=API()):
                code = main([
                    "projects", "--db", str(database),
                    "--output", str(Path(directory) / "projects"),
                ])
            self.assertEqual(code, 0)
            self.assertEqual(database.read_bytes(), before)
            self.assertEqual(database.stat().st_mtime_ns, before_mtime)

if __name__ == "__main__":
    unittest.main()
