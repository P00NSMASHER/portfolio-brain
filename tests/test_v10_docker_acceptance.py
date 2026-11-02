"""Real container smoke for v10, opt-in only on GitHub's isolated CI job.

Normal local unit tests skip Docker; hosted job sets PB_V10_DOCKER_SMOKE=1.
The test executes generated patched source inside a real network-disabled,
read-only, nonroot container and verifies both RED and GREEN assertions.
"""
import os
import subprocess
from pathlib import Path
import tempfile
import unittest

from brain.v10 import engineering_factory as factory

OLD = b"def answer():\n    return 0\n"
NEW = b"def answer():\n    return 1\n"

@unittest.skipUnless(os.getenv("PB_V10_DOCKER_SMOKE") == "1",
                     "real Docker smoke is executed in separate CI job only")
class RealDockerAcceptanceTests(unittest.TestCase):
    def test_actual_source_patch_executes_in_network_disabled_nonroot_docker(self):
        with tempfile.TemporaryDirectory(prefix="v10-docker-smoke-") as temp:
            root=Path(temp)
            (root/"brain").mkdir()
            (root/"tests").mkdir()
            (root/"brain/demo.py").write_bytes(OLD)
            (root/"tests/test_demo.py").write_text(
                "import unittest\n"
                "from brain.demo import answer\n"
                "class ChangedSource(unittest.TestCase):\n"
                "    def test_patch_delivered(self): self.assertEqual(answer(), 1)\n"
            )
            spec=dict(schema_version=1,repository=factory.REPOSITORY,
                      base_sha="a"*40,failure_run_id=123,
                      changes=[dict(path="brain/demo.py",
                                    expected_sha256=factory.sha256(OLD),
                                    old="    return 0\n",new="    return 1\n")])
            patch=factory.prepare(spec,{"brain/demo.py": OLD})
            self.assertEqual(patch["changes"][0]["updated_bytes"], NEW)
            observed = []
            def reveal_synthetic_fixture_failure(command, **kwargs):
                completed = subprocess.run(command, **kwargs)
                observed.append(completed.returncode)
                # The ORIGINAL fixture must fail. Only a failed corrected
                # execution is unexpected and needs diagnostic output.
                if len(observed) == 2 and completed.returncode:
                    self.fail(
                        "ISOLATED_CORRECTED_FIXTURE_EXECUTION_FAILED "
                        + "stdout=" + completed.stdout[-3500:]
                        + " stderr=" + completed.stderr[-3500:])
                return completed
            receipt=factory.run_isolated_tests(
                root,patch,runner=reveal_synthetic_fixture_failure)
            self.assertEqual(observed, [1, 0])
            self.assertEqual(receipt["status"],
                             "ISOLATED_RED_GREEN_TESTS_PASSED_NOT_INDEPENDENT_CI")
            self.assertTrue(receipt["regression_red_verified"])
            self.assertTrue(receipt["corrected_green_verified"])
            self.assertGreaterEqual(receipt["corrected_test_cases"], 1)
            self.assertGreaterEqual(receipt["corrected_test_cases"],
                                    receipt["baseline_test_cases"])
            self.assertEqual(receipt["operation_id"],patch["operation_id"])
            self.assertEqual((root/"brain/demo.py").read_bytes(),OLD)
            self.assertFalse(receipt["production_accepted"])
            self.assertEqual(receipt["provider_writes"],0)


    def test_reviewed_regression_makes_previously_green_source_red_then_green(self):
        # Original repository tests alone are GREEN. A separately reviewed,
        # source-locked regression exposes the real newly tested defect.
        with tempfile.TemporaryDirectory(prefix="v10-approved-regression-") as temp:
            root = Path(temp)
            (root / "brain").mkdir()
            (root / "tests").mkdir()
            (root / "brain/demo.py").write_bytes(OLD)
            (root / "tests/test_original.py").write_text(
                "import unittest\n"
                "class OriginalSuite(unittest.TestCase):\n"
                "    def test_healthy(self): self.assertTrue(True)\n"
            )
            source = (
                "import unittest\n"
                "from brain.demo import answer\n"
                "class ReviewedRegression(unittest.TestCase):\n"
                "    def test_repaired_source(self): self.assertEqual(answer(), 1)\n"
            )
            reviewed = {
                "path": "tests/test_v11_reviewed_demo.py",
                "source": source, "sha256": factory.sha256(source.encode()),
            }
            spec = {
                "schema_version": 1,
                "repository": factory.REPOSITORY,
                "base_sha": "a" * 40,
                "failure_run_id": 123,
                "changes": [{
                    "path": "brain/demo.py",
                    "expected_sha256": factory.sha256(OLD),
                    "old": "    return 0\n",
                    "new": "    return 1\n",
                }],
            }
            candidate = factory.prepare(spec, {"brain/demo.py": OLD})
            observed = []
            def run_real_container(command, **kwargs):
                result = subprocess.run(command, **kwargs)
                observed.append(result.returncode)
                if len(observed) == 2 and result.returncode != 0:
                    self.fail("REVIEWED_REGRESSION_GREEN_FAILED "
                              + result.stdout[-1200:] + result.stderr[-1200:])
                return result
            proof = factory.run_isolated_tests(
                root, candidate, runner=run_real_container,
                reviewed_regression=reviewed)
            self.assertEqual(observed, [1, 0])
            self.assertEqual(proof["baseline_test_cases"], 2)
            self.assertEqual(proof["corrected_test_cases"], 2)
            self.assertEqual(proof["reviewed_regression_sha256"], reviewed["sha256"])
            self.assertFalse((root / reviewed["path"]).exists())
            self.assertEqual((root / "brain/demo.py").read_bytes(), OLD)
            self.assertEqual(proof["provider_writes"], 0)

if __name__ == "__main__":
    unittest.main()
