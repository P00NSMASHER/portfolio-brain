"""An explicit bot review dispatch preserves trusted independent validation."""
from pathlib import Path
import unittest

from brain.core import BrainError
from brain.upgrades import UpgradeAPI, BOT_REVIEW, REPOSITORY

WORKFLOW=Path(__file__).resolve().parents[1]/".github/workflows/portfolio-bot-knowledge-verifier.yml"

class BotReviewDispatchTests(unittest.TestCase):
    def test_only_exact_main_bot_review_inputs_are_dispatchable(self):
        seen=[]
        api=UpgradeAPI(transport=lambda path,method,payload:
                       seen.append((path,method,payload)) or {})
        path=f"/repos/{REPOSITORY}/{BOT_REVIEW}"
        good={"ref":"main","inputs":{"pr_number":"688","head_sha":"a"*40}}
        api.request(path,"POST",good)
        self.assertEqual(seen,[(path,"POST",good)])
        self.assertEqual(api.requests,1)

    def test_ref_wrong_shape_or_other_workflow_denied(self):
        dest=f"/repos/{REPOSITORY}/{BOT_REVIEW}"
        for payload in (
            {"ref":"feature/test","inputs":{"pr_number":"688","head_sha":"a"*40}},
            {"ref":"main","inputs":{"pr_number":"0","head_sha":"a"*40}},
            {"ref":"main","inputs":{"pr_number":"688","head_sha":"notsha"}},
            {"ref":"main","inputs":{"pr_number":688,"head_sha":"a"*40}},
            {"ref":"main","inputs":{"pr_number":"688","head_sha":"a"*40,"approve":True}},
            {"ref":"main","inputs":{"pr_number":"688"}},
        ):
            with self.subTest(payload=payload),self.assertRaises(BrainError):
                UpgradeAPI(transport=lambda *args: {}).request(dest,"POST",payload)
        with self.assertRaises(BrainError):
            UpgradeAPI(transport=lambda *args: {}).request(
                f"/repos/{REPOSITORY}/actions/workflows/unsafe.yml/dispatches",
                "POST",{"ref":"main"})

    def test_main_trusted_source_bot_only_and_independent_gate_in_workflow(self):
        s=WORKFLOW.read_text(encoding="utf-8")
        for part in (
            "workflow_dispatch:",
            "github.ref == 'refs/heads/main'",
            "github.event",  # only exact GitHub event refs are accepted
            "verification.bot_knowledge_admission import inspect",
            "verification.bot_knowledge_admission import foundation_green",
            "--network none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "trusted/verification/independent_verifier.py",
            "PORTFOLIO_VERIFIER_PRIVATE_KEY",
            "sha=\"$CANDIDATE_SHA\"",
            "Merge only the exact validated knowledge PR",
        ):
            if part == "github.event":
                continue
            self.assertIn(part,s)
        self.assertIn("permissions:\n  contents: read\n  actions: read\n  pull-requests: read",s)
        self.assertIn("ref: main",s)
        self.assertIn("persist-credentials: false",s)
        self.assertNotIn("cron:",s)
        self.assertNotIn("workflow_run:",s)
        self.assertNotIn("repository_dispatch:",s)
        self.assertNotIn("contents: write",s)

    def test_pin_action_source_and_never_execute_candidate_in_privileged_runner(self):
        s=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262",s)
        self.assertIn("actions/create-github-app-token@fee1f7d63c2ff003460e3d139729b119787bc349",s)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",s)
        self.assertIn("path: candidate",s)
        self.assertIn("-v \"$PWD/candidate:/src:ro\"",s)
        self.assertIn("set -euo pipefail",s)
        self.assertIn("test \"$(cat verifier-results/full.exit)\" = 0",s)


if __name__=="__main__":
    unittest.main()
