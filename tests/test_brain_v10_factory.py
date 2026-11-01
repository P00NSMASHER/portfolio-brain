"""Adversarial source, provider, execution and draft-only factory regressions."""
import base64
import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from brain.v10 import engineering_factory as f

SOURCE = "a" * 40
RUN_ID = 12345678
ORIGINAL = b"def compute():\n    return 1\n"
BEFORE = hashlib.sha256(ORIGINAL).hexdigest()

def manifest():
    return {
        "schema_version": 1,
        "repository": f.REPOSITORY,
        "base_sha": SOURCE,
        "failure_run_id": RUN_ID,
        "changes": [{
            "path": "brain/demo.py",
            "expected_sha256": BEFORE,
            "old": "    return 1\n",
            "new": "    return 2\n",
        }],
    }

class FakeProvider:
    def __init__(self):
        self.calls = []
        self.main = SOURCE
        self.conclusion = "failure"
        self.failed_step = "Exact-SHA deterministic preflight"
        self.fail_write = False
        self.pr_number = 900
    def request(self, method, route, payload=None):
        self.calls.append((method, route, payload))
        if method == "GET":
            if route == "branches/main":
                return {"commit": {"sha": self.main}}
            if route == "actions/runs/" + str(RUN_ID):
                return {
                    "id": RUN_ID, "name": "brain-cycle-v2",
                    "path": ".github/workflows/brain-cycle.yml",
                    "repository": {"full_name": f.REPOSITORY},
                    "head_branch": "main", "head_sha": SOURCE,
                    "run_attempt": 1, "event": "workflow_dispatch",
                    "status": "completed", "conclusion": self.conclusion,
                }
            if route == "actions/runs/" + str(RUN_ID) + "/jobs?per_page=100":
                return {"total_count": 1, "jobs": [{
                    "name": "monitor", "run_id": RUN_ID, "run_attempt": 1,
                    "head_sha": SOURCE, "status": "completed",
                    "conclusion": self.conclusion, "steps": [{
                        "name": self.failed_step, "conclusion": self.conclusion,
                    }],
                }]}
            if route == "contents/brain/demo.py?ref=" + SOURCE:
                return {
                    "type": "file", "encoding": "base64", "sha": "b"*40,
                    "size": len(ORIGINAL),
                    "content": base64.b64encode(ORIGINAL).decode(),
                }
            raise AssertionError(route)
        if self.fail_write:
            raise f.FactoryError("FAKE_WRITE_FAILED")
        if method == "POST" and route == "git/refs":
            return {"ref": payload["ref"], "object": {"sha": SOURCE}}
        if method == "PUT" and route == "contents/brain/demo.py":
            return {"commit": {"sha": "c"*40}, "content": {"sha": "d"*40}}
        if method == "POST" and route == "pulls":
            return {
                "number": self.pr_number, "state": "open", "draft": True,
                "head": {"ref": payload["head"]},
                "base": {"ref": "main"},
            }
        raise AssertionError((method, route))

class FactoryTests(unittest.TestCase):
    def test_real_source_patch_is_deterministic_and_never_claims_release(self):
        first = f.prepare(manifest(), {"brain/demo.py": ORIGINAL})
        second = f.prepare(manifest(), {"brain/demo.py": ORIGINAL})
        self.assertEqual(first["operation_id"], second["operation_id"])
        self.assertEqual(first["changes"][0]["updated_bytes"],
                         b"def compute():\n    return 2\n")
        self.assertTrue(first["branch"].startswith("auto-repair/v10-"))
        self.assertFalse(first["production_accepted"])
        self.assertIn("NOT_TESTED", first["status"])

    def test_bad_source_anchor_wrong_repository_and_sensitive_paths_fail(self):
        bad_cases = []
        wrong_repo = manifest()
        wrong_repo["repository"] = "P00NSMASHER/abvmschoolstarworld"
        bad_cases.append(wrong_repo)
        for path in (".github/workflows/run.yml", "brain/../secrets.py",
                     "brain/private/token.py", "docs/../../README.md",
                     "/tmp/evil.py", "brain/.git/config", "brain/malware.sh"):
            row = manifest()
            row["changes"][0]["path"] = path
            bad_cases.append(row)
        for row in bad_cases:
            with self.subTest(row=row), self.assertRaises(f.FactoryError):
                f.validate_request(row)
        with self.assertRaisesRegex(f.FactoryError, "FACTORY_SOURCE_HASH_MISMATCH"):
            f.prepare(manifest(), {"brain/demo.py": b"stale"})
        source = ORIGINAL + b"    return 1\n"
        row = manifest()
        row["changes"][0]["expected_sha256"] = f.sha256(source)
        with self.assertRaisesRegex(f.FactoryError, "FACTORY_ANCHOR_NOT_UNIQUE"):
            f.prepare(row, {"brain/demo.py": source})

    def test_duplicate_path_boolean_run_and_extra_fields_are_refused(self):
        cases = []
        row = manifest()
        row["failure_run_id"] = True
        cases.append(row)
        row = manifest()
        row["changes"] = [row["changes"][0], row["changes"][0].copy()]
        cases.append(row)
        row = manifest()
        row["unreviewed_writer_scope"] = "all"
        cases.append(row)
        for item in cases:
            with self.subTest(item=item), self.assertRaises(f.FactoryError):
                f.validate_request(item)

    def test_failed_original_core_and_first_attempt_are_provider_verified(self):
        api = FakeProvider()
        out = f.verify_original_failed_core(api, manifest())
        self.assertEqual(out["run_id"], RUN_ID)
        self.assertIn("preflight", out["failed_step_names"][0].lower())
        self.assertFalse(out["production_accepted"])
        api.main = "f" * 40
        with self.assertRaisesRegex(f.FactoryError, "FACTORY_MAIN_MOVED"):
            f.verify_original_failed_core(api, manifest())
        api.main = SOURCE
        api.conclusion = "success"
        with self.assertRaisesRegex(f.FactoryError, "FACTORY_NO_ORIGINAL_FAILED_CORE"):
            f.verify_original_failed_core(api, manifest())

    def test_exact_source_provider_contents_verified_independent_of_manifest(self):
        api = FakeProvider()
        data = f.verify_original_sources(api, manifest())
        self.assertEqual(data["brain/demo.py"]["raw"], ORIGINAL)
        modified = manifest()
        modified["changes"][0]["expected_sha256"] = "0" * 64
        with self.assertRaisesRegex(f.FactoryError, "FACTORY_SOURCE_HASH_MISMATCH"):
            f.prepare(modified, {"brain/demo.py": data["brain/demo.py"]["raw"]})

    def test_non_networked_nonprivileged_actual_test_command(self):
        candidate = f.prepare(manifest(), {"brain/demo.py": ORIGINAL})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "brain").mkdir()
            (path / "tests").mkdir()
            (path / "brain/demo.py").write_bytes(ORIGINAL)
            (path / "tests/test_demo.py").write_text(
                "import unittest\nclass Example(unittest.TestCase):\n"
                "    def test_true(self): self.assertTrue(True)\n")
            seen = []
            def runner(command, **options):
                self.assertEqual(command[:2], ["docker", "run"])
                self.assertIn("--network", command)
                self.assertEqual(command[command.index("--network") + 1], "none")
                self.assertIn("--cap-drop=ALL", command)
                self.assertIn("--security-opt=no-new-privileges", command)
                bind = command[command.index("--mount") + 1]
                source = Path(bind.split("src=", 1)[1].split(",dst=", 1)[0])
                self.assertIn(b"return 2", (source / "brain/demo.py").read_bytes())
                self.assertEqual((path / "brain/demo.py").read_bytes(), ORIGINAL)
                seen.append(command)
                return types.SimpleNamespace(returncode=0, stdout="PASS", stderr="")
            result = f.run_isolated_tests(path, candidate, runner=runner)
            self.assertEqual(result["status"],
                             "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI")
            self.assertEqual(len(seen), 1)
            self.assertEqual(result["provider_writes"], 0)

    def test_failed_isolated_test_does_not_become_a_green_receipt(self):
        candidate = f.prepare(manifest(), {"brain/demo.py": ORIGINAL})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "brain").mkdir()
            (path / "tests").mkdir()
            (path / "brain/demo.py").write_bytes(ORIGINAL)
            def runner(*args, **kwargs):
                return types.SimpleNamespace(returncode=1, stdout="RED", stderr="")
            with self.assertRaisesRegex(f.FactoryError, "FACTORY_ISOLATED_TEST_FAILED"):
                f.run_isolated_tests(path, candidate, runner=runner)

    def test_real_draft_provider_writes_only_after_original_proof_and_test(self):
        api = FakeProvider()
        spec = manifest()
        candidate = f.prepare(spec, {"brain/demo.py": ORIGINAL})
        tested = {"operation_id": candidate["operation_id"],
                  "status": "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI"}
        with tempfile.TemporaryDirectory() as tmp:
            intent = Path(tmp) / "intent.json"
            result = f.create_draft(api, spec, candidate, tested,
                                    intent_path=intent)
            self.assertEqual(result["status"], "DRAFT_PR_CREATED_NOT_APPROVED")
            self.assertFalse(result["deployed"])
            self.assertFalse(result["independent_ci_verified"])
            self.assertEqual(result["pr_number"], 900)
            writes = [(method, route, payload) for method,route,payload
                      in api.calls if method != "GET"]
            self.assertEqual([method + ":" + route for method,route,_ in writes],
                             ["POST:git/refs", "PUT:contents/brain/demo.py", "POST:pulls"])
            self.assertTrue(writes[-1][2]["draft"])
            self.assertTrue(intent.exists())
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_PRIOR_INTENT_NEEDS_RECONCILIATION"):
                f.create_draft(api, spec, candidate, tested,
                               intent_path=intent)

    def test_denied_source_or_test_cannot_write_or_create_intent(self):
        api = FakeProvider()
        spec = manifest()
        candidate = f.prepare(spec, {"brain/demo.py": ORIGINAL})
        with tempfile.TemporaryDirectory() as tmp:
            intent = Path(tmp) / "intent.json"
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_TEST_RECEIPT_MISMATCH"):
                f.create_draft(api, spec, candidate,
                               {"operation_id": candidate["operation_id"],
                                "status": "FAILURE"}, intent_path=intent)
            self.assertFalse(intent.exists())
            api.main = "f" * 40
            with self.assertRaisesRegex(f.FactoryError, "FACTORY_MAIN_MOVED"):
                f.create_draft(api, spec, candidate, {
                    "operation_id": candidate["operation_id"],
                    "status": "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI",
                }, intent_path=intent)
            self.assertFalse(intent.exists())
            self.assertFalse(any(method != "GET" for method,_,_ in api.calls))

    def test_unknown_write_preserves_intent_and_forbids_auto_retry(self):
        api = FakeProvider()
        api.fail_write = True
        spec = manifest()
        candidate = f.prepare(spec, {"brain/demo.py": ORIGINAL})
        with tempfile.TemporaryDirectory() as tmp:
            intent = Path(tmp) / "intent.json"
            tested = {"operation_id": candidate["operation_id"],
                      "status": "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI"}
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_WRITE_UNCERTAIN_NEEDS_READBACK"):
                f.create_draft(api, spec, candidate, tested, intent_path=intent)
            self.assertTrue(intent.exists())
            self.assertEqual(len([x for x in api.calls if x[0] != "GET"]), 1)

    def test_provider_transport_refuses_all_arbitrary_endpoints_and_methods(self):
        transport = f.GitHubTransport("x" * 30)
        for method, route, value in [
            ("GET", "https://evil.example/token", None),
            ("GET", "actions/secrets", None),
            ("POST", "merges", {}),
            ("PUT", "contents/.github/workflows/main.yml", {}),
            ("DELETE", "git/refs/heads/main", None),
        ]:
            with self.subTest(method=method, route=route):
                with self.assertRaises(f.FactoryError):
                    transport.request(method, route, value)

if __name__ == "__main__":
    unittest.main()
