"""Non-sensitive, bounded GitHub GET failure diagnostics.

The genuine 2026-10-09 SOURCE_API_404 incidents did not log the failed API
operation. Verify future requests report only a fixed classification, without
changing BrainError semantics or exposing repository/branch/query/token data.
No real network, credentials, state mutation, or provider budget increase.
"""
from contextlib import redirect_stderr
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from brain.adapters import GitHub, _api_request_family
from brain.core import BrainError


def http_failure(path, code, *, retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    raise urllib.error.HTTPError(
        "https://api.github.com" + path, code,
        "provider text must never be logged", headers, None
    )


class SourceReadFamilyDiagnostics(unittest.TestCase):
    def evidence(self, result):
        rows = result.getvalue().splitlines()
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0].startswith("{"))
        entry = json.loads(rows[0])
        self.assertEqual(entry["event"], "SOURCE_API_GET_FAILURE_CONTEXT")
        self.assertTrue(set(entry) <= {
            "event", "request_family", "http_status",
            "read_failure", "request_number"
        })
        return entry

    def test_categories_are_fixed_labels_not_paths(self):
        endpoints = {
            "/search/repositories?q=freight+invoice&per_page=2": "REPOSITORY_SEARCH",
            "/repos/SecretOrg/SecretRepo": "REPOSITORY_METADATA",
            "/repos/SecretOrg/SecretRepo/branches/production-secret": "BRANCH_LOOKUP",
            "/repos/SecretOrg/SecretRepo/git/trees/" + "a"*40
                + "?recursive=1": "GIT_TREE",
            "/repos/SecretOrg/SecretRepo/git/blobs/" + "b"*40: "GIT_BLOB",
            "/repos/SecretOrg/SecretRepo/commits/" + "c"*40
                + "/check-runs?per_page=100&page=2": "COMMIT_CHECK_RUNS",
            "/unrecognized?password=VERY_PRIVATE": "OTHER_BOUNDED_GET",
        }
        for path, family in endpoints.items():
            with self.subTest(family=family):
                self.assertEqual(_api_request_family(path), family)
        self.assertEqual(len(set(endpoints.values())), len(endpoints))

    def test_branch_404_reports_category_only_and_keeps_original_error(self):
        secret = "private-branch-fabricated-AUTH-123"
        path = "/repos/owner/do-not-name/branches/" + secret
        api = GitHub(transport=lambda p: http_failure(p, 404))
        stream = io.StringIO()
        with redirect_stderr(stream):
            with self.assertRaisesRegex(
                BrainError, r"SOURCE_API_404: GET failed; no cursor advanced"
            ):
                api.get(path)
        entry = self.evidence(stream)
        self.assertEqual(entry["request_family"], "BRANCH_LOOKUP")
        self.assertEqual(entry["http_status"], 404)
        self.assertEqual(entry["request_number"], 1)
        self.assertNotIn(secret, stream.getvalue())
        self.assertNotIn("owner", stream.getvalue())
        self.assertNotIn("do-not-name", stream.getvalue())
        self.assertNotIn("https", stream.getvalue())

    def test_search_query_and_authorization_are_never_rendered(self):
        sentinel = "api-secret-DO-NOT-PRINT-007"
        path = "/search/repositories?q=" + sentinel + "&per_page=2"
        with patch.dict(os.environ, {"GITHUB_TOKEN": sentinel}):
            api = GitHub(transport=lambda p: http_failure(p, 403))
        stream = io.StringIO()
        with redirect_stderr(stream):
            with self.assertRaisesRegex(BrainError, "SOURCE_API_403"):
                api.get(path)
        entry = self.evidence(stream)
        self.assertEqual(entry["request_family"], "REPOSITORY_SEARCH")
        self.assertEqual(entry["http_status"], 403)
        self.assertNotIn(sentinel, stream.getvalue())
        self.assertNotIn("q=", stream.getvalue())

    def test_nonretryable_tree_and_blob_failures_stay_fatal(self):
        for suffix, category, code in (
            ("/git/trees/" + "a"*40 + "?recursive=1", "GIT_TREE", 404),
            ("/git/blobs/" + "b"*40, "GIT_BLOB", 500),
        ):
            with self.subTest(category=category):
                api = GitHub(transport=lambda p: http_failure(p, code))
                output = io.StringIO()
                with redirect_stderr(output):
                    with self.assertRaisesRegex(
                        BrainError, "SOURCE_API_" + str(code)
                    ):
                        api.get("/repos/hidden/project" + suffix)
                entry = self.evidence(output)
                self.assertEqual(entry["request_family"], category)
                self.assertEqual(entry["http_status"], code)
                self.assertEqual(api.requests, 1)

    def test_successful_bounded_retry_emits_no_error_context(self):
        observed = []
        def transport(path):
            observed.append(path)
            if len(observed) == 1:
                http_failure(path, 503, retry_after=0)
            return {"ok": True}
        api = GitHub(transport=transport)
        output = io.StringIO()
        with redirect_stderr(output):
            self.assertEqual(api.get("/repos/example/probe"), {"ok": True})
        self.assertEqual(api.requests, 2)
        self.assertEqual(output.getvalue(), "")

    def test_retry_exhaustion_emits_one_terminal_context(self):
        api = GitHub(transport=lambda p: http_failure(p, 503, retry_after=0))
        output = io.StringIO()
        with redirect_stderr(output):
            with self.assertRaisesRegex(BrainError, "SOURCE_API_503"):
                api.get("/repos/example/probe")
        evidence = self.evidence(output)
        self.assertEqual(evidence["request_number"], 2)
        self.assertEqual(evidence["http_status"], 503)
        self.assertEqual(evidence["request_family"], "REPOSITORY_METADATA")
        self.assertEqual(api.requests, 2)

    def test_timeout_diagnostics_are_strictly_classified(self):
        def timeout(_):
            raise TimeoutError("private url, token and password")
        api = GitHub(transport=timeout)
        output = io.StringIO()
        with redirect_stderr(output):
            with self.assertRaisesRegex(
                BrainError, r"SOURCE_READ_FAILED:TimeoutError"
            ):
                api.get("/repos/example/name/git/blobs/" + "a"*40)
        evidence = self.evidence(output)
        self.assertEqual(evidence["read_failure"], "TimeoutError")
        self.assertNotIn("password", output.getvalue())
        self.assertNotIn("url", output.getvalue())

    def test_unsafe_request_and_budget_exhaustion_never_emit_fake_http(self):
        api = GitHub(transport=lambda _: self.fail("GET must not be attempted"))
        for path in ("//private", "https://not-allowed", "/repos/../secret"):
            with self.subTest(path=path):
                output = io.StringIO()
                with redirect_stderr(output):
                    with self.assertRaises(BrainError):
                        api.get(path)
                self.assertEqual(output.getvalue(), "")
        api.requests = 24
        output = io.StringIO()
        with redirect_stderr(output):
            with self.assertRaisesRegex(BrainError, "REQUEST_BUDGET_EXHAUSTED"):
                api.get("/repos/example/probe")
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
