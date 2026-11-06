"""A genuine completed Brain core refreshes results without an extra schedule."""
import unittest
from pathlib import Path

from brain.v8.authority import runtime_authority

ROOT = Path(__file__).resolve().parents[1]
SCOPED = ROOT / ".github/workflows/v8-scoped-repair.yml"
CORE = ROOT / ".github/workflows/brain-cycle.yml"
MARKER = "\n  verified-results-after-core:\n"


class V11CoreResultRefreshTests(unittest.TestCase):
    def test_existing_repair_job_and_exact_core_authority_survive(self):
        text = SCOPED.read_text(encoding="utf-8")
        self.assertEqual(text.count(MARKER), 1)
        prior, remainder = text.split(MARKER, 1)
        report = remainder.split("\n  classify-original-failed-core:", 1)[0]
        self.assertIn("  propose-only:", prior)
        self.assertIn("repositories: capturebrief", prior)
        self.assertIn("permission-pull-requests: write", prior)
        self.assertNotIn("PORTFOLIO_RUNTIME_PRIVATE_KEY", report)
        self.assertNotIn("pull-requests: write", report)
        self.assertNotIn("contents: write", report)
        self.assertEqual(runtime_authority()["workflow_declares"]["repository_default"],
                         {"contents": "read"})
        self.assertNotIn("python -m brain.v11.results_dashboard",
                         CORE.read_text(encoding="utf-8"))

    def test_read_only_report_job_is_bound_to_original_completed_main_cycle(self):
        scoped = SCOPED.read_text(encoding="utf-8")
        self.assertIn('workflows: ["brain-cycle-v2"]', scoped)
        report = scoped.split(MARKER, 1)[1].split("\n  classify-original-failed-core:", 1)[0]
        for fragment in (
            "github.event.workflow_run.name == 'brain-cycle-v2'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.head_branch == 'main'",
            "github.event.workflow_run.head_sha == github.sha",
            "github.event.workflow_run.repository.full_name == 'P00NSMASHER/portfolio-brain'",
            "github.event.workflow_run.event == 'workflow_dispatch'",
            "github.event.workflow_run.event == 'schedule'",
            "actions: read", "checks: read", "issues: read",
            "contents: read", "persist-credentials: false",
            'ref: ' + '$' + '{{ github.sha }}',
            'GITHUB_TOKEN: ' + '$' + '{{ github.token }}',
            "--expected-main", "--json /tmp/brain-v11-core/results.json",
            "--html /tmp/brain-v11-core/results.html",
            "if-no-files-found: error", "retention-days: 3"
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, report)
        self.assertNotIn("continue-on-error: true", report)
        self.assertNotIn("create-github-app-token", report)

    def test_read_only_postcore_supports_protected_main_push_without_forged_approval(self):
        scoped = SCOPED.read_text(encoding="utf-8")
        stage = scoped.split(MARKER, 1)[1].split("\\n  classify-original-failed-core:", 1)[0]
        premise = stage.split("    steps:", 1)[0]
        self.assertIn("github.event.workflow_run.conclusion == 'success'", premise)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", premise)
        self.assertIn("github.event.workflow_run.head_sha == github.sha", premise)
        self.assertIn("github.event.workflow_run.run_attempt == 1", premise)
        self.assertIn("github.event.workflow_run.event == 'push'", premise)
        self.assertIn("    permissions:\\n      contents: read\\n      actions: read", stage)
        self.assertIn("python -m brain.v11.owner_inbox", stage)
        self.assertIn("--input /tmp/brain-v11-original/v9-engineering.json", stage)
        self.assertIn("--expected-sha", stage)
        self.assertIn("if-no-files-found: error", stage)
        self.assertNotIn("continue-on-error: true", stage)
        for forbidden in ("actions/create-github-app-token", "permission-contents: write",
                          "pull-requests: write", "id-token: write", "gh pr merge"):
            self.assertNotIn(forbidden, stage)
        core = CORE.read_text(encoding="utf-8")
        self.assertNotIn("python -m brain.v11.owner_inbox", core)

    def test_no_timer_new_workflow_or_privileged_trigger(self):
        scoped = SCOPED.read_text(encoding="utf-8")
        for forbidden in ("\n  schedule:", "pull_request_target:",
                          "\n  workflow_dispatch:", "permission-workflows:",
                          "id-token: write", "gh pr merge", "merge_pull_request"):
            self.assertNotIn(forbidden, scoped)
        self.assertIn("name: v8-scoped-repair-proposal", scoped)
        self.assertIn("Archive newest source-bound engineering results", scoped)
        self.assertNotIn("PORTFOLIO_12H_", scoped)


if __name__ == "__main__":
    unittest.main()
