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
