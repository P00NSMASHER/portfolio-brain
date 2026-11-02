"""V11 dashboard evidence rules: true issuer, sampled counts, unknown costs."""
import copy
import unittest

from brain.v11 import results_dashboard as v

MAIN = "a" * 40
HEAD = "b" * 40
MERGE = "c" * 40
AT = "2026-11-01T22:00:00Z"


class Fake:
    def __init__(self):
        self.calls = []
        self.main = MAIN
        self.independent = 5121826
        self.rows = [
            {"number": 900, "title": "fix: repair <script>alert(1)</script>",
             "head": {"sha": HEAD, "ref": "auto-repair/v10-abcdef0123456789"},
             "merged_at": "2026-11-01T21:30:00Z", "merge_commit_sha": MERGE},
            {"number": 899, "title": "feat: unrelated",
             "head": {"sha": "d" * 40, "ref": "feature/thing"},
             "merged_at": None, "merge_commit_sha": None},
        ]
        self.issues = [
            {"number": 796, "title": "d67 final 12h: original repairs missing",
             "body": "Historical outage", "updated_at": "2026-10-31T00:00:00Z"},
            {"number": 210, "title": "Automation audit remediation tracker",
             "body": "Open remediation", "updated_at": "2026-11-01T00:00:00Z"},
        ]
        self.core_steps = [
            {"name": "Verify independently signed Cloudflare Cron provenance",
             "conclusion": "success"}
        ]
        self.runs = [
            {"id": 104, "name": "brain-cycle-v2",
             "path": ".github/workflows/brain-cycle.yml",
             "head_branch": "main", "head_sha": MAIN,
             "repository": {"full_name": v.REPO},
             "run_attempt": 1, "event": "workflow_dispatch",
             "status": "completed", "conclusion": "success"},
            {"id": 105, "name": "brain-cycle-v2",
             "path": ".github/workflows/brain-cycle.yml",
             "head_branch": "main", "head_sha": MAIN,
             "repository": {"full_name": v.REPO},
             "run_attempt": 1, "event": "workflow_dispatch",
             "status": "completed", "conclusion": "failure"},
            {"id": 106, "name": "foundation-ci", "head_sha": "e" * 40,
             "status": "completed", "conclusion": "success"},
        ]

    def get(self, path):
        self.calls.append(path)
        if path == "branches/main":
            return {"protected": True, "commit": {"sha": self.main}}
        if path == "rulesets/24182301":
            return {"enforcement": "active", "bypass_actors": [],
                    "conditions": {"ref_name": {"include": ["refs/heads/main"]}},
                    "rules": [{"type": "required_status_checks", "parameters": {
                        "strict_required_status_checks_policy": True,
                        "required_status_checks": [
                            {"context": "validate", "integration_id": 15368},
                            {"context": "portfolio-phase1-gate", "integration_id": 5121826}]}}]}
        if path == "pulls?state=all&per_page=30":
            return copy.deepcopy(self.rows)
        if path == "issues?state=open&per_page=60":
            return copy.deepcopy(self.issues)
        if path == "actions/runs?per_page=30":
            return {"workflow_runs": copy.deepcopy(self.runs)}
        if path.startswith("actions/runs/") and path.endswith("/jobs?per_page=100"):
            run_id = int(path.split("/")[2])
            return {"total_count": 1, "jobs": [{
                "name": "monitor", "run_id": run_id, "run_attempt": 1,
                "head_sha": MAIN, "status": "completed",
                "conclusion": next(
                    (x["conclusion"] for x in self.runs if x.get("id") == run_id),
                    "success"),
                "steps": copy.deepcopy(getattr(self, "core_steps", [])),
            }]}
        if path == "commits/" + HEAD + "/check-runs?per_page=100":
            return {"total_count": 2, "check_runs": [
                {"name": "validate", "head_sha": HEAD,
                 "app": {"id": 15368}, "status": "completed", "conclusion": "success"},
                {"name": "portfolio-phase1-gate", "head_sha": HEAD,
                 "app": {"id": self.independent},
                 "status": "completed", "conclusion": "success"}]}
        raise AssertionError("unexpected route " + path)


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.api = Fake()

    def snapshot(self):
        return v.report(self.api, expected_main=MAIN, generated_at=AT)

    def test_original_checks_only_and_real_pr_merge_count(self):
        x = self.snapshot()
        self.assertEqual(x["source"], "ORIGINAL_GITHUB_API")
        self.assertEqual(x["metrics"]["repair_prs_seen_in_sample"], 1)
        self.assertEqual(x["metrics"]["repair_prs_merged_in_sample"], 1)
        self.assertEqual(x["metrics"]["merged_prs_verified_by_both_apps"], 1)
        self.assertEqual(x["metrics"]["main_cycle_successes_in_sample"], 1)
        self.assertEqual(x["metrics"]["main_cycle_failures_in_sample"], 1)
        self.assertIsNone(x["metrics"]["actual_operating_cost_usd"])
        self.assertIsNone(x["metrics"]["production_deployments_verified"])
        self.assertEqual(x["metrics"]["historical_retired_issue_candidates"], 0)
        self.assertEqual(x["metrics"]["open_incident_review_count"], 1)
        self.assertEqual(x["backlog_evidence"][-1]["number"], 210)
        self.assertEqual(x["merged_pr_evidence"][0]["verification"],
                         "VERIFIED_BOTH_APPS")

    def test_forged_independent_issuer_is_not_a_verified_result(self):
        self.api.independent = 999
        x = self.snapshot()
        self.assertEqual(x["metrics"]["merged_prs_verified_by_both_apps"], 0)
        self.assertEqual(x["merged_pr_evidence"][0]["verification"],
                         "NOT_BOTH_APPS_VERIFIED")

    def test_source_drift_stops_all_kpis(self):
        self.api.main = "f" * 40
        with self.assertRaisesRegex(v.ReportError, "MAIN_MOVED"):
            self.snapshot()

    def test_render_escapes_untrusted_titles_and_keeps_unknowns(self):
        html = v.html_report(self.snapshot())
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("UNKNOWN", html)
        self.assertIn("/issues/796", html)
        self.assertIn("/pull/900", html)

    def test_readonly_transport_does_not_allow_arbitrary_urls(self):
        client = v.GitHubReadOnly("a" * 30)
        for path in ("../secrets", "https://elsewhere.invalid", "pulls/900/merge",
                     "contents/.github/workflows/main.yml", "actions/dispatches"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(v.ReportError, "ROUTE_DENIED"):
                    client.get(path)
        self.assertEqual(client.count, 0)

    def test_original_failed_repair_is_not_hidden_as_retired_observation(self):
        issue = {"number": 796, "title": "original six-hour failure", "body": ""}
        self.assertEqual(v._issue_class(issue), "OPEN_INCIDENT_REVIEW_REQUIRED")
        historical = {"number": 699, "title": "six-hour acceptance pending", "body": ""}
        self.assertEqual(v._issue_class(historical), "RETIRED_POLICY_REVIEW_CANDIDATE")
        unrelated = {"number": 999, "title": "Fix current canonical state",
                     "body": "Earlier acceptance/soak was mentioned"}
        self.assertEqual(v._issue_class(unrelated), "ACTIVE_OR_UNRECONCILED")
        active = {"number": 811, "title": "12-hour observation completed?",
                  "body": "Legacy instructions"}
        self.assertEqual(v._issue_class(active), "ACTIVE_REVIEW_REQUIRED")



    def test_same_named_or_manually_dispatched_core_has_no_verified_cycle_credit(self):
        # Original GitHub identity and authenticated scheduling are mandatory;
        # an arbitrary name+SHA+green conclusion is never core evidence.
        self.api.runs = [
            {"id": 101, "name": "brain-cycle-v2",
             "path": ".github/workflows/unreviewed.yml",
             "head_sha": MAIN, "head_branch": "main",
             "repository": {"full_name": v.REPO},
             "run_attempt": 1, "event": "schedule",
             "status": "completed", "conclusion": "success"},
            {"id": 102, "name": "brain-cycle-v2",
             "path": ".github/workflows/brain-cycle.yml",
             "head_sha": MAIN, "head_branch": "main",
             "repository": {"full_name": v.REPO},
             "run_attempt": 2, "event": "schedule",
             "status": "completed", "conclusion": "success"},
            {"id": 103, "name": "brain-cycle-v2",
             "path": ".github/workflows/brain-cycle.yml",
             "head_sha": MAIN, "head_branch": "main",
             "repository": {"full_name": v.REPO},
             "run_attempt": 1, "event": "workflow_dispatch",
             "status": "completed", "conclusion": "success"},
        ]
        self.api.core_steps = []
        result = self.snapshot()
        self.assertEqual(result["metrics"]["main_cycle_successes_in_sample"], 0)
        self.assertEqual(result["metrics"]["unverified_main_cycle_runs_in_sample"], 3)

    def test_verified_original_signed_dispatch_and_failed_run_have_distinct_credit(self):
        def origin_run(run_id, conclusion):
            return {"id": run_id, "name": "brain-cycle-v2",
                    "path": ".github/workflows/brain-cycle.yml",
                    "head_sha": MAIN, "head_branch": "main",
                    "repository": {"full_name": v.REPO},
                    "run_attempt": 1, "event": "workflow_dispatch",
                    "status": "completed", "conclusion": conclusion}
        self.api.runs = [origin_run(104, "success"), origin_run(105, "failure")]
        self.api.core_steps = [{"name": "Verify independently signed Cloudflare Cron provenance",
                                "conclusion": "success"}]
        result = self.snapshot()
        self.assertEqual(result["metrics"]["main_cycle_successes_in_sample"], 1)
        self.assertEqual(result["metrics"]["main_cycle_failures_in_sample"], 1)
        self.assertEqual(result["metrics"]["unverified_main_cycle_runs_in_sample"], 0)

    def test_failed_original_without_signed_origin_not_counted(self):
        self.api.runs = [
            {"id": 106, "name": "brain-cycle-v2",
             "path": ".github/workflows/brain-cycle.yml",
             "head_sha": MAIN, "head_branch": "main",
             "repository": {"full_name": v.REPO},
             "run_attempt": 1, "event": "workflow_dispatch",
             "status": "completed", "conclusion": "failure"},
        ]
        self.api.core_steps = [{"name": "Verify independently signed Cloudflare Cron provenance",
                                "conclusion": "failure"}]
        got = self.snapshot()
        self.assertEqual(got["metrics"]["main_cycle_failures_in_sample"], 0)
        self.assertEqual(got["metrics"]["unverified_main_cycle_runs_in_sample"], 1)

if __name__ == "__main__":
    unittest.main()
