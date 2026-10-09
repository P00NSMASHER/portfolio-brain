"""Adversarial, offline regression of optional uninitialized GitHub search hits.

A search hit is not a verified checkout. Only a missing branch on a public,
automatically discovered size-0 repository may be skipped; other source failures
and explicit lookups remain fail-closed. No network, credentials or writes.
"""
import base64
import hashlib
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from brain.__main__ import research
from brain.adapters import GitHub, policy
from brain.core import BrainError, Store


SHA = "a" * 40
TARGET = policy()["research_targets"][0]
EMPTY = "example/never-initialized"
VALID = "example/has-source"


def repo(name, *, size=0, private=False):
    return {
        "full_name": name, "private": private, "default_branch": "main",
        "size": size, "license": {"spdx_id": "MIT"},
    }


def missing_branch(path):
    raise urllib.error.HTTPError(
        "https://api.github.com" + path, 404, "Branch not found", None, None,
    )


def discovery_transport(*, unavailable=(EMPTY,), include_valid=False, other_error=None,
                        size=0, private=False):
    """Minimal exact-path transport with an optional genuine source blob."""
    raw = b"def invoice_audit():\n    return 'freight invoice duplicate audit'\n"
    blob_sha = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + bytes([0]) + raw,
    ).hexdigest()
    calls = []
    missing = set(unavailable)

    def transport(path):
        calls.append(path)
        if path.startswith("/search/repositories?"):
            items = [repo(EMPTY, size=size, private=private)]
            if include_valid:
                items.append(repo(VALID, size=10))
            return {"incomplete_results": False, "items": items}
        if path == "/repos/" + EMPTY:
            return repo(EMPTY, size=size, private=private)
        if path == "/repos/" + EMPTY + "/branches/main":
            if EMPTY in missing:
                if other_error is not None:
                    raise urllib.error.HTTPError(
                        "https://api.github.com" + path, other_error, "error",
                        None, None,
                    )
                missing_branch(path)
            return {"commit": {"sha": SHA}}
        if path == "/repos/" + EMPTY + "/git/trees/" + SHA + "?recursive=1":
            return {"truncated": False, "tree": []}
        if path == "/repos/" + VALID + "/branches/main":
            return {"commit": {"sha": SHA}}
        if path == "/repos/" + VALID + "/git/trees/" + SHA + "?recursive=1":
            return {"truncated": False, "tree": [
                {"type": "blob", "path": "src/invoice.py",
                 "size": len(raw), "sha": blob_sha},
                {"type": "blob", "path": "tests/test_invoice.py",
                 "size": 90, "sha": "b" * 40},
            ]}
        if path == "/repos/" + VALID + "/git/blobs/" + blob_sha:
            return {"sha": blob_sha, "encoding": "base64",
                    "content": base64.b64encode(raw).decode()}
        raise AssertionError("unexpected operation: " + path)

    return transport, calls


class MissingOptionalGitHubBranchTests(unittest.TestCase):
    def test_auto_discovered_empty_repository_branch_404_is_skipped(self):
        transport, calls = discovery_transport()
        api = GitHub(transport=transport)
        self.assertEqual(api.discover(TARGET), [])
        self.assertEqual(api.unavailable_discovery_branches, 1)
        self.assertEqual(api.requests, 2)
        self.assertFalse(any("/git/trees/" in c or "/git/blobs/" in c
                             for c in calls))

    def test_second_valid_repository_still_produces_source_evidence(self):
        transport, calls = discovery_transport(include_valid=True)
        api = GitHub(transport=transport)
        found = api.discover(TARGET)
        self.assertEqual(api.unavailable_discovery_branches, 1)
        self.assertEqual(len(found), 1)
        payload, is_private = found[0]
        self.assertFalse(is_private)
        self.assertEqual(payload["repository"], VALID)
        self.assertEqual(payload["head_sha"], SHA)
        self.assertEqual(payload["path"], "src/invoice.py")
        self.assertEqual(payload["test_paths"], ["tests/test_invoice.py"])
        self.assertIn("invoice", payload["matched_terms"])
        self.assertEqual(api.requests, 5)
        self.assertLessEqual(api.requests, policy()["max_requests_per_operation"])

    def test_zero_size_with_real_branch_is_not_skipped(self):
        transport, _ = discovery_transport(unavailable=())
        api = GitHub(transport=transport)
        self.assertEqual(api.discover(TARGET), [])
        self.assertEqual(api.unavailable_discovery_branches, 0)
        self.assertEqual(api.requests, 3)

    def test_nonempty_missing_branch_fails_closed(self):
        transport, _ = discovery_transport(size=1)
        with self.assertRaisesRegex(BrainError, "SOURCE_API_404"):
            GitHub(transport=transport).discover(TARGET)

    def test_missing_size_and_false_boolean_size_do_not_create_exceptions(self):
        for size in (None, False, 0.0, "0"):
            with self.subTest(size=size):
                transport, _ = discovery_transport(size=size)
                with self.assertRaisesRegex(BrainError, "SOURCE_API_404"):
                    GitHub(transport=transport).discover(TARGET)

    def test_private_hit_still_rejected_before_branch_suppression(self):
        transport, calls = discovery_transport(private=True)
        with self.assertRaisesRegex(BrainError, "private search result"):
            GitHub(transport=transport).discover(TARGET)
        self.assertFalse(any("/branches/" in c for c in calls))

    def test_explicit_target_missing_branch_fails_closed(self):
        transport, _ = discovery_transport()
        with self.assertRaisesRegex(BrainError, "SOURCE_API_404"):
            GitHub(transport=transport).discover(TARGET, repository=EMPTY)

    def test_other_http_errors_are_not_hidden(self):
        for code in (401, 403, 500):
            with self.subTest(code=code):
                transport, _ = discovery_transport(other_error=code)
                with self.assertRaisesRegex(BrainError, "SOURCE_API_" + str(code)):
                    GitHub(transport=transport).discover(TARGET)

    def test_coverage_is_explicit_and_not_reported_as_complete(self):
        transport, _ = discovery_transport()
        api = GitHub(transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.sqlite", visibility="PUBLIC")
            try:
                result = research(store, SHA, Path(tmp) / "report", api=api)
                self.assertEqual(result["operation"]["candidates_observed"], 0)
                self.assertEqual(result["operation"]["result"], "NO_MATCHES")
                self.assertEqual(result["operation"]["unavailable_discovery_branches"], 1)
                self.assertEqual(
                    result["operation"]["discovery_coverage"],
                    "PARTIAL_OPTIONAL_BRANCH_UNAVAILABLE",
                )
                saved = json.loads(
                    (Path(tmp) / "report" / "report.json").read_text()
                )
                self.assertEqual(saved["operation"], result["operation"])
            finally:
                store.close()

    def test_discovery_skip_count_is_per_call_not_cumulative(self):
        transport, _ = discovery_transport()
        api = GitHub(transport=transport)
        api.discover(TARGET)
        self.assertEqual(api.unavailable_discovery_branches, 1)
        api.discover(TARGET)
        self.assertEqual(api.unavailable_discovery_branches, 1)


if __name__ == "__main__":
    unittest.main()
