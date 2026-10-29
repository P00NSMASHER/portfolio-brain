"""Network-free regressions for original bot draft readback after unrelated target drift."""
import unittest
from unittest.mock import patch

from brain.v8 import repair_runtime as r

CURRENT = "c" * 40
CHILD = "d" * 40
PREFIX = "repos/" + r.TARGET + "/"
BRANCH = r.BRANCH_PREFIX + r.EXPECTED_TARGET_HEAD[:12]
CANON = (
    "# CaptureBrief deployment target\n"
    "Use GitHub Pages, not Netlify.\n"
    "- Website branch: `gh-pages`\n"
    "https://p00nsmasher.github.io/capturebrief/\n"
    "- Product engine and its regression tests: `main`\n"
)
OLD = (
    "# Verified public release artifact\n\n"
    + r.MISLEADING
    + "## Build and publication are separate\nHistorical package.\n\n"
    + r.HANDOFF_START
    + "Download a Netlify package for a manual deployment to the\n"
    + "existing project's Deploys page.\n"
    + "Do not submit test forms or send notification emails.\n\n"
    + r.HANDOFF_END + "\nPreserve existing fulfillment safety.\n"
)
FIXED = r.plan(CANON, OLD)


class DriftProvider:
    def __init__(self, *, changed_doc=False, missing_pr=False,
                 wrong_actor=False, wrong_parent=False, extra_file=False,
                 wrong_base=False, move_main=False, duplicate_pr=False):
        self.changed_doc = changed_doc
        self.missing_pr = missing_pr
        self.wrong_actor = wrong_actor
        self.wrong_parent = wrong_parent
        self.extra_file = extra_file
        self.wrong_base = wrong_base
        self.move_main = move_main
        self.duplicate_pr = duplicate_pr
        self.calls = []
        self.main_reads = 0

    def checked(self, value, label):
        marker = value.get("fixture")
        if marker == "canonical":
            return CANON, r.EXPECTED_CANONICAL_BLOB
        if marker == "release":
            return OLD, "f" * 40 if self.changed_doc else r.EXPECTED_RELEASE_BLOB
        if marker == "candidate":
            return FIXED, r.digest_blob(FIXED.encode())
        raise AssertionError((value, label))

    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        if method != "GET":
            raise AssertionError("PROVIDER_MUTATION_NOT_ALLOWED")
        if path == "installation/repositories?per_page=100":
            return {"total_count": 1, "repositories": [{"full_name": r.TARGET}]}
        if path == "repos/" + r.TARGET:
            return {"full_name": r.TARGET, "archived": False, "default_branch": "main"}
        if path == PREFIX + "branches/main":
            self.main_reads += 1
            sha = "e" * 40 if self.move_main and self.main_reads > 1 else CURRENT
            return {"commit": {"sha": sha}}
        if path == PREFIX + "contents/" + r.CANONICAL + "?ref=" + CURRENT:
            return {"fixture": "canonical"}
        if path == PREFIX + "contents/" + r.DOC + "?ref=" + CURRENT:
            return {"fixture": "release"}
        if path == PREFIX + "pulls?state=open&per_page=100":
            row = {"number": 47, "head": {"ref": BRANCH}}
            if self.missing_pr:
                return []
            return [row, row] if self.duplicate_pr else [row]
        if path == PREFIX + "branches/" + BRANCH:
            return {"commit": {"sha": CHILD}}
        if path == PREFIX + "git/commits/" + CHILD:
            return {"sha": CHILD, "parents": [
                {"sha": "a" * 40 if self.wrong_parent else r.EXPECTED_TARGET_HEAD}]}
        if path == PREFIX + "contents/" + r.DOC + "?ref=" + CHILD:
            return {"fixture": "candidate"}
        if path == PREFIX + "compare/" + r.EXPECTED_TARGET_HEAD + "..." + CHILD:
            files = [{"filename": r.DOC, "status": "modified"}]
            if self.extra_file:
                files.append({"filename": ".github/workflows/release.yml",
                              "status": "added"})
            return {"files": files, "ahead_by": 1, "behind_by": 0,
                    "merge_base_commit": {"sha": r.EXPECTED_TARGET_HEAD}}
        if path == PREFIX + "pulls/47":
            return {"number": 47, "state": "open", "draft": True, "merged": False,
                    "head": {"sha": CHILD, "ref": BRANCH,
                             "repo": {"full_name": r.TARGET}},
                    "base": {"sha": "b" * 40 if self.wrong_base else CURRENT,
                             "ref": "main"},
                    "user": {"login": "spoofed[bot]" if self.wrong_actor
                             else r.APP_SLUG + "[bot]"}}
        raise AssertionError(("UNAPPROVED_GET", path))


class StaleOriginalDraftTests(unittest.TestCase):
    def run_case(self, **kwargs):
        provider = DriftProvider(**kwargs)
        with patch.object(r, "checked_document", side_effect=provider.checked):
            result = r.execute(provider, installation=r.INSTALLATION, slug=r.APP_SLUG)
        return provider, result

    def test_unrelated_main_change_reconciles_original_pending_draft_without_writes(self):
        provider, result = self.run_case()
        self.assertEqual(result["status"],
                         "ORIGINAL_BOT_DRAFT_STILL_PENDING_AFTER_TARGET_DRIFT")
        self.assertEqual(result["draft_pr"], 47)
        self.assertEqual(result["original_source"], r.EXPECTED_TARGET_HEAD)
        self.assertEqual(result["target_source"], CURRENT)
        self.assertTrue(result["source_documents_unchanged"])
        self.assertEqual(result["provider_writes"], 0)
        self.assertFalse(result["merged"])
        self.assertFalse(result["deployed"])
        self.assertEqual(provider.main_reads, 2)
        self.assertTrue(all(method == "GET" for method, path in provider.calls))
        self.assertLessEqual(len(provider.calls), r.MAX_REQUESTS)

    def test_missing_original_draft_or_document_changed_never_asserts_repair(self):
        for variant in ({"missing_pr": True}, {"changed_doc": True}):
            with self.subTest(variant=variant):
                provider, result = self.run_case(**variant)
                self.assertEqual(result["status"], "TARGET_SOURCE_CHANGED_NO_MUTATION")
                self.assertEqual(result["provider_writes"], 0)
                self.assertTrue(all(x[0] == "GET" for x in provider.calls))

    def test_invalid_original_draft_evidence_never_mutates_or_passes(self):
        for variant in (
            {"wrong_actor": True}, {"wrong_parent": True},
            {"extra_file": True}, {"wrong_base": True},
            {"move_main": True}, {"duplicate_pr": True},
        ):
            with self.subTest(variant=variant):
                provider = DriftProvider(**variant)
                with patch.object(r, "checked_document", side_effect=provider.checked):
                    with self.assertRaises(ValueError):
                        r.execute(provider, installation=r.INSTALLATION,
                                  slug=r.APP_SLUG)
                self.assertTrue(all(method == "GET" for method, path in provider.calls))

    def test_base_override_must_be_git_sha_not_unsigned_hint(self):
        provider = DriftProvider()
        with self.assertRaisesRegex(ValueError, "DRAFT_BASE_SOURCE_INVALID"):
            r.checked_draft(provider, prefix=PREFIX, number=47, branch=BRANCH,
                            branch_sha=CHILD, main_sha=r.EXPECTED_TARGET_HEAD,
                            base_sha="../other")
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
