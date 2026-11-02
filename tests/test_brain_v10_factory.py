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

def trusted_synthetic_red_green(operation_id):
    return dict(operation_id=operation_id,
                status="ISOLATED_RED_GREEN_TESTS_PASSED_NOT_INDEPENDENT_CI",
                regression_red_verified=True, corrected_green_verified=True,
                baseline_test_cases=1, corrected_test_cases=1,
                baseline_output_sha256="a"*64, output_sha256="b"*64)

class FakeProvider:
    def __init__(self):
        self.calls = []
        self.main = SOURCE
        self.conclusion = "failure"
        self.event = "workflow_dispatch"
        self.origin_step = True
        self.origin_step_conclusion = "success"
        self.failed_step = "Exact-SHA deterministic preflight"
        self.fail_write = False
        self.pr_number = 900
        self.final_sha = "c" * 40
        self.final_content = None
        self.branch = None
        self.pr_body = None
        self.pr_base_sha = SOURCE
        self.main_drift_after_pr = False
        self.token_scope = [f.REPOSITORY]
    def request(self, method, route, payload=None):
        self.calls.append((method, route, payload))
        if method == "GET":
            if route == "installation/repositories?per_page=100":
                return {"total_count": len(self.token_scope),
                        "repositories": [{"full_name": name}
                                         for name in self.token_scope]}
            if route == "branches/main":
                return {"commit": {"sha": self.main}}
            if route.startswith("branches/auto-repair/v10-"):
                return {"commit": {"sha": self.final_sha}}
            if route == "actions/runs/" + str(RUN_ID):
                return {
                    "id": RUN_ID, "name": "brain-cycle-v2",
                    "path": ".github/workflows/brain-cycle.yml",
                    "repository": {"full_name": f.REPOSITORY},
                    "head_branch": "main", "head_sha": SOURCE,
                    "run_attempt": 1, "event": self.event,
                    "status": "completed", "conclusion": self.conclusion,
                }
            if route == "actions/runs/" + str(RUN_ID) + "/jobs?per_page=100":
                return {"total_count": 1, "jobs": [{
                    "name": "monitor", "run_id": RUN_ID, "run_attempt": 1,
                    "head_sha": SOURCE, "status": "completed",
                    "conclusion": self.conclusion, "steps": (
                        [{"name": "Verify independently signed Cloudflare Cron provenance",
                          "conclusion": self.origin_step_conclusion}]
                        if self.origin_step else []) + [{
                        "name": self.failed_step, "conclusion": self.conclusion,
                    }],
                }]}
            if route.startswith("contents/brain/demo.py?ref="):
                raw = (ORIGINAL if route.endswith(SOURCE)
                       else self.final_content)
                if raw is None:
                    raise AssertionError("candidate content unavailable")
                return {
                    "type": "file", "encoding": "base64", "sha": "b"*40,
                    "size": len(raw),
                    "content": base64.b64encode(raw).decode(),
                }
            if route == "pulls/" + str(self.pr_number):
                return {
                    "number": self.pr_number, "state": "open",
                    "draft": True, "merged": False, "body": self.pr_body,
                    "head": {"ref": self.branch, "sha": self.final_sha,
                             "repo": {"full_name": f.REPOSITORY}},
                    "base": {"ref": "main", "sha": self.pr_base_sha,
                             "repo": {"full_name": f.REPOSITORY}},
                }
            raise AssertionError(route)
        if self.fail_write:
            raise f.FactoryError("FAKE_WRITE_FAILED")
        if method == "POST" and route == "git/refs":
            self.branch = payload["ref"].replace("refs/heads/", "", 1)
            return {"ref": payload["ref"], "object": {"sha": SOURCE}}
        if method == "PUT" and route == "contents/brain/demo.py":
            self.final_content = base64.b64decode(payload["content"])
            return {"commit": {"sha": self.final_sha}, "content": {"sha": "d"*40}}
        if method == "POST" and route == "pulls":
            self.pr_body = payload["body"]
            if self.main_drift_after_pr:
                self.main = "f" * 40
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

    def test_manual_failed_dispatch_without_authenticated_origin_is_denied(self):
        api = FakeProvider()
        api.origin_step = False
        with self.assertRaisesRegex(f.FactoryError,
                                    "FACTORY_ORIGINAL_AUTOMATIC_ORIGIN_UNVERIFIED"):
            f.verify_original_failed_core(api, manifest())
        api.origin_step = True
        api.origin_step_conclusion = "failure"
        with self.assertRaisesRegex(f.FactoryError,
                                    "FACTORY_ORIGINAL_AUTOMATIC_ORIGIN_UNVERIFIED"):
            f.verify_original_failed_core(api, manifest())
        api.event = "schedule"
        api.origin_step = False
        self.assertEqual(f.verify_original_failed_core(api, manifest())["run_id"], RUN_ID)

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
                self.assertIn("--read-only", command)
                self.assertEqual(command[command.index("--user") + 1], "65534:65534")
                self.assertIn("/tmp:rw,nosuid,nodev,size=64m,mode=1777", command)
                self.assertIn("/work:rw,nosuid,nodev,size=512m,mode=1777", command)
                bind = command[command.index("--mount") + 1]
                source = Path(bind.split("src=", 1)[1].split(",dst=", 1)[0])
                self.assertTrue(source.stat().st_mode & 0o005 == 0o005)
                staged = (source / "brain/demo.py").read_bytes()
                self.assertEqual((path / "brain/demo.py").read_bytes(), ORIGINAL)
                seen.append(command)
                if len(seen) == 1:
                    self.assertEqual(staged, ORIGINAL)
                    return types.SimpleNamespace(returncode=1, stdout="",
                        stderr="V10_TEST_COUNT=1\nRan 1 test in 0.01s\nFAILED (failures=1)\n")
                self.assertIn(b"return 2", staged)
                return types.SimpleNamespace(returncode=0, stdout="",
                    stderr="V10_TEST_COUNT=1\nRan 1 test in 0.01s\nOK\n")
            result = f.run_isolated_tests(path, candidate, runner=runner)
            self.assertEqual(result["status"],
                             "ISOLATED_RED_GREEN_TESTS_PASSED_NOT_INDEPENDENT_CI")
            self.assertEqual(len(seen), 2)
            self.assertTrue(result["regression_red_verified"])
            self.assertTrue(result["corrected_green_verified"])
            self.assertEqual(result["provider_writes"], 0)


    def test_reviewed_regression_is_only_in_offline_disposable_checkout(self):
        candidate = f.prepare(manifest(), {"brain/demo.py": ORIGINAL})
        source = (
            "import unittest\n"
            "from brain.demo import compute\n"
            "class ReviewedFixTest(unittest.TestCase):\n"
            "    def test_source_value(self): self.assertEqual(compute(), 2)\n"
        )
        reviewed = {
            "path": "tests/test_v11_reviewed_demo.py",
            "source": source, "sha256": f.sha256(source.encode("utf-8")),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "brain").mkdir()
            (root / "tests").mkdir()
            (root / "brain/demo.py").write_bytes(ORIGINAL)
            original_test = root / "tests/test_original.py"
            original_test.write_text(
                "import unittest\n"
                "class Existing(unittest.TestCase):\n"
                "    def test_green(self): self.assertTrue(True)\n"
            )
            runs = []
            def runner(command, **options):
                self.assertEqual(command[command.index("--network") + 1], "none")
                self.assertIn("--read-only", command)
                self.assertIn("--cap-drop=ALL", command)
                self.assertEqual(command[command.index("--user") + 1], "65534:65534")
                bind = command[command.index("--mount") + 1]
                src = Path(bind.split("src=", 1)[1].split(",dst=", 1)[0])
                self.assertEqual(
                    (src / reviewed["path"]).read_text(encoding="utf-8"), source)
                self.assertEqual(original_test.read_text().count("test_green"), 1)
                self.assertFalse((root / reviewed["path"]).exists())
                runs.append((src / "brain/demo.py").read_bytes())
                if len(runs) == 1:
                    self.assertEqual(runs[0], ORIGINAL)
                    return types.SimpleNamespace(
                        returncode=1, stdout="",
                        stderr="V10_REVIEWED_COUNT=1\nV10_REVIEWED_RESULT=FAIL\n"
                               "V10_TEST_COUNT=2\nRan 2 tests in 0.01s\n"
                               "FAILED (failures=1)\n")
                self.assertIn(b"return 2", runs[1])
                return types.SimpleNamespace(
                    returncode=0, stdout="",
                    stderr="V10_REVIEWED_COUNT=1\nV10_REVIEWED_RESULT=PASS\n"
                           "V10_TEST_COUNT=2\nRan 2 tests in 0.01s\nOK\n")
            output = f.run_isolated_tests(
                root, candidate, runner=runner, reviewed_regression=reviewed)
            self.assertEqual(output["reviewed_regression_sha256"], reviewed["sha256"])
            self.assertEqual(output["reviewed_regression_path"], reviewed["path"])
            self.assertEqual(output["baseline_test_cases"], 2)
            self.assertEqual(output["corrected_test_cases"], 2)
            self.assertTrue(output["regression_red_verified"])
            self.assertTrue(output["corrected_green_verified"])
            self.assertFalse((root / reviewed["path"]).exists())
            self.assertEqual(len(runs), 2)

    def test_reviewed_regression_cannot_overwrite_original_test(self):
        candidate = f.prepare(manifest(), {"brain/demo.py": ORIGINAL})
        source = (
            "import unittest\n"
            "class Unsafe(unittest.TestCase):\n"
            "    def test_noop(self): self.assertTrue(True)\n"
        )
        doc = {"path": "tests/test_v11_reviewed_guard.py",
               "source": source, "sha256": f.sha256(source.encode())}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "brain").mkdir()
            (root / "tests").mkdir()
            (root / "brain/demo.py").write_bytes(ORIGINAL)
            (root / doc["path"]).write_text(source)
            with patch.object(f.subprocess, "run", side_effect=AssertionError(
                    "unreviewed Docker execution")):
                with self.assertRaisesRegex(f.FactoryError,
                                            "REVIEWED_TEST_OVERWRITE"):
                    f.run_isolated_tests(root, candidate, reviewed_regression=doc)

    def test_reviewed_regression_requires_source_digest_and_safe_path(self):
        source = ("import unittest\nclass Guard(unittest.TestCase):\n"
                  "    def test_one(self): self.assertTrue(True)\n")
        good = {"path": "tests/test_v11_reviewed_guard.py",
                "source": source, "sha256": f.sha256(source.encode())}
        self.assertEqual(f.validate_reviewed_regression(good), good)
        for variant in (
            {**good, "sha256": "0" * 64},
            {**good, "path": "../tests/test.py"},
            {**good, "path": "tests/test_brain_v11_delivery.py"},
            {**good, "source": "import unittest\n"},
        ):
            with self.assertRaisesRegex(f.FactoryError, "REVIEWED_TEST"):
                f.validate_reviewed_regression(variant)


    def test_unrelated_failing_suite_never_substitutes_for_reviewed_red(self):
        candidate = f.prepare(manifest(), {"brain/demo.py": ORIGINAL})
        source = ("import unittest\nclass Reviewed(unittest.TestCase):\n"
                  "    def test_target(self): self.assertTrue(True)\n")
        doc = {"path": "tests/test_v11_reviewed_redguard.py",
               "source": source, "sha256": f.sha256(source.encode())}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "brain").mkdir()
            (root / "tests").mkdir()
            (root / "brain/demo.py").write_bytes(ORIGINAL)
            (root / "tests/test_existing.py").write_text(
                "import unittest\nclass AlreadyBroken(unittest.TestCase):\n"
                "    def test_bad(self): self.assertFalse(True)\n"
            )
            calls = []
            def fake(command, **_):
                calls.append(command)
                if len(calls) == 1:
                    return types.SimpleNamespace(returncode=1, stdout="",
                        stderr="V10_REVIEWED_COUNT=1\nV10_REVIEWED_RESULT=PASS\n"
                               "V10_TEST_COUNT=2\nRan 2 tests in 0.01s\n"
                               "FAILED (failures=1)\n")
                return types.SimpleNamespace(returncode=0, stdout="",
                    stderr="V10_REVIEWED_COUNT=1\nV10_REVIEWED_RESULT=PASS\n"
                           "V10_TEST_COUNT=2\nRan 2 tests in 0.01s\nOK\n")
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_REVIEWED_TEST_NOT_RED_GREEN"):
                f.run_isolated_tests(root, candidate, runner=fake,
                                     reviewed_regression=doc)

    def test_failed_isolated_test_does_not_become_a_green_receipt(self):
        candidate = f.prepare(manifest(), {"brain/demo.py": ORIGINAL})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "brain").mkdir()
            (path / "tests").mkdir()
            (path / "brain/demo.py").write_bytes(ORIGINAL)
            def runner(*args, **kwargs):
                return types.SimpleNamespace(returncode=1, stdout="",
                    stderr="V10_TEST_COUNT=1\nRan 1 test in 0.01s\nFAILED (failures=1)\n")
            with self.assertRaisesRegex(f.FactoryError, "FACTORY_ISOLATED_TEST_FAILED"):
                f.run_isolated_tests(path, candidate, runner=runner)

    def test_real_draft_provider_writes_only_after_original_proof_and_test(self):
        api = FakeProvider()
        spec = manifest()
        candidate = f.prepare(spec, {"brain/demo.py": ORIGINAL})
        tested = trusted_synthetic_red_green(candidate["operation_id"])
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
            readbacks = [route for method,route,_ in api.calls if method=="GET"]
            self.assertIn("branches/" + candidate["branch"], readbacks)
            self.assertIn("contents/brain/demo.py?ref=" + api.final_sha, readbacks)
            self.assertIn("pulls/900", readbacks)
            self.assertTrue(intent.exists())
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_PRIOR_INTENT_NEEDS_RECONCILIATION"):
                f.create_draft(api, spec, candidate, tested,
                               intent_path=intent)

    def test_post_creation_draft_cannot_hide_old_base_or_main_source_drift(self):
        spec = manifest()
        candidate = f.prepare(spec, {"brain/demo.py": ORIGINAL})
        tested = trusted_synthetic_red_green(candidate["operation_id"])
        for mode, code in (
            ("wrong_base_sha", "FACTORY_DRAFT_BASE_SOURCE_DRIFT"),
            ("main_moved_after_post", "FACTORY_MAIN_MOVED_AFTER_DRAFT"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                api = FakeProvider()
                if mode == "wrong_base_sha":
                    api.pr_base_sha = "f" * 40
                else:
                    api.main_drift_after_pr = True
                intent = Path(tmp) / "intent.json"
                with self.assertRaisesRegex(f.FactoryError, code):
                    f.create_draft(api, spec, candidate, tested,
                                   intent_path=intent)
                # The PR can already exist: preserve intent, never auto-retry.
                self.assertTrue(intent.exists())
                self.assertEqual(
                    [(method, route) for method, route, _ in api.calls
                     if method != "GET"],
                    [("POST", "git/refs"),
                     ("PUT", "contents/brain/demo.py"),
                     ("POST", "pulls")],
                )

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
                f.create_draft(api, spec, candidate,
                               trusted_synthetic_red_green(candidate["operation_id"]),
                               intent_path=intent)
            self.assertFalse(intent.exists())
            self.assertFalse(any(method != "GET" for method,_,_ in api.calls))

    def test_other_repositories_in_token_scope_block_before_any_write(self):
        api = FakeProvider()
        api.token_scope.append("P00NSMASHER/capturebrief")
        spec = manifest()
        candidate = f.prepare(spec, {"brain/demo.py": ORIGINAL})
        tested = trusted_synthetic_red_green(candidate["operation_id"])
        with tempfile.TemporaryDirectory() as tmp:
            intent = Path(tmp) / "intent.json"
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_TOKEN_SCOPE_NOT_SINGLE_REPOSITORY"):
                f.create_draft(api, spec, candidate, tested, intent_path=intent)
            self.assertFalse(intent.exists())
            self.assertFalse(any(method != "GET" for method,_,_ in api.calls))

    def test_mutated_candidate_bytes_do_not_inherit_original_test_receipt(self):
        api = FakeProvider()
        spec = manifest()
        candidate = f.prepare(spec, {"brain/demo.py": ORIGINAL})
        candidate["changes"][0]["updated_bytes"] = b"tampered after testing"
        tested = trusted_synthetic_red_green(candidate["operation_id"])
        with tempfile.TemporaryDirectory() as tmp:
            intent = Path(tmp) / "intent.json"
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_SOURCE_MOVED_BEFORE_WRITE"):
                f.create_draft(api, spec, candidate, tested, intent_path=intent)
            self.assertFalse(intent.exists())
            self.assertFalse(any(method != "GET" for method,_,_ in api.calls))

    def test_unknown_write_preserves_intent_and_forbids_auto_retry(self):
        api = FakeProvider()
        api.fail_write = True
        spec = manifest()
        candidate = f.prepare(spec, {"brain/demo.py": ORIGINAL})
        with tempfile.TemporaryDirectory() as tmp:
            intent = Path(tmp) / "intent.json"
            tested = trusted_synthetic_red_green(candidate["operation_id"])
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
