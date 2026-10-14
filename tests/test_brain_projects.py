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
    def test_registry_covers_nine_repo_bindings_without_widening_core(self):
        document = load_project_registry()
        repositories = {row["repository"] for row in document["projects"]}
        self.assertEqual(len(repositories), 9)
        self.assertEqual(len(policy()["repositories"]), 4)
        self.assertEqual(set(extended_repositories()), {
            "P00NSMASHER/PipsQuestWorld",
            "P00NSMASHER/permitplate-nyc",
            "P00NSMASHER/StarBlox",
            "P00NSMASHER/capturebrief",
            "P00NSMASHER/x402-product-factory",
        })

    def test_queue_never_invents_baseline_or_value(self):
        result = build_project_portfolio(
            canonical_report(),
            [repo_row(repo) for repo in extended_repositories()],
            source_sha=SHA,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["repository_count"], 9)
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
        self.assertEqual(retally["status"], "OPERATOR_FEEDBACK_RECORDED")
        self.assertIsNone(retally["measured_result"])
        research_labs = next(row for row in result["projects"] if row["id"] == "research-labs")
        self.assertEqual(research_labs["operator_outcome_count"], 0)
        starblox = next(row for row in result["projects"] if row["id"] == "starblox")
        self.assertEqual(starblox["operator_outcome_count"], 0)

    def test_missing_extended_source_blocks_project_queue_only(self):
        result = build_project_portfolio(canonical_report(), [], source_sha=SHA)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(set(result["missing_repositories"]), set(extended_repositories()))

    def test_focused_review_evidence_never_implies_measured_buyer_value(self):
        evidence = {
            "retally": {
                "status": "PR_AND_CHECKS_OBSERVED", "pr_number": 460,
                "pr_url": "https://github.com/P00NSMASHER/github-value-hunt-ledger/pull/460",
                "head_sha": "b" * 40, "production_merge_authority": False,
                "buyer_value_verified": False,
                "payment_or_external_contact_authority": False,
                "checks": {"status": "SKIPPED_CHECKS_NOT_ACCEPTANCE",
                           "complete_single_page": True,
                           "checked_head_sha": "b" * 40},
            },
        }
        result = build_project_portfolio(
            canonical_report(), [repo_row(r) for r in extended_repositories()],
            source_sha=SHA, priority_prs=evidence,
        )
        self.assertEqual(result["priority_review_coverage"], "INCOMPLETE_OR_UNVERIFIED")
        self.assertEqual(result["priority_improvements"][0]["active_pr_review"]["pr_number"],
                         460)
        self.assertIsNone(result["priority_improvements"][0]["measured_result"])
        self.assertIsNone(result["verified_revenue"])

    def test_forged_external_pr_link_cannot_be_rendered(self):
        from brain.core import BrainError
        with self.assertRaises(BrainError):
            build_project_portfolio(
                canonical_report(), [repo_row(r) for r in extended_repositories()],
                source_sha=SHA, priority_prs={"retally": {
                    "status": "PR_AND_CHECKS_OBSERVED", "pr_number": 460,
                    "pr_url": "https://evil.invalid/redirect",
                    "head_sha": "a" * 40, "checks": {"complete_single_page": True,
                    "checked_head_sha": "a" * 40},
                    "production_merge_authority": False, "buyer_value_verified": False,
                    "payment_or_external_contact_authority": False,
                }},
            )

    def test_retally_and_factory_priority_is_not_customer_activation(self):
        report = build_project_portfolio(
            canonical_report(),
            [repo_row(r) for r in extended_repositories()],
            source_sha=SHA,
        )
        work = report["priority_improvements"]
        self.assertEqual([x["project_id"] for x in work], ["retally", "product-factory"])
        self.assertEqual(work[1]["repository"], "P00NSMASHER/x402-product-factory")
        self.assertEqual([x["priority"] for x in work], [1, 2])
        self.assertIn("restricted runtime", work[0]["activation_gate"])
        self.assertIn("buyer demand", work[1]["activation_gate"])
        for task in work:
            self.assertIsNone(task["baseline_value"])
            self.assertIsNone(task["measured_result"])
            self.assertFalse(task["real_customer_activation_authority"])

    def test_factory_ci_failure_is_not_hidden(self):
        snapshots = [repo_row(r) for r in extended_repositories()]
        app = next(r for r in snapshots if r["repository"] ==
                   "P00NSMASHER/x402-product-factory")
        app["checks"] = [{"name": "factory", "status": "completed",
                          "conclusion": "failure"}]
        report = build_project_portfolio(canonical_report(), snapshots, source_sha=SHA)
        self.assertEqual(report["priority_improvements"][1]["source_check_state"],
                         "ADVERSE_CHECKS_OBSERVED")

    def test_missing_factory_source_is_not_overclaimed(self):
        snapshots = [repo_row(r) for r in extended_repositories()
                     if r != "P00NSMASHER/x402-product-factory"]
        report = build_project_portfolio(canonical_report(), snapshots, source_sha=SHA)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIsNone(report["priority_improvements"][1]["observed_source_sha"])
        self.assertEqual(report["priority_improvements"][1]["queue_status"],
                         "SOURCE_UNOBSERVED")


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
        self.assertEqual(api.requests, 20)
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
