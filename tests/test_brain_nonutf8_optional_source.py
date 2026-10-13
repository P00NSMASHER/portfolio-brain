"""V7 safe handling of hash-verified, non-UTF-8 optional GitHub search hits.

Simulates real Git source bytes, repository discovery, original SQLite state,
strict provider scopes, and quota. No live API reads or original state writes.
"""
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.__main__ import research
from brain.adapters import GitHub, event
from brain.core import BrainError, Store
from test_brain_search_volatility import (
    FakeGitHub, TARGET, GOOD, MISSING, BAD, SHA, NOW, SOURCE, BLOB,
)

BINARY = b"def invoice_match(rows):\x81\n    return rows\n"
BINARY_SHA = hashlib.sha1(
    b"blob " + str(len(BINARY)).encode() + b"\x00" + BINARY
).hexdigest()
REASON = "SEARCH_RESULT_NON_UTF8_BLOB_NOT_INSPECTED"


class NonUtf8Source(FakeGitHub):
    def __init__(self, names=None, *, invalid=None, spoof_error=False,
                 broken_hash=False, **kwargs):
        super().__init__(names=names, **kwargs)
        self.invalid = set(invalid if invalid is not None else [MISSING])
        self.spoof_error = spoof_error
        self.broken_hash = broken_hash

    def __call__(self, path):
        for repo in self.invalid:
            base = "/repos/" + repo
            if path.startswith(base + "/git/trees/"):
                self.paths.append(path)
                return {"truncated": False, "tree": [
                    {"type": "blob", "path": "src/invoice_match.py",
                     "sha": BINARY_SHA, "size": len(BINARY)},
                    {"type": "blob", "path": "tests/test_invoice_match.py",
                     "sha": "c" * 40, "size": 18},
                ]}
            if path.startswith(base + "/git/blobs/"):
                self.paths.append(path)
                if self.spoof_error:
                    raise BrainError("SOURCE_BLOB_NOT_UTF8")
                raw = BINARY.replace(b"\x81", b"\x82") if self.broken_hash else BINARY
                return {"encoding": "base64", "sha": BINARY_SHA,
                        "content": base64.b64encode(raw).decode("ascii")}
        return super().__call__(path)


class OptionalPublicBlobTests(unittest.TestCase):
    def test_bad_optional_hit_quarantined_and_verified_second_repo_used(self):
        fake = NonUtf8Source(names=[MISSING, GOOD])
        api = GitHub(transport=fake)
        inspected = api.discover(TARGET)
        self.assertEqual(len(inspected), 1)
        payload, private = inspected[0]
        self.assertEqual(payload["repository"], GOOD)
        self.assertIs(private, False)
        self.assertEqual(payload["code_sha256"], hashlib.sha256(BLOB).hexdigest())
        self.assertEqual(api.discovery_unavailable, [{
            "repository": MISSING, "stage": "blob",
            "reason": REASON
        }])
        self.assertEqual(api.requests, 7)
        self.assertEqual(len(fake.paths), api.requests)
        self.assertNotIn("invoice_match(rows):", json.dumps(api.discovery_unavailable))
        self.assertEqual(api.discovery_bounded_trees, [])

    def test_two_non_text_hits_produce_explicit_failure_not_no_matches(self):
        fake = NonUtf8Source(names=[MISSING, BAD], invalid={MISSING, BAD})
        api = GitHub(transport=fake)
        with self.assertRaisesRegex(BrainError, "DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE") as exc:
            api.discover(TARGET)
        self.assertIn("non-UTF-8 source", str(exc.exception))
        self.assertEqual(api.requests, 7)
        self.assertEqual(len(api.discovery_unavailable), 2)
        self.assertTrue(all(item["reason"] == REASON
                            for item in api.discovery_unavailable))
        self.assertFalse(api.private)

    def test_explicit_repo_blob_unreadable_remains_fatal(self):
        fake = NonUtf8Source(names=[MISSING])
        api = GitHub(transport=fake)
        with self.assertRaisesRegex(BrainError, "SOURCE_BLOB_NOT_UTF8"):
            api.discover(TARGET, repository=MISSING)
        self.assertEqual(api.requests, 4)
        self.assertEqual(api.discovery_unavailable, [])

    def test_private_mode_is_never_allowed_to_suppress_non_utf8_source(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"}):
            fake = NonUtf8Source(names=[MISSING, GOOD])
            api = GitHub(private=True, transport=fake)
            with self.assertRaisesRegex(BrainError, "SOURCE_BLOB_NOT_UTF8"):
                api.discover(TARGET)
            self.assertEqual(api.discovery_unavailable, [])
            self.assertEqual(api.requests, 4)

    def test_git_blob_sha_mismatch_remains_fatal_even_on_non_utf8_blob(self):
        fake = NonUtf8Source(names=[MISSING, GOOD], broken_hash=True)
        api = GitHub(transport=fake)
        with self.assertRaisesRegex(BrainError, "SOURCE_CONTENT_HASH_MISMATCH"):
            api.discover(TARGET)
        self.assertEqual(api.discovery_unavailable, [])
        self.assertEqual(api.requests, 4)

    def test_forged_provider_error_string_cannot_skip_unreadable_blob(self):
        fake = NonUtf8Source(names=[MISSING, GOOD], spoof_error=True)
        api = GitHub(transport=fake)
        with self.assertRaisesRegex(BrainError, "SOURCE_BLOB_NOT_UTF8"):
            api.discover(TARGET)
        self.assertEqual(api.discovery_unavailable, [])
        self.assertEqual(api.requests, 4)

    def test_valid_utf8_hit_unmodified_and_no_gaps(self):
        fake = NonUtf8Source(names=[GOOD], invalid=set())
        api = GitHub(transport=fake)
        inspected = api.discover(TARGET)
        self.assertEqual(len(inspected), 1)
        self.assertEqual(inspected[0][0]["repository"], GOOD)
        self.assertEqual(api.discovery_unavailable, [])
        self.assertEqual(api.requests, 4)

    @patch("brain.adapters.utcnow", return_value=NOW)
    @patch("brain.core.utcnow", return_value=NOW)
    def test_research_uses_verified_source_and_records_incomplete_search(self, _core, _adapter):
        api = GitHub(transport=NonUtf8Source(names=[MISSING, GOOD]))
        with tempfile.TemporaryDirectory() as directory:
            state = Store(Path(directory) / "original.sqlite", visibility="PUBLIC")
            try:
                repo = "P00NSMASHER/portfolio-brain"
                payload = {"repository": repo, "head_sha": SHA,
                           "default_branch": "main", "checks": [], "open_issues": 0,
                           "source_ref": f"https://github.com/{repo}/commit/{SHA}"}
                state.submit([event("repository", repo, payload, SHA, now=NOW)], now=NOW)
                state.drain()
                output = Path(directory) / "private_report"
                result = research(state, SHA, output, api=api)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["operation"]["result"],
                                 "OBSERVED_WITH_SEARCH_RESULT_GAPS")
                self.assertEqual(result["operation"]["candidates_observed"], 1)
                self.assertEqual(result["operation"]["unavailable_search_results"],
                                 [{"repository": MISSING, "stage": "blob",
                                   "reason": REASON}])
                self.assertEqual(result["reuse_candidates"][0]["repository"], GOOD)
                self.assertEqual(state.pending(), 0)
                self.assertEqual(result["state_sequence"], 2)
                self.assertEqual(json.loads((output / "report.json").read_text())
                                 ["operation"], result["operation"])
                self.assertFalse(result["learning"]["autonomous_code_execution"])
            finally:
                state.close()

    def test_two_invalid_hits_do_not_store_fake_candidate_or_pass_attempt(self):
        api = GitHub(transport=NonUtf8Source(
            names=[MISSING, BAD], invalid={MISSING, BAD}))
        with tempfile.TemporaryDirectory() as directory:
            state = Store(Path(directory) / "original.sqlite", visibility="PUBLIC")
            try:
                with self.assertRaisesRegex(
                    BrainError, "DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE"
                ):
                    research(state, SHA, Path(directory) / "out", api=api)
                self.assertEqual(state.pending(), 0)
                self.assertEqual(
                    state.db.execute("SELECT count(*) FROM events").fetchone()[0], 0)
                self.assertEqual(
                    state.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 0)
            finally:
                state.close()


if __name__ == "__main__":
    unittest.main()
