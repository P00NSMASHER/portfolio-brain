"""Standalone adversarial tests for a one-time App5121826 trust-root bootstrap."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from verification import trust_anchor_bootstrap as boot

MAIN = "a" * 40
HEAD = "b" * 40
ROOT = Path(__file__).resolve().parents[1]


class OriginalProvider:
    def __init__(self):
        self.main = {"protected": True, "commit": {"sha": MAIN}}
        self.pr = {
            "number": 804, "state": "open", "draft": False, "merged": False,
            "user": {"login": "P00NSMASHER"},
            "head": {"sha": HEAD, "ref": boot.BRANCH,
                     "repo": {"full_name": boot.REPO}},
            "base": {"ref": "main", "repo": {"full_name": boot.REPO}},
        }
        self.diff = {
            "merge_base_commit": {"sha": MAIN},
            "behind_by": 0,
            "files": [{"filename": x, "status": "modified"}
                      for x in boot.EXPECTED],
        }
        self.check = {
            "total_count": 1,
            "check_runs": [{
                "id": 41, "name": "validate", "head_sha": HEAD,
                "app": {"id": 15368}, "status": "completed",
                "conclusion": "success",
            }],
        }
        self.content = {x: {"type": "file", "sha": blob, "encoding": "base64"}
                        for x, blob in boot.EXPECTED.items()}
        self.calls = []

    def read(self, path):
        self.calls.append(path)
        if path == "/branches/main":
            return copy.deepcopy(self.main)
        if path == "/pulls/804":
            return copy.deepcopy(self.pr)
        if path == "/compare/" + MAIN + "..." + HEAD:
            return copy.deepcopy(self.diff)
        if path == "/commits/" + HEAD + "/check-runs?per_page=100":
            return copy.deepcopy(self.check)
        prefix = "/contents/"
        if path.startswith(prefix) and path.endswith("?ref=" + HEAD):
            return copy.deepcopy(self.content[path[len(prefix):-len("?ref=" + HEAD)]])
        raise AssertionError("Unexpected read " + path)


class BootstrapAdmissionTests(unittest.TestCase):
    def approve(self, provider, exits=(0, 0, 0)):
        return boot.verify_candidate(provider.read, HEAD, exits=exits)

    def test_exact_candidate_positive_control_never_writes(self):
        p = OriginalProvider()
        result = self.approve(p)
        self.assertEqual(result["head_sha"], HEAD)
        self.assertEqual(result["base_sha"], MAIN)
        self.assertEqual(len(p.calls), 5 + len(boot.EXPECTED))
        self.assertEqual(p.calls[-1], "/branches/main")
        self.assertEqual(set(boot.EXPECTED), {
            "verification/independent_verifier.py",
            "verification/source_admission.py",
            "brain/validate.py",
            ".github/workflows/reliability-day.yml",
            ".github/workflows/portfolio-source-acceptance-producer.yml",
            "tests/test_independent_verifier.py",
            "tests/test_source_merge_admission.py",
            "tests/test_source_observation_activation.py",
            "docs/rebuild/SOURCE_ADMISSION_CUTOVER.md",
        })

    def test_isolated_tests_must_all_pass(self):
        for exits in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            p = OriginalProvider()
            with self.subTest(exits=exits), self.assertRaisesRegex(
                boot.BootstrapDenied, "ISOLATED_TESTS_NOT_PASSING"
            ):
                self.approve(p, exits)
            self.assertEqual(p.calls, [])

    def test_wrong_author_head_draft_closed_or_other_pr_denied(self):
        for edit in (
            lambda p: p.pr["user"].update(login="untrusted"),
            lambda p: p.pr.update(draft=True),
            lambda p: p.pr.update(merged=True),
            lambda p: p.pr.update(state="closed"),
            lambda p: p.pr.update(number=999),
            lambda p: p.pr["head"].update(sha="c" * 40),
            lambda p: p.pr["head"].update(ref="unauthorized"),
            lambda p: p.pr["head"]["repo"].update(full_name="attacker/fork"),
        ):
            p = OriginalProvider()
            edit(p)
            with self.assertRaisesRegex(
                boot.BootstrapDenied, "CANDIDATE_PR_IDENTITY_CHANGED"
            ):
                self.approve(p)

    def test_no_unreviewed_file_may_be_added_or_removed(self):
        p = OriginalProvider()
        p.diff["files"].append({"filename": "README.md", "status": "added"})
        with self.assertRaisesRegex(boot.BootstrapDenied, "UNREVIEWED_CANDIDATE_DIFF"):
            self.approve(p)
        p = OriginalProvider()
        p.diff["files"].pop()
        with self.assertRaisesRegex(boot.BootstrapDenied, "UNREVIEWED_CANDIDATE_DIFF"):
            self.approve(p)

    def test_wrong_any_pinned_blob_denied(self):
        for name in boot.EXPECTED:
            p = OriginalProvider()
            p.content[name]["sha"] = "f" * 40
            with self.subTest(path=name), self.assertRaisesRegex(
                boot.BootstrapDenied, "CANDIDATE_FILE_BLOB_CHANGED"
            ):
                self.approve(p)

    def test_old_main_unprotected_or_lacks_ancestry_denied(self):
        p = OriginalProvider()
        p.main["protected"] = False
        with self.assertRaisesRegex(boot.BootstrapDenied, "MAIN_UNPROTECTED"):
            self.approve(p)
        p = OriginalProvider()
        p.diff["merge_base_commit"]["sha"] = "c" * 40
        with self.assertRaisesRegex(boot.BootstrapDenied, "UNREVIEWED_CANDIDATE_DIFF"):
            self.approve(p)

    def test_foundation_must_come_from_the_issuer_pinned_app(self):
        for app in (123, None):
            p = OriginalProvider()
            p.check["check_runs"][0]["app"]["id"] = app
            with self.subTest(app=app), self.assertRaisesRegex(
                boot.BootstrapDenied, "EXACT_HEAD_FOUNDATION_REQUIRED"
            ):
                self.approve(p)

    def test_incomplete_check_census_denied(self):
        p = OriginalProvider()
        p.check["total_count"] = 2
        with self.assertRaisesRegex(boot.BootstrapDenied, "FOUNDATION_CENSUS_INCOMPLETE"):
            self.approve(p)

    def test_only_independent_app_can_issue_the_bootstrap_check(self):
        head = HEAD
        with patch.object(boot, "_api", return_value={
            "id": 19, "name": boot.BOOTSTRAP_NAME, "head_sha": head,
            "app": {"id": 5121826}, "status": "completed", "conclusion": "success",
        }) as api:
            result = boot.issue_check("separately-issued-token", head, "read-only approved")
        self.assertEqual(result["app_id"], 5121826)
        args = api.call_args
        self.assertEqual(args.args[1], "/check-runs")
        self.assertEqual(args.kwargs["method"], "POST")
        self.assertEqual(args.kwargs["payload"]["head_sha"], HEAD)

        with patch.object(boot, "_api", return_value={
            "id": 20, "name": boot.BOOTSTRAP_NAME, "head_sha": head,
            "app": {"id": 15368}, "status": "completed", "conclusion": "success",
        }):
            with self.assertRaisesRegex(boot.BootstrapDenied, "INDEPENDENT_BOOTSTRAP_CHECK_UNVERIFIED"):
                boot.issue_check("untrusted-token", head, "falsely green")

    def test_api_write_scope_never_includes_merge_ruleset_or_branch(self):
        for path in ("/pulls/804/merge", "/rulesets/24182301", "/git/refs"):
            with self.subTest(path=path), self.assertRaisesRegex(
                boot.BootstrapDenied, "API_WRITE_FORBIDDEN"
            ):
                boot._api("token", path, method="POST", payload={})

    def test_workflow_is_scoped_to_one_branch_and_no_merge_authority(self):
        text = (ROOT / ".github/workflows/portfolio-source-acceptance.yml").read_text()
        self.assertIn("bootstrap-trust-anchor:", text)
        self.assertIn("head_branch == 'audit/source-admission-crosspath-20261030'", text)
        self.assertIn("test \"$(git hash-object verification/trust_anchor_bootstrap.py)\"", text)
        self.assertIn("app-id: \"5121826\"", text)
        self.assertIn("python -m verification.trust_anchor_bootstrap", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("--network none", text)
        self.assertNotIn("merge_pull_request", text)
        self.assertNotIn("gh pr merge", text)
        self.assertNotIn("pull_request_target:", text)
        self.assertNotIn("workflow_dispatch:", text)


if __name__ == "__main__":
    unittest.main()
