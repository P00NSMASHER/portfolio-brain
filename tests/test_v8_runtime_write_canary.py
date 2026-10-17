import base64
import unittest
from verification.v8_runtime_write_canary import (
    APP_ID, APP_SLUG, TARGET, DENIED, FailClosed, NoRedirect, run,
)

SHA = "a" * 40
COMMIT = "b" * 40


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.target_branch = False
        self.negative_branch = False
        self.negative_allowed = False
        self.inventory_count = 1
        self.saved = None
        self.pr = None
        self.fail_pr_create = False

    def request(self, method, path, body=None, errors=()):
        self.calls.append((method, path))
        if path == "/installation/repositories?per_page=100":
            return 200, {"total_count": self.inventory_count,
                         "repositories": [{"full_name": TARGET}]}
        if method == "GET" and path == "/repos/" + TARGET + "/branches/main":
            return 200, {"commit": {"sha": SHA}}
        if method == "POST" and path == "/repos/" + DENIED + "/git/refs":
            if self.negative_allowed:
                self.negative_branch = True
                return 201, {"ref": body["ref"]}
            return 404, {}
        if method == "DELETE" and path.startswith("/repos/" + DENIED + "/git/refs/heads/"):
            self.negative_branch = False
            return 204, {}
        if method == "GET" and path.startswith("/repos/" + TARGET + "/git/ref/heads/"):
            return (200, {"ref": path}) if self.target_branch else (404, {})
        if method == "POST" and path == "/repos/" + TARGET + "/git/refs":
            self.target_branch = True
            self.branch = body["ref"].removeprefix("refs/heads/")
            return 201, {"ref": body["ref"]}
        if method == "PUT" and path.startswith("/repos/" + TARGET + "/contents/"):
            self.saved = (path.removeprefix("/repos/" + TARGET + "/contents/"),
                          base64.b64decode(body["content"]))
            return 201, {"commit": {"sha": COMMIT}}
        if method == "GET" and path.startswith("/repos/" + TARGET + "/contents/"):
            return 200, {"path": self.saved[0], "content": base64.b64encode(self.saved[1]).decode()}
        if method == "POST" and path == "/repos/" + TARGET + "/pulls":
            if self.fail_pr_create:
                raise FailClosed("TEST_TRANSIENT_PR_CREATE")
            self.pr = {"number": 19, "title": body["title"], "draft": True,
                       "state": "open", "head": {"ref": body["head"], "sha": COMMIT},
                       "base": {"ref": "main"}, "merged_at": None}
            return 201, self.pr
        if method == "GET" and path.startswith("/repos/" + TARGET + "/pulls?"):
            return 200, [self.pr] if self.pr else []
        if method == "GET" and path == "/repos/" + TARGET + "/pulls/19":
            return 200, self.pr
        if method == "PATCH" and path == "/repos/" + TARGET + "/pulls/19":
            self.pr["state"] = "closed"
            return 200, self.pr
        if method == "DELETE" and path.startswith("/repos/" + TARGET + "/git/refs/heads/"):
            self.target_branch = False
            return 204, {}
        raise AssertionError("UNEXPECTED_FAKE_REQUEST: " + method + " " + path)


class WriteCanaryTests(unittest.TestCase):
    def test_success_verifies_denial_draft_readback_and_compensating_cleanup(self):
        provider = FakeProvider()
        receipt = run(provider, APP_ID, APP_SLUG, "12345678901", SHA)
        self.assertEqual(receipt["proof"], "ORIGINAL_PROVIDER_WRITE_AND_CLEANUP")
        self.assertEqual(receipt["scoped_token_repository_count"], 1)
        self.assertEqual(receipt["cross_repo_write_denied_http"], 404)
        self.assertEqual(receipt["draft_pr_number"], 19)
        self.assertTrue(receipt["draft_verified_then_closed"])
        self.assertTrue(receipt["temporary_branch_deleted"])
        self.assertEqual(provider.pr["state"], "closed")
        self.assertFalse(provider.target_branch)
        self.assertFalse(provider.negative_branch)
        self.assertFalse(receipt["production_deployed"])
        self.assertFalse(receipt["merge_authority_tested"])
        self.assertFalse(receipt["acceptance_started"])
        self.assertFalse(any(method == "PUT" and "/branches/main" in path
                             for method, path in provider.calls))

    def test_bad_app_identity_fails_before_provider_access(self):
        provider = FakeProvider()
        with self.assertRaisesRegex(FailClosed, "IDENTITY"):
            run(provider, "wrong-app", APP_SLUG, "12345678901", SHA)
        self.assertEqual(provider.calls, [])

    def test_broad_token_inventory_fails_before_any_write(self):
        provider = FakeProvider()
        provider.inventory_count = 2
        with self.assertRaisesRegex(FailClosed, "TOKEN_REPOSITORY_BOUNDARY_FAILED"):
            run(provider, APP_ID, APP_SLUG, "12345678901", SHA)
        self.assertFalse(any(method != "GET" for method, _ in provider.calls))

    def test_unexpected_outside_write_is_undone_and_fails_closed(self):
        provider = FakeProvider()
        provider.negative_allowed = True
        with self.assertRaisesRegex(FailClosed, "CROSS_REPOSITORY_WRITE"):
            run(provider, APP_ID, APP_SLUG, "12345678901", SHA)
        self.assertFalse(provider.negative_branch)
        self.assertFalse(provider.target_branch)

    def test_failed_pr_creation_still_removes_branch_and_file(self):
        provider = FakeProvider()
        provider.fail_pr_create = True
        with self.assertRaisesRegex(FailClosed, "TEST_TRANSIENT_PR_CREATE"):
            run(provider, APP_ID, APP_SLUG, "12345678901", SHA)
        self.assertFalse(provider.target_branch)
        self.assertIsNone(provider.pr)

    def test_provider_rejects_redirects_and_nonstandard_endpoints(self):
        with self.assertRaisesRegex(FailClosed, "UNEXPECTED_REDIRECT"):
            NoRedirect().redirect_request(None, None, 302, "found", {}, "https://example.com")

    def test_invalid_source_rejected_before_writes(self):
        provider = FakeProvider()
        with self.assertRaisesRegex(FailClosed, "RUN_OR_SOURCE_INVALID"):
            run(provider, APP_ID, APP_SLUG, "12345678901", "not-a-source")
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
