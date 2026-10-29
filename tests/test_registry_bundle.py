import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from registry.validate_registry import (
    RegistryValidationError, validate_coverage_items, validate_registry_bundle,
)

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
            if profile["project_id"] in {"PRJ-001","PRJ-002","PRJ-003","PRJ-004","PRJ-005","PRJ-006"}:
                self.assertEqual(profile["permissions"]["ACT"]["decision"],"BOUNDED")
                self.assertNotIn("CUSTOMER_COMMUNICATION",profile["human_approval_required_for"])
                if profile["project_id"] in {"PRJ-005","PRJ-006"}:
                    self.assertIn("CONSEQUENTIAL_CHILD_FACING_CHANGE",profile["human_approval_required_for"])
                    joined=" ".join(profile["permissions"]["ACT"]["conditions"])
                    self.assertIn("VERIFIED_ADULT_STAKEHOLDER",joined)
            else:
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

    def test_scopesignal_preserves_source_without_capturebrief_or_hunter_identity(self):
        by_name={item["name"]:item for item in self.coverage}
        scope=by_name["ScopeSignal"]
        self.assertIsNone(scope["canonical_project_id"])
        self.assertEqual(scope["coverage_status"],"PROJECT_IDENTITY_UNRESOLVED")
        self.assertEqual(scope["item_kind"],"COMMERCIAL_CONCEPT")
        self.assertEqual(scope["source_refs"],[
            "https://github.com/P00NSMASHER/github-value-hunt-ledger/blob/04252c375e8abf8564dd42a5fd5524bf6635a4fa/lanes/04-construction-scopesignal.md",
            "https://github.com/P00NSMASHER/github-value-hunt-ledger/blob/bd169dba2539de9e9fa9338c063b60f453d903de/portfolio_prework/portfolio_inventory.json",
        ])
        self.assertEqual(by_name["CaptureBrief"]["canonical_project_id"],"PRJ-004")
        self.assertEqual(by_name["Hunter / GitHub Value Hunt"]["canonical_project_id"],"PRJ-008")
        self.assertEqual([row["name"] for row in self.coverage
                          if row["canonical_project_id"] is None],["ScopeSignal"])

    def test_unbound_coverage_creates_no_project_profile_or_authority(self):
        projects={p["project_id"]:copy.deepcopy(p) for p in self.projects}
        original=copy.deepcopy(projects)
        validate_coverage_items(self.coverage,projects)
        self.assertEqual(projects,original)
        self.assertEqual(set(projects),{f"PRJ-{i:03d}" for i in range(12)})
        self.assertEqual({p["project_id"] for p in self.profiles},set(projects))
        self.assertTrue(all(p["canonical_name"]!="ScopeSignal" and "ScopeSignal" not in p["aliases"]
                            for p in projects.values()))
        scope=next(row for row in self.coverage if row["name"]=="ScopeSignal")
        for field in ("autonomy_profile_id","runtime_enabled","may_deploy","external_actions_enabled"):
            with self.subTest(field=field):
                bad=copy.deepcopy(scope)
                bad[field]=True
                with self.assertRaisesRegex(RegistryValidationError,"invalid coverage item fields"):
                    validate_coverage_items([bad],projects)

    def test_unresolved_coverage_cannot_claim_any_canonical_project(self):
        scope=next(row for row in self.coverage if row["name"]=="ScopeSignal")
        projects={p["project_id"]:p for p in self.projects}
        for project_id in ("PRJ-004","PRJ-008","PRJ-999",""):
            with self.subTest(project_id=project_id):
                bad=copy.deepcopy(scope)
                bad["canonical_project_id"]=project_id
                with self.assertRaisesRegex(RegistryValidationError,"must not claim a canonical project"):
                    validate_coverage_items([bad],projects)

    def test_unresolved_coverage_requires_concept_and_original_source(self):
        scope=next(row for row in self.coverage if row["name"]=="ScopeSignal")
        projects={p["project_id"]:p for p in self.projects}
        for kind in ("BUSINESS","PRODUCT","INFRASTRUCTURE",None):
            with self.subTest(kind=kind):
                bad=copy.deepcopy(scope); bad["item_kind"]=kind
                with self.assertRaisesRegex(RegistryValidationError,"commercial concepts"):
                    validate_coverage_items([bad],projects)
        for refs in (None,[],"source",{}):
            with self.subTest(refs=refs):
                bad=copy.deepcopy(scope); bad["source_refs"]=refs
                with self.assertRaisesRegex(RegistryValidationError,"source references"):
                    validate_coverage_items([bad],projects)
        bad=copy.deepcopy(scope); bad.pop("source_refs")
        with self.assertRaisesRegex(RegistryValidationError,"invalid coverage item fields"):
            validate_coverage_items([bad],projects)

    def test_unresolved_source_references_require_safe_immutable_file_pins(self):
        scope=next(row for row in self.coverage if row["name"]=="ScopeSignal")
        projects={p["project_id"]:p for p in self.projects}
        good=scope["source_refs"][0]
        for ref in (None,{},good.replace("04252c375e8abf8564dd42a5fd5524bf6635a4fa","main"),
                    good.replace("github.com","github.com.evil.invalid"),
                    good.replace("P00NSMASHER","other-owner"),
                    good.replace("https://","https://user@"),
                    good.replace("/lanes/","/../"),good+"?private=payload",good+"#fragment",
                    good+"\n",good.replace("/lanes/","//lanes/")):
            with self.subTest(ref=ref):
                bad=copy.deepcopy(scope); bad["source_refs"]=[ref]
                with self.assertRaisesRegex(RegistryValidationError,"immutable public owner GitHub"):
                    validate_coverage_items([bad],projects)
        bad=copy.deepcopy(scope); bad["source_refs"]=[good,good]
        with self.assertRaisesRegex(RegistryValidationError,"duplicate coverage source"):
            validate_coverage_items([bad],projects)

    def test_bound_coverage_stays_strict_and_never_infers_missing_project(self):
        bound=next(row for row in self.coverage if row["name"]=="CaptureBrief")
        projects={p["project_id"]:p for p in self.projects}
        for project_id in (None,"PRJ-999","",[]):
            with self.subTest(project_id=project_id):
                bad=copy.deepcopy(bound); bad["canonical_project_id"]=project_id
                with self.assertRaisesRegex(RegistryValidationError,"maps to missing project"):
                    validate_coverage_items([bad],projects)
        bad=copy.deepcopy(bound); bad["source_refs"]=[]
        with self.assertRaisesRegex(RegistryValidationError,"invalid coverage item fields"):
            validate_coverage_items([bad],projects)
        for status in ("VERIFIED","PROJECT_IDENTITY_UNKNOWN",None):
            with self.subTest(status=status):
                bad=copy.deepcopy(bound); bad["coverage_status"]=status
                with self.assertRaisesRegex(RegistryValidationError,"independent validation"):
                    validate_coverage_items([bad],projects)

    def test_coverage_names_remain_unique_across_bound_and_unbound_rows(self):
        scope=copy.deepcopy(next(row for row in self.coverage if row["name"]=="ScopeSignal"))
        bound=copy.deepcopy(next(row for row in self.coverage if row["name"]=="CaptureBrief"))
        scope["name"]=bound["name"]
        with self.assertRaisesRegex(RegistryValidationError,"duplicate coverage name"):
            validate_coverage_items([bound,scope],{p["project_id"]:p for p in self.projects})

if __name__=="__main__":
    unittest.main()
