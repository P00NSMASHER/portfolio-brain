import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from governance.validate_boundaries import (BoundaryValidationError, candidate_pr_authority,
                                             validate_boundaries)

ROOT=Path(__file__).resolve().parents[1]

class GovernanceBoundaryTests(unittest.TestCase):
    def test_checked_in_authority_matrix_is_complete_and_fail_closed(self):
        result=validate_boundaries()
        self.assertEqual(result["projects"],12)
        self.assertEqual(result["authority_model"],"DENY_BY_DEFAULT_PROJECT_SCOPED_NO_INHERITANCE")

    def test_no_downstream_project_inherits_candidate_pr_deploy_or_external_action(self):
        policy=json.loads((ROOT/"governance/boundaries.json").read_text())
        downstream=[row for row in policy["project_capabilities"] if row["project_id"]!="PRJ-000"]
        self.assertTrue(all(row["CANDIDATE_PR"]["allowed"] is False for row in downstream))
        self.assertTrue(all(row["DEPLOY"]["allowed"] is False for row in downstream))
        self.assertTrue(all(row["EXTERNAL_ACTION"]["allowed"] is False for row in downstream))


    def test_candidate_write_authority_gates_downstream_token_mint(self):
        denied=candidate_pr_authority(
            "PRJ-004","REPO-007","v8-capturebrief-hosting-doc-4a7c5d6c223b")
        self.assertFalse(denied["allowed"])
        self.assertFalse(denied["token_mint_allowed"])
        self.assertEqual(denied["reason"],"PROJECT_SCOPED_CANDIDATE_WRITE_DENIED")
        self.assertFalse(denied["merge_authority"])
        self.assertFalse(denied["deploy_authority"])

        allowed=candidate_pr_authority(
            "PRJ-000","REPO-008","factory/pb-07-authority-test")
        self.assertTrue(allowed["allowed"])
        self.assertFalse(candidate_pr_authority(
            "PRJ-000","REPO-008","unreviewed/pb-07-authority-test")["allowed"])

        workflow=(ROOT/".github/workflows/v8-scoped-repair.yml").read_text()
        gate="Evaluate project-scoped candidate authority before token mint"
        mint="Mint one-CaptureBrief-repository short-lived draft-only contents token"
        self.assertLess(workflow.index(gate),workflow.index(mint))
        self.assertIn("id: authority",workflow)
        self.assertIn("steps.authority.outputs.allowed == 'true'",workflow)
        self.assertIn("v8-authority.json",workflow)

    def test_abvm_is_observation_only_and_child_facing_changes_stay_human_gated(self):
        policy=json.loads((ROOT/"governance/boundaries.json").read_text())
        abvm=next(row for row in policy["project_capabilities"] if row["project_id"]=="PRJ-006")
        self.assertEqual(abvm["READ_OBSERVE"]["repository_ids"],["REPO-003"])
        self.assertEqual(abvm["READ_OBSERVE"]["scope"],["REPOSITORY_OBSERVATION"])
        self.assertFalse(abvm["CANDIDATE_PR"]["allowed"])
        self.assertFalse(abvm["DEPLOY"]["allowed"])
        self.assertFalse(abvm["EXTERNAL_ACTION"]["allowed"])
        self.assertEqual(policy["actions"]["CHILD_FACING_ACTION"]["decision"],"HUMAN_APPROVAL_REQUIRED")
        self.assertEqual(policy["actions"]["CUSTOMER_EMAIL_GMAIL"]["decision"],"EXPLICIT_MACHINE_POLICY_GATE")

    def test_pages_is_publication_not_production_deploy(self):
        pages=json.loads((ROOT/"governance/boundaries.json").read_text())["actions"]["PAGES_PUBLICATION"]
        self.assertTrue(pages["publication_only"])
        self.assertFalse(pages["production_deploy_authority"])

    def test_chatgpt_and_gmail_are_not_core_runtime_dependencies(self):
        policy=json.loads((ROOT/"governance/boundaries.json").read_text())
        self.assertEqual(policy["core_autonomy_dependencies"],{"interactive_chatgpt_required":False,"gmail_required":False})
        self.assertFalse(policy["actions"]["CUSTOMER_EMAIL_GMAIL"]["core_runtime_dependency"])

if __name__=="__main__":
    unittest.main()
