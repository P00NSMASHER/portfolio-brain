import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from registry.validate_project import ProjectValidationError, validate_project_record

SCHEMA = json.loads((ROOT / "schemas" / "PROJECT_SCHEMA.json").read_text())

VALID = {
    "schema_version": "1.0.0",
    "project_id": "PRJ-000",
    "slug": "portfolio-brain",
    "canonical_name": "Portfolio Brain",
    "project_type": "PORTFOLIO",
    "lifecycle_status": "ACTIVE",
    "parent_project_id": None,
    "aliases": ["Portfolio Intelligence System"],
    "categories": ["portfolio_control_plane"],
    "repository_bindings": [{
        "repository_id": "REPO-008",
        "full_name": "P00NSMASHER/portfolio-brain",
        "integration_status": "OBSERVE_ALLOWED"
    }],
    "autonomy_profile_id": "AUT-000",
    "objective_ids": [],
    "metric_ids": [],
    "evidence_policy": "PROVENANCE_REQUIRED",
    "data_boundary": "SANITIZED_CODE_POLICY_AND_RECEIPTS_ONLY",
    "registration_state": "REGISTERED",
    "hard_boundaries": [],
    "provenance": {
        "source_type": "MIGRATED_REGISTRY",
        "source_ref": "portfolio_prework/PROJECT_ID_REGISTRY.json",
        "source_revision": "60c97e366814388d0f10862d1d0737837866361e"
    }
}

class ProjectSchemaTests(unittest.TestCase):
    def test_schema_is_closed_and_requires_identity_authority_links(self):
        self.assertFalse(SCHEMA["additionalProperties"])
        required=set(SCHEMA["required"])
        for key in {
            "project_id","canonical_name","repository_bindings","autonomy_profile_id",
            "objective_ids","metric_ids","evidence_policy","data_boundary","registration_state"
        }:
            self.assertIn(key, required)

    def test_valid_record(self):
        validate_project_record(copy.deepcopy(VALID))

    def test_registration_cannot_hide_unknown_authority_field(self):
        bad=copy.deepcopy(VALID)
        bad["can_deploy"]=True
        with self.assertRaises(ProjectValidationError):
            validate_project_record(bad)

    def test_self_parent_rejected(self):
        bad=copy.deepcopy(VALID)
        bad["parent_project_id"]="PRJ-000"
        with self.assertRaises(ProjectValidationError):
            validate_project_record(bad)

    def test_blocked_repo_requires_blocker(self):
        bad=copy.deepcopy(VALID)
        bad["repository_bindings"][0]["integration_status"]="BLOCKED"
        with self.assertRaises(ProjectValidationError):
            validate_project_record(bad)

    def test_duplicate_repository_binding_rejected(self):
        bad=copy.deepcopy(VALID)
        bad["repository_bindings"].append(copy.deepcopy(bad["repository_bindings"][0]))
        with self.assertRaises(ProjectValidationError):
            validate_project_record(bad)

    def test_bad_identifier_rejected(self):
        bad=copy.deepcopy(VALID)
        bad["project_id"]="portfolio-brain"
        with self.assertRaises(ProjectValidationError):
            validate_project_record(bad)

    def test_live_trading_boundary_can_be_preserved(self):
        market=copy.deepcopy(VALID)
        market.update({
            "project_id":"PRJ-007",
            "slug":"market-surveillance-research",
            "canonical_name":"Market Surveillance Research Platform",
            "project_type":"RESEARCH",
            "lifecycle_status":"ACTIVE_RESEARCH_ONLY",
            "hard_boundaries":["NO_AUTONOMOUS_TRADING","NO_BROKER_ORDER_EXECUTION"],
            "autonomy_profile_id":"AUT-007"
        })
        validate_project_record(market)

if __name__ == "__main__":
    unittest.main()
