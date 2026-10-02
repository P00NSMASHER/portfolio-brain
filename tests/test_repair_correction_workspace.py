import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class RepairCorrectionWorkspaceTests(unittest.TestCase):
    def test_workflow_failure_commit_stages_only_validated_paths(self):
        workflow=(ROOT/".github/workflows/portfolio-autonomous-repair.yml").read_text(encoding="utf-8")
        step=workflow.split("- name: Create isolated workflow-failure candidate commit",1)[1].split("- name: Open protected workflow-failure repair pull request",1)[0]
        self.assertNotIn("git add -A",step)
        self.assertIn('validation.get("changed_paths")',step)
        self.assertIn('subprocess.run(["git","add","--",*changed],check=True)',step)
        self.assertIn('["git","diff","--cached","--name-only","-z"]',step)
        self.assertIn("staged candidate paths differ from validated candidate paths",step)

    def test_clean_candidates_wait_for_exact_head_foundation_before_verifier_handoff(self):
        workflow=(ROOT/".github/workflows/portfolio-autonomous-repair.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("gh workflow run foundation-ci.yml"),2)
        self.assertEqual(workflow.count('gh run watch "$FOUNDATION_RUN_ID" --repo "$GITHUB_REPOSITORY" --exit-status'),2)
        self.assertEqual(workflow.count('test "$RUN_SHA" = "$CANDIDATE_SHA"'),2)
        self.assertEqual(workflow.count('test "$RUN_BRANCH" = "$REPAIR_BRANCH"'),2)
        self.assertEqual(workflow.count('test "$RUN_EVENT" = "workflow_dispatch"'),2)
        self.assertEqual(workflow.count('test "$RUN_CONCLUSION" = "success"'),2)
        self.assertEqual(workflow.count("gh workflow run portfolio-independent-verifier.yml"),2)
        self.assertEqual(workflow.count('-f foundation_run_id="$FOUNDATION_RUN_ID"'),2)

    def test_explicit_verifier_handoff_is_bound_to_successful_foundation_evidence(self):
        workflow=(ROOT/".github/workflows/portfolio-independent-verifier.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:",workflow)
        self.assertIn("foundation_run_id:",workflow)
        self.assertIn("Bind explicit verifier dispatch to successful exact-head Foundation",workflow)
        self.assertIn('[[ "$FOUNDATION_RUN_ID" =~ ^[1-9][0-9]*$ ]]',workflow)
        self.assertIn("factory/auto-repair-*",workflow)
        self.assertIn('/actions/runs/${FOUNDATION_RUN_ID}',workflow)
        self.assertIn('"workflow": run.get("name") == "foundation-ci"',workflow)
        self.assertIn('run.get("path") == ".github/workflows/foundation-ci.yml"',workflow)
        self.assertIn('run.get("event") == "workflow_dispatch"',workflow)
        self.assertIn('run.get("status") == "completed" and run.get("conclusion") == "success"',workflow)
        self.assertIn('run.get("head_sha") == expected_sha and run.get("head_branch") == expected_branch',workflow)

    def test_failed_first_pass_cleans_generated_residue_without_widening_policy(self):
        workflow=(ROOT/".github/workflows/portfolio-autonomous-repair.yml").read_text(encoding="utf-8")
        self.assertIn("Restore validated candidate workspace before bounded correction",workflow)
        self.assertIn('validation.get("changed_paths")',workflow)
        self.assertIn("git reset --hard HEAD",workflow)
        self.assertIn("git clean -fd",workflow)
        self.assertIn("Do not create any additional file during this correction pass",workflow)
        self.assertIn("Edit only these already-validated candidate paths",workflow)
        policy=(ROOT/"repair/AUTONOMOUS_REPAIR_POLICY.json").read_text(encoding="utf-8")
        self.assertIn('"max_changed_files": 20',policy)

if __name__=="__main__":
    unittest.main()
