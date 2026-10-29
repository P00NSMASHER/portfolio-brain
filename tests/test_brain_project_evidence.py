"""Original GitHub ZIP bytes are technical evidence, not buyer/value claims."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from brain.core import BrainError
from brain.project_evidence import verify_original_project_artifacts, main

SHA = "a" * 40
HASH = "b" * 64


def retally():
    rows = []
    for kind, count in (
        ("REVIEW_SCENARIO", 5),
        ("NONMATCH_CONTROL", 5),
        ("KNOWN_BENIGN_SYNTHETIC_TRUTH", 2),
    ):
        for i in range(count):
            before = int(kind == "REVIEW_SCENARIO" and i < 2)
            after = int(kind == "REVIEW_SCENARIO" or
                        kind == "KNOWN_BENIGN_SYNTHETIC_TRUTH")
            rows.append({
                "case_id": kind.lower().replace("_", "-") + "-" + str(i),
                "truth_class": kind,
                "population_hash": HASH,
                "input_hash": HASH,
                "baseline_batch_hash": HASH,
                "candidate_queue_hash": HASH,
                "baseline_reviews": before,
                "candidate_reviews": after,
                "candidate_case_hashes": [HASH] * after,
                "baseline_runtime_ns_single_sample": 1,
                "candidate_runtime_ns_single_sample": 2,
            })
    summary = {}
    for kind in ("REVIEW_SCENARIO", "NONMATCH_CONTROL",
                 "KNOWN_BENIGN_SYNTHETIC_TRUTH"):
        group = [r for r in rows if r["truth_class"] == kind]
        summary[kind] = {
            "cases": len(group),
            "baseline_cases_flagged":
                sum(r["baseline_reviews"] > 0 for r in group),
            "candidate_cases_flagged":
                sum(r["candidate_reviews"] > 0 for r in group),
        }
    return {
        "schema_version": 1,
        "evidence_kind": "SYNTHETIC_FIRST_PARTY_COMPARISON",
        "production_deployed": False,
        "real_customer_outcome": "NOT_MEASURED",
        "human_time_saved": None,
        "verified_revenue": None,
        "validated_recovery_cents": 0,
        "source_base_sha": SHA,
        "source_sha256": {
            key: HASH for key in (
                "contracts.py", "finding_factory.py",
                "duplicate_charge_review.py", "reviewer_cockpit.py",
                "brain_review_measurement.py",
            )
        },
        "cases": rows,
        "summary": summary,
    }


def factory():
    rows = []
    for family, count, prefix in (
        ("document-workflow", 3, "document"),
        ("quote-to-order", 4, "quotes"),
        ("inventory-control", 4, "inventory"),
    ):
        for i in range(count):
            rows.append({
                "id": prefix + "-" + str(i),
                "family": family,
                "sourceDigest": HASH,
                "sourceUrls": ["https://www.nist.gov/example",
                               "https://www.energy.gov/example"],
                "existingBuyerEvidence": "NOT_COLLECTED",
                "confirmedConversations": None,
                "verifiedWorkflowCompletions": None,
                "verifiedRevenue": None,
                "buyerDemandValidated": False,
                "deploymentApproved": False,
                "externalContactPermitted": False,
                "consentRequiredForAnyRealEvaluation": True,
            })
    return {
        "kind": "unified-operator-buyer-evidence-review",
        "independentExternalBuyerEvidence": False,
        "measuredRealBuyerPain": None,
        "realCustomers": None,
        "collectedRevenue": None,
        "externalMessagesSent": 0,
        "paymentsSent": 0,
        "publicDeploymentEnabled": False,
        "autoApprove": False,
        "releaseApproved": False,
        "totalReviewPackets": len(rows),
        "familyCounts": {
            "document-workflow": 3,
            "quote-to-order": 4,
            "inventory-control": 4,
        },
        "packets": rows,
    }


def fixture(directory):
    manifest = {
        "schema_version": 1,
        "scope": "EXACT_SOURCE_GITHUB_ARTIFACT_REVIEW",
        "sources": {},
    }
    for name, repo, artifact, document, run, aid in [
        ("retally", "P00NSMASHER/github-value-hunt-ledger",
         "retally-synthetic-review.json", retally(), 123, 201),
        ("product-factory", "P00NSMASHER/x402-product-factory",
         "factory-buyer-review.json", factory(), 124, 202),
    ]:
        zip_path = directory / (name + ".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(artifact, json.dumps(document))
        prefix = (f"retally-review-{SHA}-{run}" if name == "retally"
                  else f"buyer-review-agenda-{run}")
        manifest["sources"][name] = {
            "repository": repo,
            "head_sha": SHA,
            "run_id": run,
            "artifact_id": aid,
            "artifact_name": prefix,
            "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
            "zip_path": str(zip_path),
        }
    return manifest


def reseal(manifest, project, text):
    entry = manifest["sources"][project]
    file = Path(entry["zip_path"])
    name = ("retally-synthetic-review.json" if project == "retally"
            else "factory-buyer-review.json")
    with zipfile.ZipFile(file, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, text)
    entry["zip_sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()


class OriginalProjectEvidenceTests(unittest.TestCase):
    def test_good_synthetic_provider_digests_report_real_review_tradeoff(self):
        with tempfile.TemporaryDirectory() as folder:
            m = fixture(Path(folder))
            proof = verify_original_project_artifacts(m)
        self.assertEqual(proof["status"], "PASS")
        self.assertTrue(proof["original_zip_digest_and_crc_verified"])
        self.assertFalse(proof["authority_to_merge_deploy_or_contact"])
        self.assertIsNone(proof["verified_revenue"])
        self.assertEqual(proof["independently_adjudicated_customer_outcomes"], None)
        tradeoff = proof["projects"]["retally"]["outcome"]
        self.assertEqual(tradeoff["additional_designed_cases_flagged"], 3)
        self.assertEqual(tradeoff["additional_known_benign_review_burden"], 2)
        self.assertEqual(tradeoff["candidate_nonmatch_cases_flagged"], 0)
        self.assertIsNone(tradeoff["reviewer_minutes_saved"])
        agenda = proof["projects"]["product-factory"]["outcome"]
        self.assertEqual(agenda["unverified_hypotheses"], 11)
        self.assertEqual(agenda["family_counts"], {
            "document-workflow": 3, "quote-to-order": 4,
            "inventory-control": 4,
        })
        self.assertIsNone(agenda["buyer_interviews"])
        self.assertFalse(agenda["independent_demand"])

    def test_source_sha_mismatch_and_artifact_identity_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            source = fixture(Path(folder))
            for patch in (
                ("retally", "head_sha", "f"*40),
                ("retally", "artifact_id", False),
                ("product-factory", "repository", "attacker/repo"),
                ("product-factory", "artifact_name", "unbound"),
                ("retally", "zip_sha256", "0"*64),
            ):
                m = json.loads(json.dumps(source))
                p, k, v = patch
                m["sources"][p][k] = v
                with self.subTest(patch=patch), self.assertRaises(BrainError):
                    verify_original_project_artifacts(m)

    def test_added_benign_burden_cannot_be_hidden_by_forged_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            m = fixture(Path(folder))
            altered = retally()
            altered["summary"]["KNOWN_BENIGN_SYNTHETIC_TRUTH"]["candidate_cases_flagged"] = 0
            reseal(m, "retally", json.dumps(altered))
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)

    def test_report_rejects_synthetic_money_or_claimed_customers(self):
        with tempfile.TemporaryDirectory() as folder:
            m = fixture(Path(folder))
            r = retally()
            r["verified_revenue"] = 200
            reseal(m, "retally", json.dumps(r))
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)
            m = fixture(Path(folder))
            f = factory()
            f["realCustomers"] = 1
            reseal(m, "product-factory", json.dumps(f))
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)

    def test_factory_cannot_misstate_verified_buyer_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            m = fixture(Path(folder))
            f = factory()
            f["packets"][0]["confirmedConversations"] = 3
            reseal(m, "product-factory", json.dumps(f))
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)

    def test_case_hash_and_duplicate_ids_are_still_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            m = fixture(Path(folder))
            r = retally()
            r["cases"][0]["case_id"] = r["cases"][1]["case_id"]
            reseal(m, "retally", json.dumps(r))
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)
            m = fixture(Path(folder))
            r = retally()
            r["cases"][0]["candidate_case_hashes"] = []
            reseal(m, "retally", json.dumps(r))
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)

    def test_nested_paths_and_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            m = fixture(Path(folder))
            r = m["sources"]["retally"]
            p = Path(r["zip_path"])
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("../unexpected.json", '{"status":"PASS"}')
            r["zip_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)
            m = fixture(Path(folder))
            reseal(m, "retally", '{"schema_version":1,"schema_version":1}')
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)

    def test_symlink_aliases_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            m = fixture(Path(folder))
            root = Path(folder)
            link = root / "alias.zip"
            try:
                link.symlink_to(m["sources"]["retally"]["zip_path"])
            except (OSError, NotImplementedError):
                return
            m["sources"]["retally"]["zip_path"] = str(link)
            with self.assertRaises(BrainError):
                verify_original_project_artifacts(m)

    def test_cli_creates_private_report_and_never_promotes_value(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            m = fixture(root)
            manifest_path = root / "inputs.json"
            manifest_path.write_text(json.dumps(m))
            output = root / "verified-private-report"
            self.assertEqual(main(["--manifest", str(manifest_path),
                                   "--output", str(output)]), 0)
            data = json.loads((output / "report.json").read_text())
            self.assertEqual(data["status"], "PASS")
            self.assertIsNone(data["verified_revenue"])
            self.assertFalse(data["authority_to_merge_deploy_or_contact"])


if __name__ == "__main__":
    unittest.main()
