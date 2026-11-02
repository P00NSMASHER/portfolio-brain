"""V11 repair completion: original-provider checks, no fake review or bypass."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from brain.v11 import verified_delivery as d
from brain.v9 import guarded_merge as gm

BASE = "a" * 40
HEAD = "b" * 40
OP = "c" * 64
RECEIPT = "d" * 64
RUN = 12345678
BRANCH = "auto-repair/v10-" + OP[:16]


class Fake:
    def __init__(self):
        self.calls = []
        self.main = BASE
        self.check_app = 15368
        self.core_outcome = "failure"
        self.file_path = "brain/v11/example.py"
        self.thread_resolved = True
        self.bypass = []
        self.prs = True
        self.pr = {
            "number": 777, "state": "open", "draft": True, "merged": False,
            "auto_merge": None, "node_id": "PR_some_exact_node_777",
            "changed_files": 1, "user": {"login": "portfolio-brain-v8-runtime[bot]"},
            "body": "BRAIN_V10_OPERATION_ID: " + OP + "\nOriginal run: " + str(RUN) +
                    "\nV10_RED_GREEN_RECEIPT_SHA256: " + RECEIPT,
            "base": {"ref": "main", "sha": BASE, "repo": {"full_name": d.REPO}},
            "head": {"ref": BRANCH, "sha": HEAD, "repo": {"full_name": d.REPO}},
        }

    def get(self, route):
        self.calls.append(("GET", route))
        root = d.ROOT
        if route == "repos/" + d.REPO:
            return {"id": gm.REPO_ID, "full_name": d.REPO,
                    "default_branch": "main", "archived": False,
                    "allow_auto_merge": True}
        if route == root + "rulesets/" + str(gm.RULESET_ID):
            return {"id": gm.RULESET_ID, "enforcement": "active",
                    "bypass_actors": list(self.bypass),
                    "conditions": {"ref_name": {
                        "include": ["refs/heads/main"], "exclude": []}},
                    "rules": [
                        {"type": "deletion"}, {"type": "non_fast_forward"},
                        {"type": "pull_request", "parameters": {
                            "required_review_thread_resolution": True,
                            "required_approving_review_count": 0}},
                        {"type": "required_status_checks", "parameters": {
                            "strict_required_status_checks_policy": True,
                            "required_status_checks": [
                                {"context": "validate", "integration_id": 15368},
                                {"context": "portfolio-phase1-gate",
                                 "integration_id": 5121826}]}}]}
        if route == root + "branches/main":
            return {"protected": True, "commit": {"sha": self.main}}
        if route == root + "pulls?state=open&per_page=100":
            return [{"number": 777, "head": self.pr["head"]}] if self.prs else []
        if route == root + "pulls/777":
            return deepcopy(self.pr)
        if route == root + "actions/runs/" + str(RUN):
            return {"id": RUN, "name": "brain-cycle-v2",
                    "path": ".github/workflows/brain-cycle.yml",
                    "repository": {"full_name": d.REPO},
                    "head_branch": "main", "head_sha": BASE,
                    "run_attempt": 1, "event": "workflow_dispatch",
                    "status": "completed", "conclusion": self.core_outcome}
        if route == root + "actions/runs/" + str(RUN) + "/jobs?per_page=100":
            return {"total_count": 1, "jobs": [{"name": "monitor",
                    "run_id": RUN, "run_attempt": 1, "conclusion": self.core_outcome,
                    "steps": [{"name": "original failed core", "conclusion": "failure"}]}]}
        if route == root + "pulls/777/files?per_page=100":
            return [{"filename": self.file_path, "status": "modified",
                     "sha": "e" * 40}]
        if route == root + "commits/" + HEAD + "/check-runs?per_page=100":
            return {"total_count": 1, "check_runs": [{
                "name": "validate", "app": {"id": self.check_app},
                "head_sha": HEAD, "status": "completed", "conclusion": "success"}]}
        raise AssertionError("unapproved fake route " + route)

    def graphql(self, query, vars):
        self.calls.append(("GRAPHQL", query[:45]))
        if query == gm.SETTINGS_QUERY:
            return {"data": {"repository": {
                "databaseId": gm.REPO_ID, "nameWithOwner": d.REPO,
                "isArchived": False, "autoMergeAllowed": True}}}
        if query == gm.RULESET_QUERY:
            return {"data": {"repository": {
                "databaseId": gm.REPO_ID, "nameWithOwner": d.REPO,
                "isArchived": False,
                "rulesets": {"pageInfo": {"hasNextPage": False},
                             "nodes": [{
                                 "databaseId": gm.RULESET_ID,
                                 "name": "portfolio-main-protection",
                                 "enforcement": "ACTIVE",
                                 "bypassActors": {"totalCount": len(self.bypass),
                                                  "pageInfo": {"hasNextPage": False}}}]}}}}
        if query == gm.THREADS_QUERY:
            return {"data": {"node": {
                "id": self.pr["node_id"],
                "reviewThreads": {"pageInfo": {"hasNextPage": False},
                                  "nodes": [{"isResolved": self.thread_resolved}]}}}}
        raise AssertionError("unapproved fake GraphQL")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.api = Fake()
        self.fileproof = patch.object(gm, "checked_git_tree_files")
        self.checked = self.fileproof.start()
        self.addCleanup(self.fileproof.stop)

    def eligible(self):
        return d.evaluate(self.api, main_sha=BASE, event_head=HEAD)

    def test_original_failure_and_no_timer_enroll_plan_is_read_only(self):
        plan = self.eligible()
        self.assertEqual(plan["status"], "V10_REPAIR_ELIGIBLE_FOR_NATIVE_PROTECTION")
        self.assertEqual(plan["original_failure_run_id"], RUN)
        self.assertEqual(plan["head_sha"], HEAD)
        self.assertEqual(plan["writes"], 0)
        self.assertEqual(plan["independent_merge_gate"],
                         "GITHUB_REQUIRED_APP_5121826")
        self.checked.assert_called_once()
        self.assertFalse(any(k not in {"GET", "GRAPHQL"} for k, _ in self.api.calls))

    def test_unrelated_pr_is_inert_and_does_not_inspect_forged_body(self):
        self.api.prs = False
        self.assertEqual(self.eligible()["status"], "NO_V10_REPAIR_FOR_EVENT")

    def test_deny_fake_head_or_issuer(self):
        self.api.check_app = 9999
        with self.assertRaisesRegex(d.DeliveryDenied, "ISSUER"):
            self.eligible()
        self.api = Fake()
        self.api.pr["base"]["sha"] = "f" * 40
        with self.assertRaisesRegex(d.DeliveryDenied, "SOURCE"):
            self.eligible()

    def test_deny_wrong_original_failure(self):
        for conclusion in ("success", "cancelled"):
            self.api = Fake()
            self.api.core_outcome = conclusion
            with self.assertRaisesRegex(d.DeliveryDenied, "ORIGINAL_FAILURE"):
                self.eligible()

    def test_deny_untrusted_bot_and_unbound_receipt(self):
        self.api.pr["user"]["login"] = "P00NSMASHER"
        with self.assertRaisesRegex(d.DeliveryDenied, "UNAUTHORIZED"):
            self.eligible()
        self.api = Fake()
        self.api.pr["body"] = "BRAIN_V10_OPERATION_ID: " + OP
        with self.assertRaisesRegex(d.DeliveryDenied, "PROOF"):
            self.eligible()

    def test_deny_unsafe_file_and_duplicate_workflow_change(self):
        for file in (".github/workflows/foundation-ci.yml",
                     "brain/../private/secrets.py", "tests/test_only.py"):
            self.api = Fake()
            self.api.file_path = file
            with self.assertRaisesRegex(d.DeliveryDenied, "REPAIR_"):
                self.eligible()

    def test_deny_bypass_threads_and_base_drift(self):
        self.api.bypass = [{"actor_id": 1}]
        with self.assertRaises(gm.Denied):
            self.eligible()
        self.api = Fake()
        self.api.thread_resolved = False
        with self.assertRaisesRegex(d.DeliveryDenied, "UNRESOLVED"):
            self.eligible()
        self.api = Fake()
        self.api.main = "f" * 40
        with self.assertRaisesRegex(d.DeliveryDenied, "MAIN_DRIFT"):
            self.eligible()

    def test_no_graphql_mutation_until_read_checks_pass(self):
        with patch.object(d, "_gh", side_effect=AssertionError("write")):
            self.api.check_app = 999
            with self.assertRaises(d.DeliveryDenied):
                self.eligible()


if __name__ == "__main__":
    unittest.main()
