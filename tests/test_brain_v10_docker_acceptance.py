"""Real container smoke for v10, opt-in only on GitHub's isolated CI job.

Normal local unit tests skip Docker; hosted job sets PB_V10_DOCKER_SMOKE=1.
The test executes generated patched source inside a real network-disabled,
read-only, nonroot container and verifies both RED and GREEN assertions.
"""
import os
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
            receipt=factory.run_isolated_tests(root,patch)
            self.assertEqual(receipt["status"],
                             "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI")
            self.assertEqual(receipt["operation_id"],patch["operation_id"])
            self.assertEqual((root/"brain/demo.py").read_bytes(),OLD)
            self.assertFalse(receipt["production_accepted"])
            self.assertEqual(receipt["provider_writes"],0)

if __name__ == "__main__":
    unittest.main()
