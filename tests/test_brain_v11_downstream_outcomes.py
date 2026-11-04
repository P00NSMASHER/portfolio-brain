"""Adversarial proof that green CI alone cannot complete a repair."""
import base64
import copy
import hashlib
import json
import unittest

from brain.v11 import downstream_outcomes as o

REPO = "P00NSMASHER/portfolio-brain"
BASE = "a" * 40
HEAD = "b" * 40
MERGE = "c" * 40
BEHAVIOR = b'{"actual_customer_path":"verified","result":"fixed"}'
BUILD = json.dumps({"source_sha": MERGE}).encode()


def blob(raw):
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw
    ).hexdigest()


class Provider:
    def __init__(self):
        self.calls = []
        self.fail_rule = False
        self.wrong_head = False
        self.bad_issuer = False
        self.failed_check = False
        self.missing_contract = False
        self.late_contract = False
        self.wrong_merge_parent = False
        self.main_moved = False
        self.no_deployment = False
        self.deployment_failed = False
        self.wrong_deployment_sha = False
        self.contract = {
            "schema_version": 1, "repository": REPO, "pr_number": 900,
            "environment": "github-pages",
            "build_url": "https://p00nsmasher.github.io/portfolio-brain/build-info.json",
            "behavior_url": "https://p00nsmasher.github.io/portfolio-brain/functional-proof.json",
            "expected_behavior_sha256": hashlib.sha256(BEHAVIOR).hexdigest(),
        }

    def get(self, repo, route):
        self.calls.append((repo, route))
        assert repo == REPO
        if route == "rulesets/24182301":
            return {
                "enforcement": "evaluate" if self.fail_rule else "active",
                "bypass_actors": [],
                "rules": [{"type": "required_status_checks",
                           "parameters": {
                               "strict_required_status_checks_policy": True,
                               "required_status_checks": [
                                   {"context": "validate", "integration_id": 15368},
                                   {"context": "portfolio-phase1-gate",
                                    "integration_id": 5121826}]}}],
            }
        if route == "pulls/900":
            return {
                "number": 900, "state": "closed", "merged": True,
                "head": {"sha": "d" * 40 if self.wrong_head else HEAD,
                         "repo": {"full_name": REPO}},
                "base": {"ref": "main", "sha": "d" * 40,
                         "repo": {"full_name": REPO}},
                "merge_commit_sha": MERGE,
            }
        if route == "git/commits/" + MERGE:
            return {"parents": [
                {"sha": "f" * 40 if self.wrong_merge_parent else BASE},
                {"sha": HEAD}
            ]}
        if route.startswith("contents/repair/downstream-outcomes/900.json?ref="):
            if self.missing_contract or not route.endswith(BASE):
                return {"type": "missing"}
            raw = json.dumps(self.contract).encode("utf-8")
            return {"type": "file", "encoding": "base64", "size": len(raw),
                    "sha": blob(raw),
                    "content": base64.b64encode(raw).decode()}
        if route == "commits/" + HEAD + "/check-runs?per_page=100":
            return {"total_count": 2, "check_runs": [
                {"name": "validate", "head_sha": HEAD,
                 "app": {"id": 15368}, "status": "completed",
                 "conclusion": "failure" if self.failed_check else "success"},
                {"name": "portfolio-phase1-gate", "head_sha": HEAD,
                 "app": {"id": 9 if self.bad_issuer else 5121826},
                 "status": "completed", "conclusion": "success"}]}
        if route == "branches/main":
            return {"protected": True,
                    "commit": {"sha": "e" * 40 if self.main_moved else MERGE}}
        if route == "deployments?sha=" + MERGE + "&per_page=100":
            if self.no_deployment:
                return []
            return [{"id": 123, "sha": HEAD if self.wrong_deployment_sha else MERGE,
                     "environment": "github-pages"}]
        if route == "deployments/123/statuses?per_page=100":
            return [{"deployment_id": 123,
                     "state": "failure" if self.deployment_failed else "success"}]
        raise AssertionError("unexpected provider route " + route)


class Live:
    def __init__(self):
        self.calls = []
        self.build = BUILD
        self.behavior = BEHAVIOR
        self.status = 200

    def __call__(self, repo, url):
        o._allowed_url(repo, url)
        self.calls.append(url)
        body = self.build if url.endswith("/build-info.json") else self.behavior
        return {"status": self.status, "body": body,
                "content_type": "application/json"}


class DownstreamOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.api = Provider()
        self.live = Live()

    def verify(self):
        return o.verify(self.api, self.live, repo=REPO, pr_number=900)

    def assert_hold(self, code):
        with self.assertRaisesRegex(o.OutcomeHold, code):
            self.verify()

    def test_original_provider_and_real_live_behavior_required(self):
        receipt = self.verify()
        self.assertEqual(receipt["status"], "VERIFIED_REAL_WORLD_REPAIR")
        self.assertEqual(receipt["candidate_head_sha"], HEAD)
        self.assertEqual(receipt["merge_main_sha"], MERGE)
        self.assertEqual(receipt["approved_pre_repair_base_sha"], BASE)
        self.assertEqual(receipt["provider_writes"], 0)
        self.assertIsNone(receipt["verified_customer_revenue"])
        self.assertEqual(len(self.live.calls), 2)

    def test_preapproved_contract_read_from_immutable_base_not_pr_current_base(self):
        self.verify()
        self.assertIn((REPO, "contents/repair/downstream-outcomes/900.json?ref=" + BASE),
                      self.api.calls)
        self.assertNotIn((REPO, "contents/repair/downstream-outcomes/900.json?ref=" + "d"*40),
                         self.api.calls)

    def test_a_fake_or_failing_independent_app_never_completes(self):
        self.api.bad_issuer = True
        self.assert_hold("INDEPENDENT_EXACT_HEAD")
        self.api.bad_issuer = False
        self.api.failed_check = True
        self.assert_hold("INDEPENDENT_EXACT_HEAD")
        self.assertEqual(self.live.calls, [])

    def test_rule_held_or_wrong_source_blocks_before_live(self):
        self.api.fail_rule = True
        self.assert_hold("PROTECTED_INDEPENDENT_GATE")
        self.api.fail_rule = False
        self.api.main_moved = True
        self.assert_hold("CURRENT_MAIN")
        self.assertEqual(self.live.calls, [])

    def test_no_preapproved_contract_cannot_be_added_post_hoc(self):
        self.api.missing_contract = True
        self.assert_hold("PREAPPROVED_CONTRACT_MISSING")
        self.assertEqual(self.live.calls, [])

    def test_wrong_merge_ancestry_prevents_claim(self):
        self.api.wrong_head = True
        self.assert_hold("MERGE_ANCESTRY_NOT_PROVEN")
        self.api.wrong_head = False
        self.api.wrong_merge_parent = True
        self.assert_hold("PREAPPROVED_CONTRACT_MISSING")

    def test_http_success_without_provider_deployment_is_not_delivery(self):
        self.api.no_deployment = True
        self.assert_hold("EXACT_DEPLOYMENT_NOT_FOUND")
        self.api.no_deployment = False
        self.api.deployment_failed = True
        self.assert_hold("DELIVERY_NOT_CONFIRMED")
        self.api.deployment_failed = False
        self.api.wrong_deployment_sha = True
        self.assert_hold("EXACT_DEPLOYMENT_NOT_FOUND")
        self.assertEqual(self.live.calls, [])

    def test_green_checks_and_deployment_with_stale_live_build_is_not_repair(self):
        self.live.build = json.dumps({"source_sha": BASE}).encode()
        self.assert_hold("LIVE_SOURCE_REVISION_MISMATCH")

    def test_green_checks_and_current_build_without_functional_fix_is_not_repair(self):
        self.live.behavior = b'{"actual_customer_path":"still-broken"}'
        self.assert_hold("FUNCTIONAL_BEHAVIOR_NOT_VERIFIED")

    def test_read_only_live_host_rejects_credentials_redirects_and_ssrf(self):
        for url in (
            "http://p00nsmasher.github.io/portfolio-brain/build-info.json",
            "https://example.com/portfolio-brain/build-info.json",
            "https://127.0.0.1/portfolio-brain/build-info.json",
            "https://p00nsmasher.github.io/portfolio-brain/../x",
            "https://p00nsmasher.github.io/portfolio-brain/%2e%2e/x",
            "https://p00nsmasher.github.io/portfolio-brain/build-info.json?debug=true",
            "https://user@p00nsmasher.github.io/portfolio-brain/build-info.json",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(o.OutcomeHold, "LIVE_HOST_OR_PATH_DENIED"):
                    o._allowed_url(REPO, url)

    def test_no_discretionary_repo_can_self_enroll_independent_issuer(self):
        with self.assertRaisesRegex(o.OutcomeHold, "REPOSITORY_OR_PR_NOT_ELIGIBLE"):
            o.verify(self.api, self.live, repo="P00NSMASHER/capturebrief", pr_number=900)

    def test_untrusted_client_cannot_use_write_or_secrets_route(self):
        client = o.GitHubReadOnly("x" * 30)
        for route in ("pulls/900/merge", "actions/dispatches",
                      "../issues", "secrets", "https://example.com"):
            with self.subTest(route=route):
                with self.assertRaisesRegex(o.OutcomeHold, "UNAPPROVED_GITHUB_ROUTE"):
                    client.get(REPO, route)
        self.assertEqual(client.reads, 0)


if __name__ == "__main__":
    unittest.main()
