"""Black-box, offline simulation of original state-push delivery under HTTP 408."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/brain-cycle.yml"
PARENT = "a" * 40
PUBLISHED = "b" * 40
FOREIGN = "c" * 40


def original_publish_shell():
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index("          if git -C state diff --cached --quiet; then")
    end = source.index(
        '          MAIN_SHA="$(gh api "repos/' + chr(36)
        + '{GITHUB_REPOSITORY}/branches/main"', start)
    return textwrap.dedent(source[start:end])


class UncertainStatePushTests(unittest.TestCase):
    def run_publish(self, *, outcome="uncertain", remote=(PUBLISHED,),
                    no_change=False, commit_success=True, gh_failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            bindir = directory / "bin"
            bindir.mkdir()
            git = bindir / "git"
            git.write_text(
                "#!/usr/bin/env bash\n"
                '[[ "$1" == "-C" && "$2" == "state" ]] || exit 90\n'
                'case "$3" in\n'
                '  diff)\n'
                '    [[ "$MOCK_NO_CHANGE" == "true" ]] && exit 0 || exit 1 ;;\n'
                '  commit)\n'
                '    printf "commit\\n" >> "$MOCK_GIT_CALLS"\n'
                '    [[ "$MOCK_COMMIT_SUCCESS" == "true" ]] && exit 0 || exit 98 ;;\n'
                '  -c)\n'
                '    [[ "$5" == "push" ]] || exit 91\n'
                '    printf "push\\n" >> "$MOCK_GIT_CALLS"\n'
                '    if [[ "$MOCK_PUSH_OUTCOME" == "uncertain" ]]; then\n'
                '      echo "error: RPC failed; HTTP 408" >&2\n'
                '      echo "Everything up-to-date" >&2\n'
                '      exit 1\n'
                '    fi\n'
                '    exit 0 ;;\n'
                '  rev-parse)\n'
                '    [[ "$4" == "HEAD" ]] || exit 92\n'
                '    printf "%s\\n" "$PUBLICATION_SHA" ;;\n'
                '  *) exit 93 ;;\n'
                'esac\n',
                encoding="utf-8",
            )
            git.chmod(0o755)
            gh = bindir / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "from pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "if ('--header' not in args or 'Cache-Control: no-cache' not in args\n"
                "    or not any(x.endswith('/branches/brain-state-v2') for x in args)):\n"
                "    sys.exit(91)\n"
                "with open(os.environ['MOCK_GH_CALLS'], 'a') as out: out.write('read\\n')\n"
                "if os.environ['MOCK_GH_FAILURE'] == 'true': sys.exit(7)\n"
                "path = Path(os.environ['MOCK_RESPONSES'])\n"
                "values = path.read_text().splitlines()\n"
                "if not values: sys.exit(92)\n"
                "path.write_text('\\n'.join(values[1:]) + ('\\n' if len(values) > 1 else ''))\n"
                "print(values[0])\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            pause = bindir / "sleep"
            pause.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$1" >> "$MOCK_PAUSES"\n',
                encoding="utf-8",
            )
            pause.chmod(0o755)
            responses = directory / "responses"
            responses.write_text("\n".join(remote) + "\n", encoding="utf-8")
            git_calls = directory / "git-calls"
            gh_calls = directory / "gh-calls"
            pauses = directory / "pauses"
            env = dict(os.environ)
            env.update(
                PATH=str(bindir) + os.pathsep + env.get("PATH", ""),
                MOCK_GIT_CALLS=str(git_calls),
                MOCK_GH_CALLS=str(gh_calls),
                MOCK_RESPONSES=str(responses),
                MOCK_PAUSES=str(pauses),
                MOCK_PUSH_OUTCOME=outcome,
                MOCK_COMMIT_SUCCESS=str(commit_success).lower(),
                MOCK_GH_FAILURE=str(gh_failure).lower(),
                MOCK_NO_CHANGE=str(no_change).lower(),
                PUBLICATION_SHA=PARENT if no_change else PUBLISHED,
                BRAIN_STATE_PARENT=PARENT,
                GITHUB_REPOSITORY="P00NSMASHER/portfolio-brain",
                GITHUB_RUN_ID="41117144407",
                BRAIN_SOURCE_SHA="d" * 40,
            )
            result = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", original_publish_shell()],
                env=env, text=True, capture_output=True, check=False, timeout=15)
            def rows(file):
                return file.read_text().splitlines() if file.exists() else []
            return result, rows(git_calls), rows(gh_calls), rows(pauses)

    def test_http_408_landed_exact_commit_is_readback_verified(self):
        result, git, gh, waits = self.run_publish(remote=(PUBLISHED,))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("STATE_PUSH_TRANSPORT_UNCERTAIN", result.stdout)
        self.assertEqual(git, ["commit", "push"])
        self.assertEqual(gh, ["read"])
        self.assertEqual(waits, [])

    def test_http_408_parent_still_visible_fails_without_second_push(self):
        result, git, gh, waits = self.run_publish(remote=(PARENT,) * 6)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STATE_DELIVERY_UNVERIFIED", result.stdout)
        self.assertEqual(git, ["commit", "push"])
        self.assertEqual(len(gh), 6)
        self.assertEqual(waits, ["2"] * 5)
        self.assertIn("Everything up-to-date", result.stderr)

    def test_foreign_remote_tip_fails_closed(self):
        result, git, gh, waits = self.run_publish(remote=(FOREIGN, PUBLISHED))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STATE_DELIVERY_CONFLICT", result.stdout)
        self.assertEqual(git, ["commit", "push"])
        self.assertEqual(gh, ["read"])
        self.assertEqual(waits, [])

    def test_successful_push_still_requires_exact_tip(self):
        result, git, gh, waits = self.run_publish(
            outcome="success", remote=(PARENT, PUBLISHED))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(git, ["commit", "push"])
        self.assertEqual(len(gh), 2)
        self.assertEqual(waits, ["2"])

    def test_no_state_changes_make_no_git_write(self):
        result, git, gh, waits = self.run_publish(
            no_change=True, remote=(PARENT,))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("NO_STATE_CHANGE", result.stdout)
        self.assertEqual(git, [])
        self.assertEqual(gh, ["read"])
        self.assertEqual(waits, [])

    def test_remote_provider_error_fails_closed(self):
        result, git, gh, waits = self.run_publish(gh_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(git, ["commit", "push"])
        self.assertEqual(gh, ["read"])
        self.assertEqual(waits, [])

    def test_failed_local_commit_never_pushes(self):
        result, git, gh, waits = self.run_publish(commit_success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(git, ["commit"])
        self.assertEqual(gh, [])
        self.assertEqual(waits, [])


if __name__ == "__main__":
    unittest.main()
