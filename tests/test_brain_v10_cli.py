"""End-to-end local v10 CLI preparation and publish-authorization tests."""
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from brain.v10 import __main__ as cli
from brain.v10 import engineering_factory as factory
from test_brain_v10_factory import manifest, ORIGINAL, FakeProvider

class V10CLITests(unittest.TestCase):
    def test_local_cli_emits_real_changed_source_test_receipt_without_remote_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec.json"
            spec.write_text(json.dumps(manifest()))
            output = root / "receipt.json"
            fake_tests = {"status": "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI",
                          "operation_id": factory.prepare(
                              manifest(), {"brain/demo.py": ORIGINAL})["operation_id"],
                          "output_sha256": "c"*64}
            with patch.object(cli, "_checkout_sources",
                              return_value={"brain/demo.py": ORIGINAL}), \
                 patch.object(factory, "run_isolated_tests", return_value=fake_tests), \
                 patch.object(factory, "GitHubTransport") as transport:
                result = cli.run(spec, root, receipt=output)
            transport.assert_not_called()
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(output.read_text())["status"],
                             "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI")
            self.assertFalse(result["production_accepted"])
            self.assertFalse(result["merged"])
            self.assertFalse(result["independent_ci_verified"])
            self.assertEqual(output.stat().st_mode & 0o077, 0)

    def test_draft_cli_never_merges_and_never_contacts_other_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec.json"
            spec.write_text(json.dumps(manifest()))
            candidate = factory.prepare(manifest(), {"brain/demo.py": ORIGINAL})
            fake_tests = {"status": "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI",
                          "operation_id": candidate["operation_id"],
                          "output_sha256": "d" * 64}
            api = FakeProvider()
            with patch.object(cli, "_checkout_sources",
                              return_value={"brain/demo.py": ORIGINAL}), \
                 patch.object(factory, "run_isolated_tests", return_value=fake_tests), \
                 patch.object(factory, "GitHubTransport", return_value=api):
                result = cli.run(spec, root, publish=True,
                                 intent=root/"intent.json", receipt=root/"receipt.json",
                                 token="x"*30)
            self.assertEqual(result["status"], "DRAFT_PR_CREATED_NOT_APPROVED")
            self.assertTrue((root/"intent.json").exists())
            self.assertFalse(result["deployed"])
            self.assertEqual([route for method,route,_ in api.calls if method=="POST"],
                             ["git/refs", "pulls"])

    def test_worktree_sha_mismatch_is_hard_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/"brain").mkdir()
            (root/"brain/demo.py").write_bytes(ORIGINAL)
            with patch.object(cli.subprocess,"run", return_value=
                              types.SimpleNamespace(returncode=0, stdout="f"*40+"\n")):
                with self.assertRaisesRegex(factory.FactoryError,
                                            "FACTORY_CHECKOUT_WRONG_SOURCE"):
                    cli._checkout_sources(root, manifest())

    def test_untrusted_or_duplicate_input_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root/"bad.json"
            bad.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaises(factory.FactoryError):
                cli._read_spec(bad)
            good = root/"good.json"
            good.write_text(json.dumps(manifest()))
            alias = root/"alias.json"
            alias.symlink_to(good)
            with self.assertRaisesRegex(factory.FactoryError,
                                        "FACTORY_MANIFEST_UNSAFE"):
                cli._read_spec(alias)

    def test_receipt_is_append_only_and_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/"receipt.json"
            cli._write_receipt(target, {"status":"FIRST"})
            with self.assertRaises(FileExistsError):
                cli._write_receipt(target, {"status":"SECOND"})
            self.assertEqual(json.loads(target.read_text())["status"],"FIRST")

if __name__=="__main__":
    unittest.main()
