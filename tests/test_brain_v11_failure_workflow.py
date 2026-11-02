"""Original-run failure intake must not weaken existing workflow authority."""
from pathlib import Path
import unittest

from brain.v8.authority import runtime_authority

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/v8-scoped-repair.yml"
CORE = ROOT / ".github/workflows/brain-cycle.yml"


class ReadOnlyOriginalFailureJobTests(unittest.TestCase):
    def stage(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(content.count("\n  classify-original-failed-core:"), 1)
        return content.split("\n  classify-original-failed-core:", 1)[1]

    def test_original_successful_core_and_v8_runtime_unchanged(self):
        full = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  propose-only:", full)
        self.assertIn("  verified-results-after-core:", full)
        self.assertIn("repositories: capturebrief", full)
        self.assertIn("permission-contents: write", full)
        self.assertEqual(runtime_authority()["workflow_declares"]["repository_default"],
                         {"contents": "read"})
        self.assertNotIn("python -m brain.v11.failure_triage",
                         CORE.read_text(encoding="utf-8"))

    def test_exact_failed_core_is_event_bound_no_tokens_or_new_schedules(self):
        step = self.stage()
        for needle in (
            "github.event.workflow_run.name == 'brain-cycle-v2'",
            "github.event.workflow_run.conclusion == 'failure'",
            "github.event.workflow_run.conclusion == 'timed_out'",
            "github.event.workflow_run.head_branch == 'main'",
            "github.event.workflow_run.head_sha == github.sha",
            "github.event.workflow_run.repository.full_name == 'P00NSMASHER/portfolio-brain'",
            "github.event.workflow_run.event == 'workflow_dispatch'",
            "github.event.workflow_run.event == 'schedule'",
            "run: |", "GITHUB_TOKEN:", "actions: read",
            "contents: read", "persist-credentials: false",
            "python -m brain.v11.failure_triage",
            "--source-sha", "--run-id", "if-no-files-found: error",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, step)
        # Initial provider authentication receives NO writer token. The
        # conditional one-repo candidate token is strictly a later step.
        before_candidate = step.split(
            "      - name: Match one preapproved exact-source repair recipe", 1)[0]
        for forbidden in (
            "create-github-app-token", "PORTFOLIO_RUNTIME_PRIVATE_KEY",
            "PORTFOLIO_VERIFIER_PRIVATE_KEY", "pull-requests: write",
            "contents: write", "workflow_dispatch:",
            "schedule:", "id-token: write", "gh pr merge",
            "permissions: write-all", "gh api --method",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, before_candidate)
        self.assertNotIn("pull_request_target:", WORKFLOW.read_text())

    def test_approved_repair_never_receives_token_without_source_proof(self):
        stage = self.stage()
        candidate = stage.split(
            "      - name: Match one preapproved exact-source repair recipe", 1)[1]
        for required in (
            "python -m brain.v11.approved_recipe_runner",
            "--registry repair/V11_PREAPPROVED_SOURCE_RECIPES.json",
            "--receipt /tmp/brain-v11-failure/receipt.json",
            "--workspace .", "--spec /tmp/brain-v11-failure/approved-spec.json",
            "--reviewed-test /tmp/brain-v11-failure/approved-reviewed-test.json",
            "if test -s /tmp/brain-v11-failure/approved-spec.json",
            'eligible=true', 'eligible=false',
            "if: " + "$" + "{{ steps.recipe.outputs.eligible == 'true' }}",
            "app-id: '5352505'", "repositories: portfolio-brain",
            "permission-contents: write", "permission-pull-requests: write",
            "permission-actions: read", "skip-token-revoke: false",
            "PORTFOLIO_RUNTIME_PRIVATE_KEY", "PORTFOLIO_RUNTIME_TOKEN:",
            "python -m brain.v10", "--publish --intent",
            "--receipt /tmp/brain-v11-failure/v10-redgreen.json",
            "if-no-files-found: error", "retention-days: 7",
        ):
            with self.subTest(required=required):
                self.assertIn(required, candidate)
        self.assertEqual(candidate.count("--reviewed-test /tmp/brain-v11-failure/approved-reviewed-test.json"), 2)
        self.assertNotIn("skip-reviewed-regression", candidate)
        for forbidden in ("gh pr merge", "pull_request_target:", "id-token: write",
                          "gh api --method", "refs/heads/main", "write-all",
                          "portfolio-phase1-gate: success"):
            self.assertNotIn(forbidden, candidate)


if __name__ == "__main__":
    unittest.main()
