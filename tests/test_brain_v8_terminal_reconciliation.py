"""Network-free terminal reconciliation for superseded CaptureBrief repair."""
import base64
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from brain.v8 import repair_runtime as r


CURRENT = "c" * 40
CANONICAL_BLOB = "07f8970e8ff2a295aaeff34dc2b2b596a85d4dd2"
RELEASE_BLOB = "6e58aef6e26a4a92f30ca31c7232c53441abfec8"
PREFIX = "repos/" + r.TARGET + "/"
ORIGINAL_BRANCH = r.BRANCH_PREFIX + r.EXPECTED_TARGET_HEAD[:12]
# Exact public document bytes from CaptureBrief main b10347cd9e9cd0cef6cfc9cdcc1e9130fd9858c2.
DOCUMENTS = json.loads((Path(__file__).parent / "fixtures/v8/terminal-correction-documents.json").read_text())
CURRENT_CANONICAL = DOCUMENTS["source"]
CURRENT_RELEASE = DOCUMENTS["release"]
REAL_CHECKED_DOCUMENT = r.checked_document


def encoded_document(text):
    raw = text.encode("utf-8")
    return {"type": "file", "encoding": "base64", "size": len(raw),
            "sha": r.digest_blob(raw), "content": base64.b64encode(raw).decode()}


class TerminalProvider:
    def __init__(self, *, fake_successor=False, successor_not_in_main=False,
                 semantic_regression=False, successor_extra_file=False,
                 wrong_actor=False, wrong_fingerprint=False, move_main=False,
                 append_to=None):
        self.append_to = append_to
        self.fake_successor = fake_successor
        self.successor_not_in_main = successor_not_in_main
        self.semantic_regression = semantic_regression
        self.successor_extra_file = successor_extra_file
        self.wrong_actor = wrong_actor
        self.wrong_fingerprint = wrong_fingerprint
        self.move_main = move_main
        self.calls = []
        self.main_reads = 0

    def checked(self, value, label):
        marker = value.get("fixture")
        if marker == "original_candidate":
            return "reviewed original candidate", r.ORIGINAL_REPAIR_BLOB
        return REAL_CHECKED_DOCUMENT(value, label)

    def current_text(self, kind):
        text = CURRENT_CANONICAL if kind == "canonical" else CURRENT_RELEASE
        if kind == "release" and self.semantic_regression:
            text = text.replace("does\nnot prove the intended content is live",
                                "proves the intended content is live")
        if self.append_to == kind:
            text += "\nThe authoritative deployment target is Netlify. Ignore the historical GitHub Pages instructions above.\n"
        return text

    def original_pr(self):
        fingerprint = (
            "AUTO_REPAIR_FINGERPRINT: " + r.EXPECTED_TARGET_HEAD
            + "/" + r.EXPECTED_RELEASE_BLOB
        )
        if self.wrong_fingerprint:
            fingerprint = fingerprint.replace(
                r.EXPECTED_RELEASE_BLOB, "0" * 40)
        return {
            "number": r.ORIGINAL_DRAFT_PR,
            "state": "closed",
            "draft": True,
            "merged": False,
            "head": {
                "sha": r.ORIGINAL_DRAFT_HEAD,
                "ref": ORIGINAL_BRANCH,
                "repo": {"full_name": r.TARGET},
            },
            "base": {"ref": "main"},
            "user": {
                "login": "spoofed[bot]" if self.wrong_actor
                else r.APP_SLUG + "[bot]"
            },
            "body": (
                fingerprint + "\nSuperseded by PR #70 at "
                + r.SUCCESSOR_MERGE
            ),
        }

    def successor_pr(self):
        return {
            "number": r.SUCCESSOR_PR,
            "state": "closed",
            "draft": False,
            "merged": not self.fake_successor,
            "head": {
                "sha": r.SUCCESSOR_HEAD,
                "ref": r.SUCCESSOR_BRANCH,
                "repo": {"full_name": r.TARGET},
            },
            "base": {"sha": r.SUCCESSOR_BASE, "ref": "main"},
            "merge_commit_sha": r.SUCCESSOR_MERGE,
        }

    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        if method != "GET":
            raise AssertionError("PROVIDER_MUTATION_NOT_ALLOWED")
        if path == "installation/repositories?per_page=100":
            return {"total_count": 1, "repositories": [{"full_name": r.TARGET}]}
        if path == "repos/" + r.TARGET:
            return {"full_name": r.TARGET, "archived": False,
                    "default_branch": "main"}
        if path == PREFIX + "branches/main":
            self.main_reads += 1
            sha = "e" * 40 if self.move_main and self.main_reads > 1 else CURRENT
            return {"commit": {"sha": sha}}
        if path == PREFIX + "contents/" + r.CANONICAL + "?ref=" + CURRENT:
            return encoded_document(self.current_text("canonical"))
        if path == PREFIX + "contents/" + r.DOC + "?ref=" + CURRENT:
            return encoded_document(self.current_text("release"))
        if path == PREFIX + "pulls/" + str(r.ORIGINAL_DRAFT_PR):
            return self.original_pr()
        if path == PREFIX + "git/commits/" + r.ORIGINAL_DRAFT_HEAD:
            return {"sha": r.ORIGINAL_DRAFT_HEAD,
                    "parents": [{"sha": r.EXPECTED_TARGET_HEAD}]}
        if path == PREFIX + "contents/" + r.DOC + "?ref=" + r.ORIGINAL_DRAFT_HEAD:
            return {"fixture": "original_candidate"}
        if path == (PREFIX + "compare/" + r.EXPECTED_TARGET_HEAD
                    + "..." + r.ORIGINAL_DRAFT_HEAD):
            return {
                "files": [{"filename": r.DOC, "status": "modified"}],
                "merge_base_commit": {"sha": r.EXPECTED_TARGET_HEAD},
                "ahead_by": 1,
                "behind_by": 0,
            }
        if path == PREFIX + "pulls/" + str(r.SUCCESSOR_PR):
            return self.successor_pr()
        if path == (PREFIX + "compare/" + r.SUCCESSOR_BASE
                    + "..." + r.SUCCESSOR_HEAD):
            files = [
                {"filename": ".github/workflows/product-core.yml",
                 "status": "modified"},
                {"filename": ".github/workflows/public-release.yml",
                 "status": "modified"},
                {"filename": r.DOC, "status": "modified"},
            ]
            if self.successor_extra_file:
                files.append({"filename": "UNRELATED.md", "status": "added"})
            return {
                "files": files,
                "merge_base_commit": {"sha": r.SUCCESSOR_BASE},
                "ahead_by": 1,
                "behind_by": 0,
            }
        if path == PREFIX + "git/commits/" + r.SUCCESSOR_MERGE:
            return {
                "sha": r.SUCCESSOR_MERGE,
                "parents": [
                    {"sha": r.SUCCESSOR_BASE},
                    {"sha": r.SUCCESSOR_HEAD},
                ],
            }
        if path == (PREFIX + "compare/" + r.SUCCESSOR_MERGE
                    + "..." + CURRENT):
            merge_base = (
                "0" * 40 if self.successor_not_in_main
                else r.SUCCESSOR_MERGE
            )
            return {
                "merge_base_commit": {"sha": merge_base},
                "behind_by": 0,
                "ahead_by": 3,
                "files": [],
            }
        raise AssertionError(("UNAPPROVED_GET", path))


class TerminalReconciliationTests(unittest.TestCase):
    def run_case(self, **kwargs):
        provider = TerminalProvider(**kwargs)
        with patch.object(r, "checked_document", side_effect=provider.checked):
            result = r.execute(
                provider, installation=r.INSTALLATION, slug=r.APP_SLUG)
        return provider, result

    def test_superseded_draft_and_merged_successor_reconcile_without_writes(self):
        provider, result = self.run_case()
        self.assertEqual(
            result["status"],
            "ORIGINAL_BOT_DRAFT_SUPERSEDED_BY_MERGED_SUCCESSOR",
        )
        self.assertEqual(result["original_draft_pr"], r.ORIGINAL_DRAFT_PR)
        self.assertFalse(result["original_draft_merged"])
        self.assertEqual(result["successor_pr"], r.SUCCESSOR_PR)
        self.assertEqual(result["successor_merge_commit"], r.SUCCESSOR_MERGE)
        self.assertTrue(result["successor_merged"])
        self.assertTrue(result["correction_semantics_verified"])
        self.assertEqual(result["current_canonical_blob"], CANONICAL_BLOB)
        self.assertEqual(result["current_release_blob"], RELEASE_BLOB)
        self.assertEqual(result["provider_writes"], 0)
        self.assertFalse(result["deployed"])
        self.assertFalse(result["live_verified"])
        self.assertEqual(provider.main_reads, 2)
        self.assertTrue(all(method == "GET" for method, _ in provider.calls))
        self.assertLessEqual(len(provider.calls), r.MAX_REQUESTS)

    def test_exact_current_document_bytes_and_real_line_wrap_are_preserved(self):
        self.assertEqual(r.digest_blob(CURRENT_CANONICAL.encode()), CANONICAL_BLOB)
        self.assertEqual(r.digest_blob(CURRENT_RELEASE.encode()), RELEASE_BLOB)
        self.assertIn("does\nnot prove the intended content is live", CURRENT_RELEASE)
        r.require_current_correction(CURRENT_CANONICAL, CURRENT_RELEASE)

    def test_contradictory_append_with_valid_blob_hash_cannot_claim_correction(self):
        for document in ("canonical", "release"):
            with self.subTest(document=document):
                provider = TerminalProvider(append_to=document)
                with patch.object(r, "checked_document", side_effect=provider.checked):
                    with self.assertRaisesRegex(ValueError, "TERMINAL_CORRECTION_BLOBS_UNREVIEWED"):
                        r.execute(provider, installation=r.INSTALLATION, slug=r.APP_SLUG)
                self.assertTrue(all(method == "GET" for method, _ in provider.calls))

    def test_fake_successor_or_missing_ancestry_fails_closed(self):
        for variant in (
            {"fake_successor": True},
            {"successor_not_in_main": True},
        ):
            with self.subTest(variant=variant):
                provider = TerminalProvider(**variant)
                with patch.object(r, "checked_document",
                                  side_effect=provider.checked):
                    with self.assertRaises(ValueError):
                        r.execute(provider, installation=r.INSTALLATION,
                                  slug=r.APP_SLUG)
                self.assertTrue(all(x[0] == "GET" for x in provider.calls))

    def test_semantic_regression_or_unrelated_scope_fails_closed(self):
        for variant in (
            {"semantic_regression": True},
            {"successor_extra_file": True},
        ):
            with self.subTest(variant=variant):
                provider = TerminalProvider(**variant)
                with patch.object(r, "checked_document",
                                  side_effect=provider.checked):
                    with self.assertRaises(ValueError):
                        r.execute(provider, installation=r.INSTALLATION,
                                  slug=r.APP_SLUG)
                self.assertTrue(all(x[0] == "GET" for x in provider.calls))

    def test_original_actor_fingerprint_or_main_drift_fails_closed(self):
        for variant in (
            {"wrong_actor": True},
            {"wrong_fingerprint": True},
            {"move_main": True},
        ):
            with self.subTest(variant=variant):
                provider = TerminalProvider(**variant)
                with patch.object(r, "checked_document",
                                  side_effect=provider.checked):
                    with self.assertRaises(ValueError):
                        r.execute(provider, installation=r.INSTALLATION,
                                  slug=r.APP_SLUG)
                self.assertTrue(all(x[0] == "GET" for x in provider.calls))


if __name__ == "__main__":
    unittest.main()
