"""Black-box regression checks for the production GitHub state-push readback.

The tests execute the actual shell fragment from brain-cycle.yml, with mock
`gh` and `sleep` commands. No network, secrets, or Git writes are used.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "brain-cycle.yml"
PARENT = "a" * 40
PUBLISHED = "b" * 40
OTHER = "c" * 40


def readback_shell():
    content = WORKFLOW.read_text(encoding="utf-8")
    start = content.index('          REMOTE_SHA=""')
    end = content.index('          MAIN_SHA="$(gh api "repos/${GITHUB_REPOSITORY}/branches/main"', start)
    return textwrap.dedent(content[start:end])


class PostPushVisibilityTests(unittest.TestCase):
    def run_readback(self, responses):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "from pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "if '--header' not in args or 'Cache-Control: no-cache' not in args or "
                "not any(a.endswith('/branches/brain-state-v2') for a in args):\n"
                "    sys.exit(10)\n"
                "p = Path(os.environ['MOCK_RESPONSES'])\n"
                "rows = p.read_text().splitlines()\n"
                "if not rows:\n"
                "    sys.exit(11)\n"
                "p.write_text('\\n'.join(rows[1:]) + ('\\n' if len(rows) > 1 else ''))\n"
                "with open(os.environ['MOCK_CALLS'], 'a') as f:\n"
                "    f.write('gh\\n')\n"
                "print(rows[0])\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            pause = bin_dir / "sleep"
            pause.write_text(
                "#!/bin/sh\nprintf 'sleep:%s\\n' \"$1\" >> \"$MOCK_SLEEPS\"\n",
                encoding="utf-8",
            )
            pause.chmod(0o755)
            response_file = root / "responses.txt"
            response_file.write_text("\n".join(responses) + ("\n" if responses else ""), encoding="utf-8")
            calls_file = root / "calls.txt"
            sleeps_file = root / "sleeps.txt"
            env = dict(os.environ)
            env.update({
                "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
                "MOCK_RESPONSES": str(response_file),
                "MOCK_CALLS": str(calls_file),
                "MOCK_SLEEPS": str(sleeps_file),
                "GITHUB_REPOSITORY": "P00NSMASHER/portfolio-brain",
                "BRAIN_STATE_PARENT": PARENT,
                "PUBLICATION_SHA": PUBLISHED,
            })
            proc = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", readback_shell()],
                env=env, capture_output=True, text=True, timeout=10, check=False,
            )
            calls = calls_file.read_text().splitlines() if calls_file.exists() else []
            sleeps = sleeps_file.read_text().splitlines() if sleeps_file.exists() else []
            return proc, calls, sleeps

    def test_immediate_visible_publication_needs_no_retry(self):
        result, calls, sleeps = self.run_readback([PUBLISHED])
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_old_parent_then_publication_is_bounded_success(self):
        result, calls, sleeps = self.run_readback([PARENT, PARENT, PUBLISHED])
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, ["sleep:2", "sleep:2"])
        self.assertEqual(result.stdout.count("STATE_VISIBILITY_PENDING"), 2)

    def test_six_stale_parent_responses_fail_closed(self):
        result, calls, sleeps = self.run_readback([PARENT] * 6)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 6)
        self.assertEqual(sleeps, ["sleep:2"] * 5)
        self.assertIn("STATE_DELIVERY_UNVERIFIED", result.stdout)

    def test_competing_remote_tip_fails_without_sleep_or_retry(self):
        result, calls, sleeps = self.run_readback([OTHER, PUBLISHED])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])
        self.assertIn("STATE_DELIVERY_CONFLICT", result.stdout)

    def test_empty_provider_head_cannot_be_laundered(self):
        result, calls, sleeps = self.run_readback(["", PUBLISHED])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_provider_error_fails_closed(self):
        result, calls, sleeps = self.run_readback([])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertEqual(sleeps, [])

    def test_original_nonforce_publication_and_main_drift_guards_remain(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("push origin HEAD:refs/heads/brain-state-v2", content)
        self.assertIn('test "$MAIN_SHA" = "$BRAIN_SOURCE_SHA"', content)
        self.assertIn("STATE_CONFLICT: no publication", content)
        self.assertIn("STATE_DELIVERY_UNVERIFIED", content)
        self.assertNotIn("git push --force", content)
