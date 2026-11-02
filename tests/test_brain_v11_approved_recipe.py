"""Safe recipe match on exact Git source; not a fabricated unattended merge."""
from copy import deepcopy
import json
import subprocess
import tempfile
from pathlib import Path
import unittest

from brain.v10 import engineering_factory as factory
from brain.v11 import approved_recipe_runner as recipes

SOURCE = b"def compute():\n    return 1\n"


class ApprovedRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v11-approved-recipe-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = self.root / "brain" / "changes.py"
        path.parent.mkdir()
        path.write_bytes(SOURCE)
        subprocess.run(["git", "-C", str(self.root), "init", "-q"],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.root), "add", "--all"],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit",
                        "-qm", "reviewed fixture"], check=True)
        self.sha = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.receipt = {
            "schema_version": 1,
            "status": "ORIGINAL_AUTOMATIC_FAILURE_CLASSIFIED_NOT_REPAIRED",
            "repository": factory.REPOSITORY, "source_sha": self.sha,
            "source_run_id": 12345678,
            "original_event": "workflow_dispatch",
            "original_conclusion": "failure",
            "failed_stage_families": ["PREFLIGHT"],
            "stage_is_root_cause": False,
            "candidate_patch_prepared": False,
            "draft_pr_created": False,
            "merged": False, "production_accepted": False, "provider_writes": 0,
        }
        self.receipt["fingerprint_sha256"] = factory.sha256(factory.canonical({
            "repository": factory.REPOSITORY, "source_sha": self.sha,
            "run_id": 12345678, "stages": ["PREFLIGHT"]}).encode())
        self.registry = {
            "schema_version": 1, "repository": factory.REPOSITORY,
            "recipes": [{
                "id": "bounded-safe-preflight-recipe",
                "stage_family": "PREFLIGHT",
                "changes": [{
                    "path": "brain/changes.py",
                    "expected_sha256": factory.sha256(SOURCE),
                    "old": "    return 1\n", "new": "    return 2\n",
                }],
            }],
        }

    def test_real_local_git_source_and_reviewed_recipe_prepare_v10_spec_only(self):
        result, spec = recipes.choose(self.root, self.receipt, self.registry)
        self.assertEqual(result["status"],
                         "SOURCE_LOCKED_REVIEWED_RECIPE_PREPARED_NOT_TESTED")
        self.assertTrue(result["eligible"])
        self.assertEqual(spec["failure_run_id"], 12345678)
        self.assertEqual(spec["base_sha"], self.sha)
        self.assertEqual(spec["repository"], factory.REPOSITORY)
        candidate = factory.prepare(spec, {"brain/changes.py": SOURCE})
        self.assertEqual(candidate["operation_id"], result["operation_id"])
        self.assertEqual((self.root/"brain/changes.py").read_bytes(), SOURCE)
        self.assertFalse(result["red_green_tested"])
        self.assertFalse(result["draft_pr_created"])
        self.assertFalse(result["merged"])
        self.assertEqual(result["provider_writes"], 0)

    def test_empty_registry_creates_no_spec_or_fake_fix(self):
        empty = {**self.registry, "recipes": []}
        result, spec = recipes.choose(self.root, self.receipt, empty)
        self.assertIsNone(spec)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["status"], "NO_PREAPPROVED_SOURCE_FIX")
        self.assertFalse(result["draft_pr_created"])

    def test_unreviewed_control_path_symlink_and_drifting_blob_are_refused(self):
        bad = deepcopy(self.registry)
        bad["recipes"][0]["changes"][0]["path"] = "brain/v11/verified_delivery.py"
        with self.assertRaisesRegex(factory.FactoryError, "NOT_APPROVED"):
            recipes.choose(self.root, self.receipt, bad)
        bad = deepcopy(self.registry)
        bad["recipes"][0]["changes"][0]["path"] = "../../secrets.txt"
        with self.assertRaisesRegex(factory.FactoryError, "PATH_REFUSED"):
            recipes.choose(self.root, self.receipt, bad)
        bad = deepcopy(self.registry)
        bad["recipes"][0]["changes"][0]["expected_sha256"] = "0" * 64
        with self.assertRaisesRegex(factory.FactoryError, "SOURCE_HASH"):
            recipes.choose(self.root, self.receipt, bad)

    def test_ambiguous_or_duplicate_reviewed_recipe_never_auto_selects(self):
        bad = deepcopy(self.registry)
        second = deepcopy(bad["recipes"][0])
        second["id"] = "another-safe-preflight-recipe"
        bad["recipes"].append(second)
        with self.assertRaisesRegex(factory.FactoryError, "AMBIGUOUS"):
            recipes.choose(self.root, self.receipt, bad)
        bad["recipes"][1]["id"] = bad["recipes"][0]["id"]
        with self.assertRaisesRegex(factory.FactoryError, "RECIPE_ENTRY_INVALID"):
            recipes.choose(self.root, self.receipt, bad)

    def test_forged_failure_receipt_wrong_status_or_run_cannot_prepare_spec(self):
        for key, fake in (
            ("source_sha", "f" * 40),
            ("source_run_id", 0),
            ("status", "MERGED_LIVE_REPAIR"),
            ("provider_writes", 1),
            ("fingerprint_sha256", "f" * 64),
            ("original_event", "push"),
        ):
            bad = deepcopy(self.receipt)
            bad[key] = fake
            with self.subTest(key=key), self.assertRaises(factory.FactoryError):
                recipes.choose(self.root, bad, self.registry)

    def test_worktree_tampering_before_recipe_is_rejected(self):
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_untracked.py").write_text("assert True\n")
        with self.assertRaisesRegex(factory.FactoryError, "WORKSPACE_DIRTY"):
            recipes.choose(self.root, self.receipt, self.registry)

    def test_document_outputs_exclusive_and_no_git_writes(self):
        with tempfile.TemporaryDirectory(prefix="v11-recipe-receipts-") as outside:
            destination = Path(outside)
            registry_path = destination / "registry.json"
            registry_path.write_text(json.dumps(self.registry))
            receipt_path = destination / "receipt.json"
            receipt_path.write_text(json.dumps(self.receipt))
            spec_path = destination / "spec.json"
            decision_path = destination / "decision.json"
            args = ["--receipt", str(receipt_path), "--registry", str(registry_path),
                    "--workspace", str(self.root), "--spec", str(spec_path),
                    "--decision", str(decision_path)]
            self.assertEqual(recipes.main(args), 0)
            self.assertTrue(spec_path.exists())
            self.assertTrue(decision_path.exists())
            self.assertEqual(spec_path.stat().st_mode & 0o077, 0)
            self.assertEqual(decision_path.stat().st_mode & 0o077, 0)
            self.assertEqual(recipes.main(args), 2)  # no clobber or retry


if __name__ == "__main__":
    unittest.main()
