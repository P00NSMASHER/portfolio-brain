"""Original negative/positive and privilege-bound regressions for scoped V8 repair."""
import base64
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

from brain.v8 import repair_runtime as r
from brain.v8 import repair_core_origin as origin

CANON = (
    "# CaptureBrief deployment target\n"
    "Use GitHub Pages, not Netlify.\n"
    "- Website branch: " + chr(96) + "gh-pages" + chr(96) + "\n"
    "https://p00nsmasher.github.io/capturebrief/\n"
    "- Product engine and its regression tests: " + chr(96) + "main" + chr(96) + "\n"
)
OLD = (
    "# Verified public release artifact\n\n"
    + r.MISLEADING +
    "## Build and publication are separate\n"
    "This package is historical.\n\n"
    + r.HANDOFF_START +
    "Download an old package for a manual deployment to the\n"
    "existing project's Deploys page. Do not submit test forms or send notification emails.\n\n"
    + r.HANDOFF_END + "\nKeep all other source and fulfillment conditions.\n"
)
SHA = "a" * 40
CORE_ROOT = "/repos/" + origin.REPOSITORY + "/"


def legitimate_core(path, event="workflow_dispatch", original=True):
    if path == CORE_ROOT + "branches/main":
        return {"commit": {"sha": SHA}}
    if path == CORE_ROOT + "actions/runs/17":
        return dict(
            name="brain-cycle-v2", path=".github/workflows/brain-cycle.yml",
            repository={"full_name": origin.REPOSITORY}, head_branch="main",
            head_sha=SHA, run_attempt=1, status="completed",
            conclusion="success", event=event)
    if path == CORE_ROOT + "actions/runs/17/jobs?per_page=100":
        steps = list(origin.MANDATORY) + (
            ["Verify independently signed Cloudflare Cron provenance"]
            if original else [])
        return {"total_count": 1, "jobs": [{
            "name": "monitor", "status": "completed", "conclusion": "success",
            "steps": [{"name": n, "conclusion": "success"} for n in steps]
        }]}
    raise AssertionError(path)


class OriginalCoreAdmission(unittest.TestCase):
    def test_real_signed_dispatch_and_native_schedule_are_admitted(self):
        p = origin.admit(legitimate_core, SHA, "17")
        self.assertEqual(p["status"], "ORIGINAL_AUTOMATIC_CORE_AUTHENTICATED")
        self.assertFalse(p["writer_token_issued"])
        p = origin.admit(lambda path: legitimate_core(path, event="schedule", original=False),
                         SHA, "17")
        self.assertEqual(p["run_id"], "17")

    def test_manual_push_changed_sha_and_missing_original_job_are_denied(self):
        for event, original_success in (
            ("push", True), ("workflow_dispatch", False),
            ("pull_request", True)):
            with self.subTest(event=event), self.assertRaises(ValueError):
                origin.admit(lambda path: legitimate_core(
                    path, event=event, original=original_success), SHA, "17")
        for bad in ("bad_sha", "b" * 40, True):
            with self.subTest(source=bad), self.assertRaises(ValueError):
                origin.admit(legitimate_core, bad, "17")
        with self.assertRaises(ValueError):
            origin.admit(legitimate_core, SHA, "../17")


class CaptureBriefScopeTests(unittest.TestCase):
    def test_original_deployment_error_reproduced_then_corrected(self):
        after = r.plan(CANON, OLD)
        self.assertIn("Current GitHub Pages release handoff", after)
        self.assertNotIn(r.MISLEADING, after)
        self.assertEqual(after.split(r.HANDOFF_END, 1)[1],
                         OLD.split(r.HANDOFF_END, 1)[1])
        self.assertIn(r.CORRECTION, after)
        self.assertEqual(r.plan(CANON, after), None)

    def test_malformed_or_unauthorized_source_does_not_get_patch(self):
        samples = (
            ("Migrate to Netlify", OLD),
            (CANON, OLD.replace(r.MISLEADING, "")),
            (CANON, OLD + r.MISLEADING),
            (CANON, OLD.replace(r.HANDOFF_START, "## Edited site handoff\n\n")),
            (CANON, OLD.replace("Do not submit test forms or send notification emails",
                                "Automatically submit test forms")),
            (CANON, OLD.replace("existing project's Deploys page", "attacker site")),
            (CANON, OLD + r.CORRECTION),
        )
        for source, doc in samples:
            with self.subTest(doc=doc[:45]), self.assertRaises(ValueError):
                r.plan(source, doc)

    def test_original_blob_bytes_and_one_repository_scope_are_required(self):
        content = b"original public documentation\n"
        sha = r.digest_blob(content)
        good = {"type": "file", "encoding": "base64", "size": len(content),
                "sha": sha, "content": base64.b64encode(content).decode()}
        self.assertEqual(r.checked_document(good, "TEST")[1], sha)
        with self.assertRaises(ValueError):
            r.checked_document(dict(good, sha="0"*40), "TEST")
        r.check_scope({"total_count": 1, "repositories": [
            {"full_name": r.TARGET}]}, r.INSTALLATION, r.APP_SLUG)
        for inventory in (
            {"total_count": 2, "repositories": [{"full_name": r.TARGET}]},
            {"total_count": True, "repositories": [{"full_name": r.TARGET}]},
            {"total_count": 1, "repositories": [{"full_name": "P00NSMASHER/other"}]},
            {"total_count": 1, "repositories": []},
        ):
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                r.check_scope(inventory, r.INSTALLATION, r.APP_SLUG)

    def test_provider_never_touches_other_repo_workflow_or_merge(self):
        p = r.GitHubAPI("a"*32)
        invalid = (
            ("GET", "repos/P00NSMASHER/other/contents/README.md"),
            ("PUT", "repos/"+r.TARGET+"/contents/.github/workflows/release.yml"),
            ("POST", "repos/"+r.TARGET+"/merges"),
            ("DELETE", "repos/"+r.TARGET+"/git/refs/heads/main"),
            ("GET", "repos/"+r.TARGET+"/actions/secrets"),
            ("GET", "repos/"+r.TARGET+"/contents/other-file?ref="+SHA),
        )
        for method, path in invalid:
            with self.subTest(method=method, path=path), self.assertRaises(ValueError):
                p(method, path, {} if method in {"PUT","POST"} else None)
        with self.assertRaises(ValueError):
            r.NoRedirect().redirect_request(None,None,302,"",{},
                                            "https://attacker.example/")

    def test_original_source_drifts_never_create_a_branch(self):
        calls=[]
        def api(method,path,payload=None):
            calls.append((method,path))
            if path == "installation/repositories?per_page=100":
                return {"total_count":1,"repositories":[{"full_name":r.TARGET}]}
            if path == "repos/"+r.TARGET:
                return {"full_name":r.TARGET,"archived":False,
                        "default_branch":"main"}
            if path.endswith("branches/main"):
                return {"commit":{"sha":"f"*40}}
            raise AssertionError(path)
        actual=r.execute(api,installation=r.INSTALLATION,slug=r.APP_SLUG)
        self.assertEqual(actual["status"],"TARGET_SOURCE_CHANGED_NO_MUTATION")
        self.assertEqual(actual["provider_writes"],0)
        self.assertTrue(all(method=="GET" for method,path in calls))

    def test_realistic_provider_draft_write_never_merges_or_deploys(self):
        calls=[]
        raw_doc=None
        fixed=r.plan(CANON,OLD)
        branch=r.BRANCH_PREFIX+r.EXPECTED_TARGET_HEAD[:12]
        repaired_sha="b"*40

        def api(method,path,payload=None):
            nonlocal raw_doc
            calls.append((method,path))
            if path=="installation/repositories?per_page=100":
                return {"total_count":1,"repositories":[{"full_name":r.TARGET}]}
            prefix="repos/"+r.TARGET+"/"
            if path=="repos/"+r.TARGET:
                return {"full_name":r.TARGET,"archived":False,"default_branch":"main"}
            if method=="GET" and path==prefix+"branches/main":
                return {"commit":{"sha":r.EXPECTED_TARGET_HEAD}}
            if method=="GET" and path.endswith("contents/"+r.CANONICAL+"?ref="+r.EXPECTED_TARGET_HEAD):
                return {"fixture": "canonical"}
            if method=="GET" and path.endswith("contents/"+r.DOC+"?ref="+r.EXPECTED_TARGET_HEAD):
                return {"fixture": "old"}
            if path==prefix+"pulls?state=open&per_page=100":
                return []
            if path==prefix+"branches/"+branch:
                raise urllib.error.HTTPError(path,404,"Not Found",{},None)
            if method=="POST" and path==prefix+"git/refs":
                self.assertEqual(payload["sha"],r.EXPECTED_TARGET_HEAD)
                self.assertEqual(payload["ref"],"refs/heads/"+branch)
                return {"ref":payload["ref"],"object":{"sha":r.EXPECTED_TARGET_HEAD}}
            if method=="PUT" and path==prefix+"contents/"+r.DOC:
                raw_doc=base64.b64decode(payload["content"])
                self.assertEqual(raw_doc.decode(),fixed)
                self.assertEqual(payload["sha"],r.EXPECTED_RELEASE_BLOB)
                return {"commit":{"sha":repaired_sha},
                        "content":{"sha":r.digest_blob(raw_doc)}}
            if method=="GET" and path==prefix+"git/commits/"+repaired_sha:
                return {"sha":repaired_sha,
                        "parents":[{"sha":r.EXPECTED_TARGET_HEAD}]}
            if method=="GET" and path==prefix+"contents/"+r.DOC+"?ref="+repaired_sha:
                return {"fixture": "after"}
            if method=="GET" and path==prefix+"compare/"+r.EXPECTED_TARGET_HEAD+"..."+repaired_sha:
                return {"files":[{"filename":r.DOC,"status":"modified"}],
                        "merge_base_commit":{"sha":r.EXPECTED_TARGET_HEAD},
                        "ahead_by":1,"behind_by":0}
            if method=="POST" and path==prefix+"pulls":
                self.assertTrue(payload["draft"])
                self.assertEqual(payload["base"],"main")
                return {"number":123}
            if method=="GET" and path==prefix+"pulls/123":
                return {"number":123,"state":"open","draft":True,"merged":False,
                        "head":{"sha":repaired_sha,"ref":branch,
                                "repo":{"full_name":r.TARGET}},
                        "base":{"sha":r.EXPECTED_TARGET_HEAD,"ref":"main"},
                        "user":{"login":r.APP_SLUG+"[bot]"}}
            raise AssertionError((method,path))

        def checked(obj,label):
            if obj.get("fixture")=="canonical":
                return CANON,r.EXPECTED_CANONICAL_BLOB
            if obj.get("fixture")=="old":
                return OLD,r.EXPECTED_RELEASE_BLOB
            if obj.get("fixture")=="after":
                return fixed,r.digest_blob(fixed.encode())
            raise AssertionError(obj)
        with patch.object(r,"checked_document",side_effect=checked):
            result=r.execute(api,installation=r.INSTALLATION,slug=r.APP_SLUG)
        self.assertEqual(result["draft_pr"],123)
        self.assertEqual(result["provider_writes"],3)
        self.assertFalse(result["merged"])
        self.assertFalse(result["deployed"])
        self.assertEqual(sum(method!="GET" for method,path in calls),3)
        self.assertNotIn("merges",[path for method,path in calls])

    def test_main_owned_workflow_pinned_and_not_new_schedule(self):
        wf=Path(".github/workflows/v8-scoped-repair.yml").read_text()
        for file in ("brain/v8/repair_runtime.py",
                     "brain/v8/repair_core_origin.py"):
            content=Path(file).read_bytes()
            sha=hashlib.sha1(
                b"blob "+str(len(content)).encode()+b"\x00"+content).hexdigest()
            self.assertIn(sha,wf)
        self.assertIn("workflow_run:",wf)
        self.assertIn("types: [completed]",wf)
        self.assertIn("github.event.workflow_run.conclusion == 'success'",wf)
        self.assertIn("persist-credentials: false",wf)
        self.assertIn("python -I",wf)
        self.assertIn("repositories: capturebrief",wf)
        self.assertIn("permission-contents: write",wf)
        self.assertIn("permission-pull-requests: write",wf)
        self.assertIn("skip-token-revoke: false",wf)
        self.assertNotIn("permission-workflows:",wf)
        for forbidden in ("schedule:", "workflow_dispatch:", "pull_request_target:"):
            self.assertNotIn(forbidden,wf)
