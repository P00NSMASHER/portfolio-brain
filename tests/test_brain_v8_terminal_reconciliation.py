"""Network-free terminal reconciliation for superseded CaptureBrief repair."""
import unittest
from unittest.mock import patch

from brain.v8 import repair_runtime as r


CURRENT = "c" * 40
CANONICAL_BLOB = "1" * 40
RELEASE_BLOB = "2" * 40
PREFIX = "repos/" + r.TARGET + "/"
ORIGINAL_BRANCH = r.BRANCH_PREFIX + r.EXPECTED_TARGET_HEAD[:12]
CURRENT_CANONICAL = (
    "# CaptureBrief deployment target\n"
    "Use GitHub Pages, not Netlify.\n"
    "- Website branch: `gh-pages`\n"
    "https://p00nsmasher.github.io/capturebrief/\n"
    "- Product engine and its regression tests: `main`\n"
)
CURRENT_RELEASE = (
    "# Verified public release artifact\n\n"
    "CaptureBrief's authoritative website uses GitHub Pages, the `gh-pages` branch,\n"
    "and https://p00nsmasher.github.io/capturebrief/.\n\n"
    "The older scripts are legacy packaging tools. They do not\n"
    "select the current hosting provider or authorize a website deployment.\n\n"
    "## Current GitHub Pages release handoff\n"
    "A successful product build or deployment job does not prove the intended content is live.\n"
)


class TerminalProvider:
    def __init__(self, *, fake_successor=False, successor_not_in_main=False,
                 semantic_regression=False, successor_extra_file=False,
                 wrong_actor=False, wrong_fingerprint=False, move_main=False):
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
        if marker == "current_canonical":
            return CURRENT_CANONICAL, CANONICAL_BLOB
        if marker == "current_release":
            release = CURRENT_RELEASE
            if self.semantic_regression:
                release = release.replace(
                    "does not prove the intended content is live",
                    "proves the intended content is live",
                )
            return release, RELEASE_BLOB
        if marker == "original_candidate":
            return "reviewed original candidate", r.ORIGINAL_REPAIR_BLOB
        raise AssertionError((value, label))

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
            return {"fixture": "current_canonical"}
        if path == PREFIX + "contents/" + r.DOC + "?ref=" + CURRENT:
            return {"fixture": "current_release"}
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
