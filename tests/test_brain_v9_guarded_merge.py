"""Network-free hostile-input tests for the guarded native auto-merge controller."""
import base64
import copy
import json
import unittest

from brain.v9 import guarded_merge as gm

BASE = "a" * 40
HEAD = "b" * 40
REVIEW_TIP = "c" * 40
PR = 812
NODE = "PR_" + "f" * 28
ROOT_TREE, DOCS_TREE, GENESIS_TREE = "1" * 40, "2" * 40, "3" * 40
FILE = "docs/genesis/NOTES.md"
RAW = b"# Low-risk review note\nNo code or workflow changes.\n"
BLOB = gm.git_blob_sha(RAW)
ROOT = "repos/" + gm.REPO + "/"


def content(raw):
    return {"type": "file", "encoding": "base64", "size": len(raw),
            "sha": gm.git_blob_sha(raw),
            "content": base64.b64encode(raw).decode("ascii")}


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.mutations = 0
        self.enabled = False
        self.disabled = False
        self.no_acceptance = False
        self.change_head = False
        self.bad_threads = False
        self.provider_fail = False
        self.extra_acceptance_file = False
        self.immediate_merge = False
        self.symlink = False
        self.repo = {"id": gm.REPO_ID, "full_name": gm.REPO, "default_branch": "main",
                     "archived": False, "allow_auto_merge": True}
        self.main = {"protected": True, "commit": {"sha": BASE}}
        self.rules = {"id": gm.RULESET_ID, "enforcement": "active",
            "bypass_actors": [], "conditions": {"ref_name": {
                "include": ["refs/heads/main"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                {"type": "pull_request", "parameters": {
                    "required_review_thread_resolution": True,
                    "required_approving_review_count": 0}},
                {"type": "required_status_checks", "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": k, "integration_id": v}
                        for k, v in gm.REQUIRED_CHECKS.items()]}}]}
        self.record = {"source_sha": BASE, "status": "PASS", "decision": "RELEASED",
            "scope": "SOURCE_SPECIFIC_UNATTENDED_PRODUCTION_CORE_RELIABILITY_ONLY",
            "original_run_evidence": {"completed_span_seconds": 21601,
                "maximum_gap_seconds": 1801, "all_success_attempt_one": True,
                "all_original_core_state_parent_child_links_contiguous": True},
            "terminal_state_replay": {"pending_events": 0, "sqlite_integrity": "PASS",
                "foreign_keys": "PASS", "deterministic_report_reproduction": "PASS"},
            "proof": {"technical_workflow_conclusion": "success"}}
        self.refs = [{"ref": "refs/heads/brain-acceptance-" + BASE[:8] + "-20261019",
                      "object": {"type": "commit", "sha": REVIEW_TIP}}]
        self.commit = {"sha": REVIEW_TIP, "parents": [{"sha": BASE}]}
        self.pr = {"number": PR, "node_id": NODE, "state": "open", "draft": False,
            "merged": False, "mergeable": True, "mergeable_state": "clean",
            "base": {"ref": "main", "sha": BASE,
                     "repo": {"full_name": gm.REPO}},
            "head": {"ref": "docs/source", "sha": HEAD,
                     "repo": {"full_name": gm.REPO}},
            "user": {"login": "P00NSMASHER"},
            "labels": [{"name": gm.LABEL}], "changed_files": 1,
            "additions": 2, "deletions": 0, "auto_merge": None}
        self.checks = {"total_count": 2, "check_runs": [
            {"name": k, "status": "completed", "conclusion": "success",
             "app": {"id": v}, "head_sha": HEAD}
            for k, v in gm.REQUIRED_CHECKS.items()]}
        self.files = [{"filename": FILE, "status": "modified", "sha": BLOB}]

    def get(self, path):
        self.calls.append(("GET", path))
        if path == "repos/" + gm.REPO:
            r = copy.deepcopy(self.repo)
            if self.disabled:
                r["allow_auto_merge"] = False
            return r
        if path == ROOT + "rulesets/" + str(gm.RULESET_ID):
            return copy.deepcopy(self.rules)
        if path == ROOT + "branches/main":
            return copy.deepcopy(self.main)
        if path == ROOT + "git/matching-refs/heads/brain-acceptance-" + BASE[:8] + "-":
            if self.no_acceptance:
                raise gm.Denied("HTTP_404")
            return copy.deepcopy(self.refs)
        if path == ROOT + "git/commits/" + REVIEW_TIP:
            return copy.deepcopy(self.commit)
        if path == ROOT + "compare/" + BASE + "..." + REVIEW_TIP:
            file = "acceptance/finish-soak-" + BASE[:8] + "-20261019.json"
            changes = [{"filename": file, "status": "added"}]
            if self.extra_acceptance_file:
                changes.append({"filename": ".github/workflows/unsafe.yml", "status": "added"})
            return {"files": changes, "ahead_by": 1, "behind_by": 0,
                    "merge_base_commit": {"sha": BASE}}
        if path == ROOT + "contents/acceptance/finish-soak-" + BASE[:8] + "-20261019.json?ref=" + REVIEW_TIP:
            return content(json.dumps(self.record).encode("utf-8"))
        if path == ROOT + "pulls/" + str(PR):
            p = copy.deepcopy(self.pr)
            if self.enabled:
                if self.immediate_merge:
                    p["state"] = "closed"
                    p["merged"] = True
                    p["merge_commit_sha"] = "e" * 40
                else:
                    p["auto_merge"] = {"merge_method": "squash"}
            if self.change_head and sum(1 for m, q in self.calls if q == path) > 1:
                p["head"]["sha"] = "d" * 40
            return p
        if path == ROOT + "commits/" + HEAD + "/check-runs?per_page=100":
            return copy.deepcopy(self.checks)
        if path == ROOT + "pulls/" + str(PR) + "/files?per_page=100":
            return copy.deepcopy(self.files)
        if path == ROOT + "git/commits/" + HEAD:
            return {"sha": HEAD, "tree": {"sha": ROOT_TREE}}
        if path == ROOT + "git/trees/" + ROOT_TREE:
            return {"sha": ROOT_TREE, "truncated": False, "tree": [
                {"path": "docs", "type": "tree", "mode": "040000", "sha": DOCS_TREE}]}
        if path == ROOT + "git/trees/" + DOCS_TREE:
            return {"sha": DOCS_TREE, "truncated": False, "tree": [
                {"path": "genesis", "type": "tree", "mode": "040000", "sha": GENESIS_TREE}]}
        if path == ROOT + "git/trees/" + GENESIS_TREE:
            return {"sha": GENESIS_TREE, "truncated": False, "tree": [
                {"path": "NOTES.md", "type": "blob",
                 "mode": "120000" if self.symlink else "100644", "sha": BLOB}]}
        if path == ROOT + "contents/" + FILE + "?ref=" + HEAD:
            return content(RAW)
        raise AssertionError("UNREVIEWED_PROVIDER_ROUTE: " + path)

    def graphql(self, query, variables):
        self.calls.append(("GRAPHQL", "read" if query == gm.THREADS_QUERY else "write"))
        if query == gm.THREADS_QUERY:
            return {"data": {"node": {"id": NODE, "reviewThreads": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [{"isResolved": not self.bad_threads}]}}}}
        if query == gm.ENABLE_MUTATION:
            self.mutations += 1
            if self.provider_fail:
                raise RuntimeError("ambiguous timeout")
            self.enabled = True
            return {"data": {"enablePullRequestAutoMerge": {
                "pullRequest": {"id": NODE,
                                "autoMergeRequest": {"enabledAt": "2026-10-19T06:00:00Z"}}}}}
        raise AssertionError("UNREVIEWED_GRAPHQL")


class GuardedAdmissionTests(unittest.TestCase):
    def assert_blocked(self, provider, reason):
        with self.assertRaisesRegex(gm.Denied, reason):
            gm.run(provider, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(provider.mutations, 0, "mutation occurred before failed check")
        self.assertFalse(provider.enabled)

    def test_positive_dry_run_never_enrolls(self):
        f = FakeProvider()
        result = gm.run(f, number=PR, expected_main=BASE)
        self.assertEqual(result["status"], "ADMISSIBLE")
        self.assertEqual(result["base_sha"], BASE)
        self.assertEqual(result["head_sha"], HEAD)
        self.assertEqual(result["provider_writes"], 0)
        self.assertFalse(result["enrolled"])
        self.assertEqual(f.mutations, 0)
        self.assertTrue(all(x[0] == "GET" or x == ("GRAPHQL", "read") for x in f.calls))

    def test_one_protected_native_enrollment_and_readback(self):
        f = FakeProvider()
        result = gm.run(f, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(result["status"], "NATIVE_AUTO_MERGE_ENROLLED")
        self.assertEqual(result["provider_writes"], 1)
        self.assertTrue(result["enrolled"])
        self.assertFalse(result["merged"])
        self.assertEqual(f.mutations, 1)
        self.assertTrue(any(c == ("GRAPHQL", "write") for c in f.calls))

    def test_immediate_platform_merge_must_be_provider_verified(self):
        f = FakeProvider()
        f.immediate_merge = True
        result = gm.run(f, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(result["status"], "NATIVE_AUTO_MERGE_COMPLETED")
        self.assertTrue(result["merged"])
        self.assertEqual(result["merge_commit_sha"], "e" * 40)
        self.assertEqual(f.mutations, 1)

    def test_repository_setting_disabled_means_no_write(self):
        f = FakeProvider()
        f.disabled = True
        result = gm.run(f, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(result["status"], "REPOSITORY_AUTO_MERGE_SETTING_DISABLED")
        self.assertEqual(f.mutations, 0)
        self.assertEqual(len(f.calls), 1)

    def test_unaccepted_source_blocks_every_mutation(self):
        f = FakeProvider()
        f.no_acceptance = True
        self.assert_blocked(f, "SOURCE_ACCEPTANCE_NOT_YET_RECORDED")

    def test_source_or_branch_ambiguity_blocks(self):
        f = FakeProvider()
        f.main["commit"]["sha"] = "e" * 40
        self.assert_blocked(f, "PROTECTED_MAIN_SOURCE_MOVED")
        f = FakeProvider()
        f.refs.append(copy.deepcopy(f.refs[0]))
        self.assert_blocked(f, "ACCEPTANCE_BRANCH_NOT_UNIQUE")
        f = FakeProvider()
        f.extra_acceptance_file = True
        self.assert_blocked(f, "ACCEPTANCE_BRANCH_SCOPE")

    def test_protection_bypass_or_independent_check_mutation_blocks(self):
        f = FakeProvider()
        f.rules["bypass_actors"] = [{"actor_id": 1}]
        self.assert_blocked(f, "PROTECTED_RULESET_MISMATCH")
        f = FakeProvider()
        f.rules["rules"][-1]["parameters"]["strict_required_status_checks_policy"] = False
        self.assert_blocked(f, "INDEPENDENT_CHECK_GATE_MISSING")
        f = FakeProvider()
        f.rules["rules"][-1]["parameters"]["required_status_checks"][1]["integration_id"] = 0
        self.assert_blocked(f, "INDEPENDENT_CHECK_ISSUER_MISSING")

    def test_acceptance_not_authorized_by_old_or_fake_evidence(self):
        f = FakeProvider()
        f.record["source_sha"] = "f" * 40
        self.assert_blocked(f, "ACCEPTANCE_STATUS_OR_SOURCE")
        for key, value in (("completed_span_seconds", 20000), ("maximum_gap_seconds", 6000),
                           ("all_success_attempt_one", False)):
            f = FakeProvider()
            f.record["original_run_evidence"][key] = value
            with self.subTest(key=key):
                self.assert_blocked(f, "ACCEPTANCE_ORIGINAL_EVIDENCE_MISSING")
        f = FakeProvider()
        f.commit["parents"] = [{"sha": "f" * 40}]
        self.assert_blocked(f, "ACCEPTANCE_COMMIT_ANCESTRY")

    def test_wrong_actor_draft_or_missing_label_blocks(self):
        for field, value, reason in (
            ("user", {"login": "untrusted-caller"}, "PR_IDENTITY_OR_MERGEABILITY"),
            ("draft", True, "PR_IDENTITY_OR_MERGEABILITY"),
            ("labels", [], "TRUSTED_LABEL_MISSING"),
            ("mergeable_state", "unknown", "PR_IDENTITY_OR_MERGEABILITY")
        ):
            f = FakeProvider()
            f.pr[field] = value
            with self.subTest(field=field):
                self.assert_blocked(f, reason)

    def test_forged_green_check_issuer_and_incomplete_checks_block(self):
        f = FakeProvider()
        f.checks["check_runs"][0]["app"]["id"] = 0
        self.assert_blocked(f, "INDEPENDENT_HEAD_CHECK_FAILED")
        f = FakeProvider()
        f.checks["check_runs"][1]["head_sha"] = "e" * 40
        self.assert_blocked(f, "INDEPENDENT_HEAD_CHECK_FAILED")
        f = FakeProvider()
        f.checks["total_count"] = 3
        self.assert_blocked(f, "CHECK_CENSUS_INCOMPLETE")

    def test_changed_workflow_symlink_and_oversized_patch_block(self):
        f = FakeProvider()
        f.files[0]["filename"] = ".github/workflows/bypass.yml"
        self.assert_blocked(f, "NOT_LOW_RISK_DOCUMENT")
        f = FakeProvider()
        f.pr["additions"] = 300
        self.assert_blocked(f, "PR_CHANGE_BOUNDS")
        f = FakeProvider()
        f.files[0]["sha"] = "f" * 40
        self.assert_blocked(f, "PR_FILE_NOT_REGULAR_BLOB")
        f = FakeProvider()
        f.symlink = True
        self.assert_blocked(f, "PR_FILE_NOT_REGULAR_BLOB")

    def test_unresolved_threads_or_races_block(self):
        f = FakeProvider()
        f.bad_threads = True
        self.assert_blocked(f, "UNRESOLVED_OR_INCOMPLETE_REVIEW_THREADS")
        f = FakeProvider()
        f.change_head = True
        self.assert_blocked(f, "PR_CHANGED_DURING_ADMISSION")

    def test_provider_write_uncertainty_fails_without_retry(self):
        f = FakeProvider()
        f.provider_fail = True
        with self.assertRaisesRegex(gm.Denied, "AUTO_MERGE_WRITE_UNCERTAIN"):
            gm.run(f, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(f.mutations, 1)
        self.assertFalse(f.enabled)

    def test_already_enrolled_is_idempotent(self):
        f = FakeProvider()
        f.enabled = True
        result = gm.run(f, number=PR, expected_main=BASE, apply=True)
        self.assertEqual(result["status"], "ALREADY_ENROLLED")
        self.assertEqual(f.mutations, 0)

    def test_http_client_no_password_or_arbitrary_repo(self):
        with self.assertRaisesRegex(gm.Denied, "GITHUB_TOKEN_MISSING"):
            gm.GitHub("")
        with self.assertRaisesRegex(gm.Denied, "GITHUB_ROUTE_NOT_ALLOWLISTED"):
            gm.GitHub("a" * 32).get("repos/untrusted/repo/branches/main")

    def test_prohibited_paths_including_traversal(self):
        for path in ("../../docs/genesis/x.md", "docs/genesis/../../x.md",
                     "docs/genesis/x.yaml", "docs/genesis/GUARDED_NATIVE_AUTOMERGE.md",
                     "docs/genesis//note.md", "docs/rebuild/README.md/"):
            with self.subTest(path=path), self.assertRaises(gm.Denied):
                gm.checked_path(path)


if __name__ == "__main__":
    unittest.main()
