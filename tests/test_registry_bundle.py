import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from registry.validate_registry import validate_registry_bundle

class RegistryBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.projects=json.loads((ROOT/"registry/projects.json").read_text())["projects"]
        cls.profiles=json.loads((ROOT/"registry/autonomy_profiles.json").read_text())["profiles"]
        cls.coverage=json.loads((ROOT/"registry/PORTFOLIO_COVERAGE.json").read_text())["items"]

    def test_cross_file_registry_validates(self):
        counts=validate_registry_bundle()
        self.assertEqual(counts["projects"],12)
        self.assertEqual(counts["autonomy_profiles"],12)
        self.assertGreaterEqual(counts["coverage_items"],60)

    def test_inherited_stable_ids_preserved(self):
        ids={p["project_id"] for p in self.projects}
        self.assertEqual({f"PRJ-{i:03d}" for i in range(12)},ids)

    def test_every_project_has_one_matching_profile(self):
        by_project={}
        for profile in self.profiles:
            self.assertNotIn(profile["project_id"],by_project)
            by_project[profile["project_id"]]=profile
        self.assertEqual({p["project_id"] for p in self.projects},set(by_project))

    def test_all_project_runtimes_enabled_without_self_approval(self):
        for profile in self.profiles:
            self.assertTrue(profile["runtime_enabled"])
            self.assertIn(profile["permissions"]["ACT"]["decision"],{"HUMAN_APPROVAL_REQUIRED","PROHIBITED"})
            self.assertFalse(profile["separation_of_duties"]["builder_may_self_approve"])

    def test_no_repository_adapter_is_enabled_in_step2(self):
        for project in self.projects:
            for binding in project["repository_bindings"]:
                self.assertIn(binding["integration_status"],{"DECLARED","BLOCKED"})

    def test_owner_named_portfolio_coverage(self):
        names={x["name"] for x in self.coverage}
        required={
          "RecoveryWorks","RecoveryOS","Freight Recovery","AP Recovery","Payer Recovery",
          "Utility Recovery","Duty Recovery","SaaS Recovery","Telecom Recovery","Rebate Recovery",
          "Lease Recovery","Construction Recovery","Tax Recovery","Insurance Recovery","Cloud Recovery",
          "Merchant Fee Recovery","Parcel Recovery","Procurement Recovery","Warranty/Credit Recovery",
          "Payroll/Benefit Billing Recovery","Recovery Scan 360","PermitPlate","PermitPlate NYC",
          "CaptureBrief","ScopeSignal","Recovery Proof SLA","Commission/Payout Assurance",
          "AP Leakage Assurance","Money-State Integrity","Revenue Assurance concepts",
          "StarBlox","StarBlox learning systems","Star Market","avatar/equipment/home/Buddy systems",
          "StarBlox artwork pipeline","ABVM School Star World","ABVM Grade 2 Parent Companion",
          "school-information ingestion/refresh systems","trading-platform",
          "historical market-surveillance research","Hunter / GitHub Value Hunt",
          "technology-intelligence experiments","search-strategy research","data/repository discovery",
          "model evaluation","FMC tariff research","Hospital Price Transparency MRF research",
          "TiC payer MRF research","URDB utility-rate research","AI Business OS","Business OS",
          "persistent agents","Truth Engine","Value Memory","Knowledge Graph","entity canonicalization",
          "governance/control plane","software factory","portfolio allocator","learning engine",
          "training environment","repair pipeline","skill evaluation/promotion","Browser Gateway",
          "GitHub automation","future autonomous infrastructure"
        }
        self.assertTrue(required <= names, sorted(required-names))

if __name__=="__main__":
    unittest.main()
