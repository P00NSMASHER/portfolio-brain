"""Regression for GitHub compare SHA syntax in the scoped V8 repair API allowlist.

The genuine 2026-10-17 CaptureBrief recovery requires GET compare/A...B,
which the previous generic '..' traversal screen rejected before any HTTP.
These tests allow only that exact immutable SHA comparison and fail closed
for traversal and unreviewed endpoints without making network calls.
"""
import io
import json
import unittest

from brain.v8.repair_runtime import GitHubAPI, TARGET, EXPECTED_TARGET_HEAD

PARENT = EXPECTED_TARGET_HEAD
CHILD = "33a0b2cd26921935bfca11a0b35e566ad0c735f1"
PREFIX = "repos/" + TARGET + "/"


class FakeOpener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        assert timeout == 20
        return io.BytesIO(json.dumps({
            "merge_base_commit": {"sha": PARENT},
            "ahead_by": 1,
            "behind_by": 0,
            "files": [{"filename": "PUBLIC-RELEASE.md", "status": "modified"}],
        }).encode("utf-8"))


class V8ExactCompareAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.api = GitHubAPI("a" * 32)
        self.opener = FakeOpener()
        self.api.opener = self.opener

    def test_real_single_parent_git_compare_is_admitted_without_network(self):
        endpoint = PREFIX + "compare/" + PARENT + "..." + CHILD
        response = self.api("GET", endpoint)
        self.assertEqual(response["merge_base_commit"]["sha"], PARENT)
        self.assertEqual(response["files"][0]["filename"], "PUBLIC-RELEASE.md")
        self.assertEqual(len(self.opener.requests), 1)
        self.assertEqual(self.opener.requests[0].get_method(), "GET")
        self.assertEqual(
            self.opener.requests[0].full_url,
            "https://api.github.com/" + endpoint,
        )

    def test_no_partial_or_extra_dots_escape_exact_compare(self):
        for suffix in (
            PARENT + ".." + CHILD,
            PARENT + "...." + CHILD,
            PARENT + "....." + CHILD,
            PARENT + "..." + CHILD + "/../secrets",
            PARENT + "..." + CHILD + "?q=..",
            PARENT + "...../" + CHILD,
            PARENT + ".../" + CHILD,
        ):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                self.api("GET", PREFIX + "compare/" + suffix)
        self.assertEqual(self.opener.requests, [])

    def test_no_encoded_traversal_other_repo_or_unreviewed_write(self):
        denied = (
            PREFIX + "git/commits/" + CHILD + "/../refs",
            PREFIX + "contents/PUBLIC-RELEASE.md?ref=" + CHILD + "%2e%2e",
            PREFIX + "branches/v8-capturebrief-hosting-doc-" + PARENT[:12] + "/../secrets",
            PREFIX + "compare/" + PARENT + "..." + CHILD + "#frag",
            "repos/P00NSMASHER/portfolio-brain/compare/" + PARENT + "..." + CHILD,
            PREFIX + "pulls?state=all&per_page=100",
        )
        for path in denied:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.api("GET", path)
        with self.assertRaises(ValueError):
            self.api("POST", PREFIX + "compare/" + PARENT + "..." + CHILD, {})
        self.assertEqual(self.opener.requests, [])


if __name__ == "__main__":
    unittest.main()
