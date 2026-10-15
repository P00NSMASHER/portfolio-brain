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
    def test_app_factory_extended_observation_has_priority_under_get_budget(self):
        self.assertEqual(extended_repositories()[0],
                         "P00NSMASHER/x402-product-factory")

    def test_registry_excludes_retired_game_from_active_get_budget(self):
        document = load_project_registry()
        repositories = {row["repository"] for row in document["projects"]}
        self.assertEqual(len(repositories), 8)
        self.assertNotIn("P00NSMASHER/StarBlox",repositories)
        self.assertEqual(len(policy()["repositories"]), 4)
        self.assertEqual(set(extended_repositories()), {
            "P00NSMASHER/PipsQuestWorld",
            "P00NSMASHER/permitplate-nyc",
            "P00NSMASHER/capturebrief",
            "P00NSMASHER/x402-product-factory",
        })

    def test_grade_2_app_and_roblox_are_active_not_retired_starblox(self):
        registry = load_project_registry()
        by_id = {item["id"]: item for item in registry["projects"]}
        self.assertEqual(by_id["abvm"]["name"], "ABVM Grade 2 Learning App")
        self.assertIn("daily teacher curriculum/homework refresh", by_id["abvm"]["improvement_focus"])
        self.assertEqual(by_id["pips-classroom"]["name"], "ABVM Grade 2 Roblox Classroom")
        self.assertFalse(any("StarBlox" in item["name"] for item in registry["projects"]))

    def test_queue_never_invents_baseline_or_value(self):
        result = build_project_portfolio(
            canonical_report(),
            [repo_row(repo) for repo in extended_repositories()],
            source_sha=SHA,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["repository_count"], 8)
        self.assertIsNone(result["verified_revenue"])
        self.assertEqual(result["technical_review_packet_count"], 0)
        self.assertEqual(result["measured_project_outcomes"], 0)
        self.assertIsNone(result["real_buyer_confirmed_outcomes"])
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
        self.assertFalse(any(row["id"] == "starblox" for row in result["projects"]))
        self.assertTrue(any(row["id"] == "pips-classroom" for row in result["projects"]))

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
        self.assertIn("paying freight-recovery pilot", work[0]["commercial_north_star"])
        self.assertIn("paying buyer", work[1]["commercial_north_star"])
        self.assertEqual(work[0]["independent_revenue_gates"][-1],
                         "payment-provider-confirmed settled customer revenue net of refunds")
        self.assertTrue(all(item["revenue_evidence_status"] == "NOT_VERIFIED" for item in work))
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
        self.assertEqual(api.requests, 16)
        self.assertLessEqual(api.requests, policy()["max_requests_per_operation"])

    def test_priority_sources_and_pr_ci_precede_optional_project_observations(self):
        from brain.projects import FOCUS

        factory = "P00NSMASHER/x402-product-factory"
        retally = "P00NSMASHER/github-value-hunt-ledger"

        class Store:
            visibility = "PUBLIC"
            def read_report(self, sha):
                return canonical_report()

        class API:
            def __init__(self, extra_optional_reads=0):
                self.requests = 0
                self.calls = []
                self.extra_optional_reads = extra_optional_reads

            def observe(self, repository):
                self.calls.append("observe:" + repository)
                self.requests += 4
                if (repository != factory
                        and self.extra_optional_reads):
                    self.requests += self.extra_optional_reads
                    self.extra_optional_reads = 0
                if self.requests > policy()["max_requests_per_operation"]:
                    raise RuntimeError("test should have skipped budget overrun")
                payload = dict(repo_row(repository))
                for key in ("key", "observed_at", "data_kind"):
                    payload.pop(key)
                return payload, False

            def get(self, path):
                self.calls.append("get:" + path)
                self.requests += 1
                if self.requests > policy()["max_requests_per_operation"]:
                    raise RuntimeError("test should not exceed GET budget")
                repository = retally if retally in path else factory
                if "/pulls?" in path:
                    number = 329 if repository == retally else 43
                    title = ("RETALLY first-customer controls" if
                             repository == retally else
                             "Automate ideas and private deployment")
                    return [{
                        "number": number,
                        "state": "open",
                        "draft": True,
                        "title": title,
                        "updated_at": "2026-10-14T08:00:00Z",
                        "html_url": f"https://github.com/{repository}/pull/{number}",
                        "head": {"sha": SHA, "ref": "research/head",
                                 "repo": {"full_name": repository}},
                        "base": {"ref": "main",
                                 "repo": {"full_name": repository}},
                    }]
                return {"total_count": 1, "check_runs": [
                    {"id": 123, "head_sha": SHA, "status": "completed",
                     "conclusion": "success"},
                ]}

        api = API()
        with tempfile.TemporaryDirectory() as directory:
            result = projects(Store(), SHA, Path(directory) / "report", api=api)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(api.requests, 20)
        self.assertEqual(result["operation"]["requests_after_priority_source"], 4)
        self.assertEqual(result["operation"]["requests_after_priority_prs"], 8)
        self.assertEqual(result["technical_review_packet_count"], 2)
        self.assertEqual(
            result["focused_work_readiness"],
            "SOURCE_PINNED_TECHNICAL_REVIEW_AVAILABLE_NOT_RELEASE_APPROVAL",
        )
        self.assertTrue(api.calls[0].startswith("observe:" + factory))
        self.assertTrue(all(call.startswith("get:") for call in api.calls[1:5]))
        self.assertTrue(all(call.startswith("observe:") for call in api.calls[5:]))
        self.assertFalse(result["autonomous_downstream_writes"])

    def test_optional_extra_pagination_preserves_priority_and_never_fakes_completion(self):
        class Store:
            visibility = "PUBLIC"
            def read_report(self, sha):
                return canonical_report()

        class API:
            def __init__(self):
                self.requests = 0
                self.seen = []
            def observe(self, repo):
                self.seen.append(repo)
                self.requests += 9 if repo != extended_repositories()[0] else 4
                if self.requests > 24:
                    raise RuntimeError("Budget overrun should be skipped")
                payload = dict(repo_row(repo))
                for key in ("key", "observed_at", "data_kind"):
                    payload.pop(key)
                return payload, False

        api = API()
        with tempfile.TemporaryDirectory() as directory:
            result = projects(Store(), SHA, Path(directory) / "report", api=api)
        self.assertEqual(api.seen[0], "P00NSMASHER/x402-product-factory")
        self.assertLessEqual(api.requests, 24)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["focused_work_readiness"],
                         "FOCUSED_TECHNICAL_EVIDENCE_INCOMPLETE")
        self.assertTrue(any(
            row["error"] == "OPTIONAL_SOURCE_NOT_ATTEMPTED_INSUFFICIENT_GET_BUDGET"
            for row in result["operation"]["errors"]
        ))
        self.assertTrue(result["missing_repositories"])
        self.assertEqual(result["verified_revenue"], None)

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
            # This is an immutability test, not a wall-clock freshness test.
            # Freeze both clock bindings at the fixture's report timestamp so
            # the regression cannot expire 48 hours after its source commit.
            with patch("brain.__main__.source_sha", return_value=SHA), \
                 patch("brain.__main__.GitHub", return_value=API()), \
                 patch("brain.core.utcnow", return_value="2026-10-13T20:00:00Z"), \
                 patch("brain.__main__.utcnow", return_value="2026-10-13T20:00:00Z"):
                code = main([
                    "projects", "--db", str(database),
                    "--output", str(Path(directory) / "projects"),
                ])
            self.assertEqual(code, 0)
            self.assertEqual(database.read_bytes(), before)
            self.assertEqual(database.stat().st_mtime_ns, before_mtime)


    def test_native_budget_reuses_four_freed_gets_for_original_pr_proof(self):
        ret = "P00NSMASHER/github-value-hunt-ledger"
        fac = "P00NSMASHER/x402-product-factory"
        class Store:
            visibility = "PUBLIC"
            def read_report(self, sha):
                return canonical_report()
        class API:
            def __init__(self):
                self.requests = 0
                self.calls = []
            def observe(self, repository):
                self.calls.append("observe:" + repository)
                self.requests += 4
                row = dict(repo_row(repository))
                for name in ("key", "observed_at", "data_kind"):
                    row.pop(name)
                return row, False
            def get(self, path):
                self.calls.append("get:" + path)
                self.requests += 1
                self.assert_budget()
                repo = ret if ret in path else fac
                if "/pulls?state=open" in path:
                    number = 329 if repo == ret else 43
                    return [{
                        "number":number,"state":"open","draft":True,
                        "title":("RETALLY first-customer onboarding" if repo==ret
                                 else "Factory buyer pilots"),
                        "updated_at":"2026-10-14T08:00:00Z",
                        "html_url":f"https://github.com/{repo}/pull/{number}",
                        "head":{"sha":SHA,"ref":"feature/repair",
                                "repo":{"full_name":repo}},
                        "base":{"ref":"main","repo":{"full_name":repo}},
                    }]
                if "/check-runs?" in path:
                    return {"total_count":1,"check_runs":[{
                        "id":123,"head_sha":SHA,"name":"validate",
                        "status":"completed","conclusion":"success",
                        "app":{"id":15368},
                    }]}
                if "/pulls/" in path:
                    number=int(path.split("/pulls/",1)[1])
                    return {
                        "number":number,"state":"open","merged":False,
                        "merge_commit_sha":None,
                        "head":{"sha":SHA,"repo":{"full_name":repo}},
                        "base":{"ref":"main","repo":{"full_name":repo}},
                    }
                if "/branches/main" in path:
                    return {"commit":{"sha":SHA}}
                raise AssertionError("unexpected provider GET "+path)
            def assert_budget(self):
                self_assert = self.requests <= policy()["max_requests_per_operation"]
                if not self_assert:
                    raise AssertionError("exceeded the protected GET budget")
        api=API()
        with tempfile.TemporaryDirectory() as directory:
            result=projects(Store(),SHA,Path(directory)/"project",
                            api=api,verify_original_repairs=True)
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["repository_count"],8)
        self.assertLessEqual(api.requests,24)
        self.assertEqual(api.requests,23)
        self.assertEqual(result["operation"]["original_repair_requests"],3)
        self.assertEqual(len(result["original_repair_proof"]["source_checks"]),1)
        self.assertEqual(result["original_repair_proof"]["source_checks"][0]
                         ["source_head_sha"],SHA)
        self.assertEqual(result["original_repair_proof"]["observed_pr_count"],1)
        self.assertEqual(len(result["original_repair_proof"]["proofs"]),1)
        self.assertFalse(result["original_repair_proof"]["proofs"][0]["merged"])
        self.assertFalse(result["autonomous_downstream_writes"])
        self.assertEqual(len(result["autonomous_repair_followthrough"]["actions"]),2)

    def test_budget_exhaustion_skips_original_review_instead_of_calling_any_provider(self):
        from brain.core import BrainError
        class Store:
            visibility = "PUBLIC"
            def read_report(self, sha):
                return canonical_report()
        class API:
            def __init__(self):
                self.requests=0
                self.calls=[]
            def observe(self, repo):
                self.calls.append("observe:"+repo)
                self.requests+=4 if repo==extended_repositories()[0] else 9
                if self.requests>24:
                    raise BrainError("REQUEST_BUDGET_EXHAUSTED")
                row=dict(repo_row(repo))
                for key in ("key","observed_at","data_kind"):
                    row.pop(key)
                return row,False
            def get(self, path):
                self.calls.append("get:"+path)
                self.requests += 1
                if self.requests > 24:
                    raise AssertionError("unbounded original provider call")
                if "/pulls?state=open" in path:
                    return []
                raise AssertionError("original PR checks should not run")
        api=API()
        with tempfile.TemporaryDirectory() as directory:
            result=projects(Store(),SHA,Path(directory)/"project",
                            api=api,verify_original_repairs=True)
        self.assertLessEqual(api.requests,24)
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["operation"]["original_repair_requests"],0)
        self.assertEqual(result["original_repair_proof"]["proofs"],[])
        self.assertEqual(result["operation"]["original_repair_provider_status"],
                         "NOT_CHECKED_OR_REQUEST_BUDGET_UNAVAILABLE")
        self.assertFalse(result["autonomous_downstream_writes"])


if __name__ == "__main__":
    unittest.main()
