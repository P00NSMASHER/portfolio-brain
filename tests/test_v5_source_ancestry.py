"""Prove the ancestry check on real Git objects from a bounded source graph."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_v5_deployed_state_compatibility import git, verify_main_ancestry


class SourceAncestryTests(unittest.TestCase):
    def test_shallow_source_history_excludes_state_and_unrelated_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "remote"
            git("init", "--quiet", "--initial-branch=main", str(repo))

            def commit(message):
                git("-C", str(repo), "-c", "user.name=Test",
                    "-c", "user.email=test@example.invalid", "commit",
                    "--quiet", "--allow-empty", "-m", message)
                return git("-C", str(repo), "rev-parse", "HEAD")

            root = commit("source")
            git("-C", str(repo), "checkout", "--quiet", "--orphan", "state")
            unrelated = commit("independent state history")
            git("-C", str(repo), "checkout", "--quiet", "main")
            for i in range(18):
                commit(str(i))
            parent = commit("previous protected source")
            main = commit("new protected source")
            git("-C", str(repo), "config", "uploadpack.allowFilter", "true")

            verify_main_ancestry(parent, main, origin=repo.as_uri())
            for unproven in (root, unrelated):
                with self.subTest(unproven=unproven), self.assertRaises(subprocess.CalledProcessError):
                    verify_main_ancestry(unproven, main, origin=repo.as_uri())
