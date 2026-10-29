"""Fail-closed source-bound repair recovery after an original partial App write."""
import urllib.error
import unittest
from unittest.mock import patch

from brain.v8 import repair_runtime as r

CANON=(
    "# CaptureBrief deployment target\n"
    "Use GitHub Pages, not Netlify.\n"
    "- Website branch: " + chr(96) + "gh-pages" + chr(96) + "\n"
    "https://p00nsmasher.github.io/capturebrief/\n"
    "- Product engine and its regression tests: " + chr(96) + "main" + chr(96) + "\n"
)
OLD=(
    "# Verified public release artifact\n\n"
    + r.MISLEADING
    + "## Build and publication are separate\nHistorical package.\n\n"
    + r.HANDOFF_START
    + "Download a Netlify package for a manual deployment to the\n"
    + "existing project's Deploys page.\n"
    + "Do not submit test forms or send notification emails.\n\n"
    + r.HANDOFF_END + "\nPreserve the existing safety and case conditions.\n"
)
FIXED=r.plan(CANON, OLD)
CHILD="33a0b2cd26921935bfca11a0b35e566ad0c735f1"
PREFIX="repos/"+r.TARGET+"/"


class AppPartialRecovery:
    def __init__(self, *, bad_parent=False, bad_bytes=False,
                 extra_file=False, wrong_bot=False, already_pr=False,
                 post_http_error=None):
        self.events=[]
        self.bad_parent=bad_parent
        self.bad_bytes=bad_bytes
        self.extra_file=extra_file
        self.wrong_bot=wrong_bot
        self.already_pr=already_pr
        self.post_http_error=post_http_error

    def get_file(self, obj, label):
        marker=obj.get("fixture")
        if marker=="canonical":
            return CANON,r.EXPECTED_CANONICAL_BLOB
        if marker=="old":
            return OLD,r.EXPECTED_RELEASE_BLOB
        if marker=="repaired":
            if self.bad_bytes:
                return FIXED+"injected-unsafe-line",r.digest_blob(
                    (FIXED+"injected-unsafe-line").encode("utf-8"))
            return FIXED,r.digest_blob(FIXED.encode("utf-8"))
        raise AssertionError((obj,label))

    def __call__(self, method, path, payload=None):
        self.events.append((method,path))
        branch=r.BRANCH_PREFIX+r.EXPECTED_TARGET_HEAD[:12]
        if path=="installation/repositories?per_page=100":
            return {"total_count":1,"repositories":[{"full_name":r.TARGET}]}
        if path=="repos/"+r.TARGET:
            return {"full_name":r.TARGET,"archived":False,
                    "default_branch":"main"}
        if method=="GET" and path==PREFIX+"branches/main":
            return {"commit":{"sha":r.EXPECTED_TARGET_HEAD}}
        if method=="GET" and path==PREFIX+"contents/"+r.CANONICAL+"?ref="+r.EXPECTED_TARGET_HEAD:
            return {"fixture":"canonical"}
        if method=="GET" and path==PREFIX+"contents/"+r.DOC+"?ref="+r.EXPECTED_TARGET_HEAD:
            return {"fixture":"old"}
        if method=="GET" and path==PREFIX+"pulls?state=open&per_page=100":
            if self.already_pr:
                return [{"number":77,"head":{"ref":branch},
                         "base":{"ref":"main"}}]
            return []
        if method=="GET" and path==PREFIX+"branches/"+branch:
            return {"commit":{"sha":CHILD}}
        if method=="GET" and path==PREFIX+"git/commits/"+CHILD:
            return {"sha":CHILD,"parents":[{"sha":"f"*40 if self.bad_parent
                                         else r.EXPECTED_TARGET_HEAD}]}
        if method=="GET" and path==PREFIX+"contents/"+r.DOC+"?ref="+CHILD:
            return {"fixture":"repaired"}
        if method=="GET" and path==PREFIX+"compare/"+r.EXPECTED_TARGET_HEAD+"..."+CHILD:
            rows=[{"filename":r.DOC,"status":"modified"}]
            if self.extra_file:
                rows.append({"filename":".github/workflows/privileged.yml",
                             "status":"added"})
            return {"files":rows,
                    "ahead_by":1,"behind_by":0,
                    "merge_base_commit":{"sha":r.EXPECTED_TARGET_HEAD}}
        if method=="POST" and path==PREFIX+"pulls":
            assert payload["draft"] is True
            assert payload["base"]=="main"
            assert payload["head"]==branch
            assert "AUTO_REPAIR_FINGERPRINT:" in payload["body"]
            if self.post_http_error:
                raise urllib.error.HTTPError(
                    path,self.post_http_error,"blocked",{},None)
            return {"number":77}
        if method=="GET" and path==PREFIX+"pulls/77":
            return {"number":77,"state":"open","draft":True,"merged":False,
                    "head":{"sha":CHILD,"ref":branch,
                            "repo":{"full_name":r.TARGET}},
                    "base":{"sha":r.EXPECTED_TARGET_HEAD,"ref":"main"},
                    "user":{"login":("unauthorized[bot]" if self.wrong_bot else
                                     r.APP_SLUG+"[bot]")}}
        raise AssertionError("UNEXPECTED_TEST_PATH_OR_MUTATION:"+method+":"+path)


class OriginalHalfWrittenBranchTests(unittest.TestCase):
    def execute_case(self, case):
        with patch.object(r,"checked_document",side_effect=case.get_file):
            return r.execute(case,installation=r.INSTALLATION,slug=r.APP_SLUG)

    def test_resume_actual_partial_original_branch_creates_only_one_draft(self):
        case=AppPartialRecovery()
        value=self.execute_case(case)
        self.assertEqual(value["status"],
                         "ORIGINAL_AUTHENTICATED_DRAFT_REPAIR_VERIFIED")
        self.assertEqual(value["repair_commit"],CHILD)
        self.assertEqual(value["draft_pr"],77)
        self.assertTrue(value["resumed_from_verified_existing_branch"])
        self.assertEqual(value["provider_writes"],1)
        self.assertEqual([x for x in case.events if x[0]!="GET"],
                         [("POST",PREFIX+"pulls")])
        self.assertFalse(value["merged"])
        self.assertFalse(value["deployed"])

    def test_repeated_exact_bot_draft_does_not_create_another(self):
        case=AppPartialRecovery(already_pr=True)
        result=self.execute_case(case)
        self.assertEqual(result["provider_writes"],0)
        self.assertEqual(result["draft_pr"],77)
        self.assertEqual([m for m,p in case.events if m!="GET"],[])

    def test_wrong_parent_never_creates_pr_or_changes_document(self):
        case=AppPartialRecovery(bad_parent=True)
        with self.assertRaisesRegex(ValueError,"EXACT_CHILD"):
            self.execute_case(case)
        self.assertEqual([m for m,p in case.events if m!="GET"],[])

    def test_wrong_bytes_do_not_get_automatic_merge_or_pr(self):
        case=AppPartialRecovery(bad_bytes=True)
        with self.assertRaisesRegex(ValueError,"EXISTING_BRANCH_BYTES"):
            self.execute_case(case)
        self.assertEqual([m for m,p in case.events if m!="GET"],[])

    def test_extra_privileged_workflow_file_refuses_source_patch(self):
        case=AppPartialRecovery(extra_file=True)
        with self.assertRaisesRegex(ValueError,"UNAPPROVED_CHANGE"):
            self.execute_case(case)
        self.assertEqual([m for m,p in case.events if m!="GET"],[])

    def test_bogus_bot_identity_cannot_be_counted_as_verified(self):
        case=AppPartialRecovery(already_pr=True,wrong_bot=True)
        with self.assertRaisesRegex(ValueError,"ORIGINAL_BOT_DRAFT"):
            self.execute_case(case)
        self.assertEqual([m for m,p in case.events if m!="GET"],[])

    def test_http_denial_keeps_partial_intent_no_second_doc_write(self):
        case=AppPartialRecovery(post_http_error=403)
        with self.assertRaises(urllib.error.HTTPError):
            self.execute_case(case)
        self.assertEqual([x for x in case.events if x[0]!="GET"],
                         [("POST",PREFIX+"pulls")])

    def test_actual_rest_endpoint_allowlist_remains_repo_and_sha_bound(self):
        provider=r.GitHubAPI("a"*32)
        denied=(
            "repos/"+r.TARGET+"/git/commits/notsha",
            "repos/"+r.TARGET+"/git/commits/"+CHILD+"/attestations",
            "repos/"+r.TARGET+"/contents/.github/workflows/build.yml",
            "repos/"+r.TARGET+"/secrets",
            "repos/P00NSMASHER/portfolio-brain/merges",
        )
        for path in denied:
            with self.subTest(path=path), self.assertRaises(ValueError):
                provider("GET",path)
