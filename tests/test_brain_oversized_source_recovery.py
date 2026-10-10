"""Fail-closed, size-bounded optional public source recovery.

All transport responses are synthetic; original 2026-10-10 failures proved
SOURCE_RESPONSE_TOO_LARGE in research, not which GitHub endpoint supplied it.
Do not infer a historic endpoint, raise the 2 MB cap, retry arbitrary sources,
give private source data public status, or call an optional gap complete.
"""
from __future__ import annotations

import base64
from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from brain.adapters import GitHub, event
from brain.core import BrainError, Store, utcnow
from brain.__main__ import research

SOURCE = "a"*40
BLOB = b"def freight_invoice_audit(rows):\n    return rows  # verified freight invoice audit\n"
BLOB_SHA = hashlib.sha1(
    b"blob " + str(len(BLOB)).encode() + b"\x00" + BLOB
).hexdigest()
OVERSIZED="ExampleOrg/VeryLargePublicSearchHit"
INSPECTED="ExampleOrg/InspectedSmallPublic"
TARGET={
    "project":"freight-recovery",
    "query":"freight invoice audit",
    "terms":["freight","invoice","audit"],
}


def metadata(name, *, private=False):
    return {
        "full_name":name, "private":private, "size":930,
        "default_branch":"main", "license":{"spdx_id":"MIT"},
    }


class SourceTransport:
    """Only declared GETs are available; no network, token or branch mutation."""
    def __init__(self, *, stage="tree", both=False, private=False,
                 damaged_blob=False):
        self.stage=stage
        self.both=both
        self.private=private
        self.damaged_blob=damaged_blob
        self.calls=[]

    def __call__(self,path):
        self.calls.append(path)
        selected={OVERSIZED} | ({INSPECTED} if self.both else set())
        if path.startswith("/search/repositories?"):
            if self.stage=="search":
                raise BrainError("SOURCE_RESPONSE_TOO_LARGE")
            return {"incomplete_results":False, "items":[
                metadata(OVERSIZED,private=self.private),
                metadata(INSPECTED,private=self.private),
            ]}
        for name in (OVERSIZED,INSPECTED):
            if path=="/repos/"+name:
                return metadata(name,private=self.private)
            if path=="/repos/"+name+"/branches/main":
                if self.stage=="branch" and name in selected:
                    raise BrainError("SOURCE_RESPONSE_TOO_LARGE")
                return {"commit":{"sha":SOURCE}}
            if path=="/repos/"+name+"/git/trees/"+SOURCE+"?recursive=1":
                if self.stage=="tree" and name in selected:
                    raise BrainError("SOURCE_RESPONSE_TOO_LARGE")
                return {
                    "truncated":False,
                    "tree":[{
                        "type":"blob", "path":"src/freight_invoice_audit.py",
                        "size":len(BLOB), "sha":BLOB_SHA,
                    }],
                }
            if path=="/repos/"+name+"/git/blobs/"+BLOB_SHA:
                if self.stage=="blob" and name in selected:
                    raise BrainError("SOURCE_RESPONSE_TOO_LARGE")
                return {
                    "encoding":"base64",
                    "sha":("f"*40 if self.damaged_blob and name==INSPECTED
                           else BLOB_SHA),
                    "content":base64.b64encode(BLOB).decode(),
                }
        raise AssertionError("Unexpected GitHub endpoint (not an allowed read family)")


class ByteResponse:
    def __init__(self,raw):
        self.raw=raw
        self.calls=0
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def read(self,n):
        assert n==2_000_001, "Original strict response byte limit changed"
        self.calls+=1
        return self.raw[:n]


class ByteOpener:
    def __init__(self,raw):
        self.response=ByteResponse(raw)
    def open(self,request,timeout):
        assert request.full_url.startswith("https://api.github.com/")
        assert request.get_method()=="GET"
        assert timeout==10, "Original timeout budget changed"
        return self.response


class OversizedSourceRecoveryTests(unittest.TestCase):
    def test_oversized_actual_read_retains_limit_and_redacts_url_token(self):
        marker="PRIVATE-REPO-AND-TOKEN-DO-NOT-EXPOSE"
        data=b"{" + b"x"*2_000_000
        with patch.dict(os.environ,{"GITHUB_TOKEN":marker}):
            api=GitHub()
        opener=ByteOpener(data)
        api.opener=opener
        output=io.StringIO()
        with redirect_stderr(output):
            with self.assertRaisesRegex(BrainError,"^SOURCE_RESPONSE_TOO_LARGE$"):
                api.get("/repos/"+marker+"/project/git/trees/" + SOURCE +
                        "?recursive=1")
        rows=output.getvalue().splitlines()
        self.assertEqual(len(rows),1)
        receipt=json.loads(rows[0])
        self.assertEqual(receipt,{
            "event":"SOURCE_API_GET_FAILURE_CONTEXT",
            "read_failure":"ResponseTooLarge",
            "request_family":"GIT_TREE",
            "request_number":1,
        })
        self.assertNotIn(marker,output.getvalue())
        self.assertNotIn("https",output.getvalue())
        self.assertEqual(api.requests,1)
        self.assertEqual(opener.response.calls,1)

    def test_exact_two_megabytes_is_still_allowed_without_diagnostic(self):
        api=GitHub()
        opener=ByteOpener(b"{}"+b" "*(2_000_000-2))
        api.opener=opener
        stderr=io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(api.get("/repos/ExampleOrg/repo"),{})
        self.assertEqual(api.requests,1)
        self.assertEqual(stderr.getvalue(),"")
        self.assertEqual(opener.response.calls,1)

    def test_oversized_tree_with_verified_alternate_is_partial_not_complete(self):
        transport=SourceTransport(stage="tree")
        api=GitHub(transport=transport)
        found=api.discover(TARGET)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0][0]["repository"],INSPECTED)
        self.assertEqual(found[0][0]["blob_sha"],BLOB_SHA)
        self.assertEqual(found[0][0]["code_sha256"],
                         hashlib.sha256(BLOB).hexdigest())
        self.assertFalse(found[0][1])
        self.assertEqual(api.discovery_unavailable,[{
            "repository":OVERSIZED,
            "stage":"tree",
            "reason":"SEARCH_RESULT_RESPONSE_TOO_LARGE_NOT_INSPECTED",
        }])
        self.assertEqual(api.requests,6)
        self.assertEqual(len(transport.calls),6)

    def test_oversized_blob_with_verified_alternate_is_partial(self):
        transport=SourceTransport(stage="blob")
        api=GitHub(transport=transport)
        found=api.discover(TARGET)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0][0]["repository"],INSPECTED)
        self.assertEqual(api.discovery_unavailable[0]["stage"],"blob")
        self.assertEqual(api.requests,7)
        self.assertEqual(len(transport.calls),7)

    def test_two_oversized_candidates_have_no_verified_source_or_success(self):
        for stage in ("tree","blob"):
            with self.subTest(stage=stage):
                transport=SourceTransport(stage=stage,both=True)
                api=GitHub(transport=transport)
                with self.assertRaisesRegex(
                    BrainError,
                    "DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE:"
                    " provider size bound at "+stage+"; verified_candidates=0",
                ):
                    api.discover(TARGET)
                self.assertEqual(len(api.discovery_unavailable),2)
                self.assertEqual(api.requests,len(transport.calls))

    def test_explicit_repository_never_suppresses_oversized_source(self):
        for stage in ("tree","blob"):
            with self.subTest(stage=stage):
                transport=SourceTransport(stage=stage)
                api=GitHub(transport=transport)
                with self.assertRaisesRegex(BrainError,"SOURCE_RESPONSE_TOO_LARGE"):
                    api.discover(TARGET,repository=OVERSIZED)
                self.assertEqual(api.discovery_unavailable,[])
                self.assertNotIn("/search/repositories", " ".join(transport.calls))

    def test_private_search_never_suppresses_oversized_source(self):
        for stage in ("tree","blob"):
            with self.subTest(stage=stage):
                with patch.dict(os.environ,{"GITHUB_TOKEN":"fake-private-test-token"}):
                    api=GitHub(private=True,transport=SourceTransport(
                        stage=stage,private=True
                    ))
                with self.assertRaisesRegex(BrainError,"SOURCE_RESPONSE_TOO_LARGE"):
                    api.discover(TARGET)
                self.assertEqual(api.discovery_unavailable,[])

    def test_search_api_and_branch_overflow_still_fail(self):
        for stage in ("search","branch"):
            with self.subTest(stage=stage):
                api=GitHub(transport=SourceTransport(stage=stage))
                with self.assertRaisesRegex(BrainError,"SOURCE_RESPONSE_TOO_LARGE"):
                    api.discover(TARGET)
                self.assertEqual(api.discovery_unavailable,[])

    def test_unverified_backup_blob_integrity_remains_fatal(self):
        api=GitHub(transport=SourceTransport(
            stage="tree",damaged_blob=True
        ))
        with self.assertRaisesRegex(BrainError,"source blob identity invalid"):
            api.discover(TARGET)
        self.assertEqual(len(api.discovery_unavailable),1)

    def test_one_oversized_optional_hit_cannot_skip_request_budget(self):
        api=GitHub(transport=SourceTransport(stage="tree"))
        api.requests=23
        with self.assertRaisesRegex(BrainError,"REQUEST_BUDGET_EXHAUSTED"):
            api.discover(TARGET)
        self.assertEqual(api.requests,25)

    def test_diagnostics_clear_after_next_independent_discovery(self):
        api=GitHub(transport=SourceTransport(stage="tree"))
        api.discover(TARGET)
        self.assertEqual(len(api.discovery_unavailable),1)
        api.transport=SourceTransport(stage="none")
        records=api.discover(TARGET)
        self.assertEqual(len(records),2)
        self.assertEqual(api.discovery_unavailable,[])

    def test_research_persists_only_inspected_source_and_explicit_gap(self):
        with tempfile.TemporaryDirectory(prefix="brain-oversize-evidence-") as tmp:
            root=Path(tmp)
            store=Store(root/"state.sqlite",visibility="PUBLIC")
            try:
                original_repo="P00NSMASHER/portfolio-brain"
                current_time=utcnow()
                payload={
                    "repository":original_repo, "head_sha":SOURCE,
                    "default_branch":"main", "checks":[], "open_issues":0,
                    "source_ref":
                        "https://github.com/"+original_repo+"/commit/"+SOURCE,
                }
                store.submit([
                    event("repository",original_repo,payload,SOURCE,
                          now=current_time)
                ],now=current_time)
                store.drain()
                api=GitHub(transport=SourceTransport(stage="tree"))
                report=research(store,SOURCE,root/"report",api=api)
                self.assertEqual(report["status"],"PASS")
                self.assertEqual(
                    report["operation"]["result"],
                    "OBSERVED_WITH_SEARCH_RESULT_GAPS",
                )
                self.assertEqual(report["operation"]["candidates_observed"],1)
                self.assertEqual(report["operation"]["unavailable_search_results"],[
                    {"repository":OVERSIZED,"stage":"tree",
                     "reason":"SEARCH_RESULT_RESPONSE_TOO_LARGE_NOT_INSPECTED"}
                ])
                self.assertEqual(len(report["reuse_candidates"]),1)
                self.assertEqual(report["reuse_candidates"][0]["repository"],INSPECTED)
                self.assertEqual(store.pending(),0)
                self.assertEqual(
                    json.loads((root/"report"/"report.json").read_text())
                    ["operation"]["result"],
                    "OBSERVED_WITH_SEARCH_RESULT_GAPS"
                )
            finally:
                store.close()

    def test_zero_verified_source_does_not_record_a_research_pass(self):
        with tempfile.TemporaryDirectory(prefix="brain-oversize-negative-") as tmp:
            store=Store(Path(tmp)/"state.sqlite",visibility="PUBLIC")
            try:
                api=GitHub(transport=SourceTransport(stage="tree",both=True))
                with self.assertRaisesRegex(
                    BrainError, "DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE"
                ):
                    research(store,SOURCE,Path(tmp)/"report",api=api)
                self.assertEqual(store.pending(),0)
                self.assertEqual(
                    store.db.execute(
                        "select count(*) from attempts where operation='research'"
                    ).fetchone()[0],0
                )
            finally:
                store.close()


if __name__=="__main__":
    unittest.main()
