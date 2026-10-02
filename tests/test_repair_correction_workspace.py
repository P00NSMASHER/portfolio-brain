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

    def test_trusted_pr_submitter_is_scoped_to_pr_creation_only(self):
        workflow=(ROOT/".github/workflows/portfolio-autonomous-repair.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("secrets.PORTFOLIO_REPAIR_PR_TOKEN"),4)
        workflow_pr=workflow.split("- name: Open protected workflow-failure repair pull request",1)[1].split("- name: Submit scheduler candidate through software factory",1)[0]
        self.assertIn('GH_TOKEN: ${{ secrets.PORTFOLIO_REPAIR_PR_TOKEN || github.token }}',workflow_pr)
        self.assertIn("TRUSTED_PR_SUBMITTER:",workflow_pr)
        factory_pr=workflow.split("- name: Record independent factory PASS and open protected PR",1)[1].split("- name: Preserve independent factory evidence",1)[0]
        self.assertIn('PORTFOLIO_FACTORY_TOKEN: ${{ secrets.PORTFOLIO_REPAIR_PR_TOKEN || github.token }}',factory_pr)
        prefix=workflow.split("- name: Open protected workflow-failure repair pull request",1)[0]
        self.assertNotIn("PORTFOLIO_REPAIR_PR_TOKEN",prefix)

    def test_trusted_pr_submitter_avoids_duplicate_foundation_dispatch(self):
        workflow=(ROOT/".github/workflows/portfolio-autonomous-repair.yml").read_text(encoding="utf-8")
        self.assertIn("steps.pr.outputs.trusted_submitter != 'true'",workflow)
        self.assertIn("steps.factory_pr.outputs.trusted_submitter != 'true'",workflow)
        self.assertEqual(workflow.count("gh workflow run foundation-ci.yml"),2)
        verifier=(ROOT/".github/workflows/portfolio-independent-verifier.yml").read_text(encoding="utf-8")
        self.assertNotIn("workflow_dispatch:",verifier)
        self.assertIn('workflows: ["foundation-ci"]',verifier)
        self.assertIn("actions: read",verifier)
        self.assertNotIn("actions: write",verifier)

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
