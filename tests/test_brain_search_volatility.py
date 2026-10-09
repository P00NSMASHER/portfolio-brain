"""GitHub search-index volatility: bounded, transparent, read-only research.

These fixtures simulate HTTP status handling and exact Git blob inspection.
No live provider requests, network calls, branch changes or budget increases.
"""
import base64
import hashlib
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from brain.__main__ import research
from brain.adapters import GitHub, event
from brain.core import BrainError, Store

SHA="a"*40
SOURCE="b"*40
NOW="2026-10-09T18:00:00Z"
BLOB=b"def verify_invoice_freight(rows):\n    return rows  # invoice freight audit\n"
BLOB_SHA=hashlib.sha1(
    b"blob "+str(len(BLOB)).encode()+b"\x00"+BLOB
).hexdigest()
MISSING="ExampleOrg/just-deleted"
GOOD="ExampleOrg/verified-stable"
BAD= "ExampleOrg/unstable"
TARGET={"project":"freight-recovery","query":"freight invoice audit",
        "terms":["invoice","freight","duplicate","audit"]}


def metadata(name, *, private=False):
    return {"full_name":name,"private":private,
            "default_branch":"main","license":{"spdx_id":"MIT"}}


def missing(path):
    raise urllib.error.HTTPError(
        "https://api.github.com"+path,404,"Not Found",{},None
    )


class FakeGitHub:
    """A strict API stub to distinguish search, branch, tree and blob errors."""
    def __init__(self, names=None, *, fail_stage=None, fail_status=404,
                 explicit=False, private_hit=False, search_failure=False):
        self.names=names if names is not None else [MISSING,GOOD]
        self.fail_stage=fail_stage
        self.fail_status=fail_status
        self.explicit=explicit
        self.private_hit=private_hit
        self.search_failure=search_failure
        self.paths=[]

    def __call__(self, path):
        self.paths.append(path)
        if path.startswith("/search/repositories?"):
            if self.search_failure:
                missing(path)
            names=self.names
            return {"incomplete_results":False,"items":[
                metadata(n,private=(self.private_hit and n==MISSING))
                for n in names
            ]}
        if path.startswith("/repos/") and path.endswith("/branches/main"):
            repo=path[len("/repos/"):-len("/branches/main")]
            if (repo==MISSING or repo==BAD) and self.fail_stage=="branch":
                self._fail(path)
            return {"commit":{"sha":SOURCE}}
        if path.startswith("/repos/") and "/git/trees/" in path:
            repo=path[len("/repos/"):].split("/git/trees/",1)[0]
            if (repo==MISSING or repo==BAD) and self.fail_stage=="tree":
                self._fail(path)
            return {"truncated":False,"tree":[
                {"type":"blob","path":"src/invoice_match.py",
                 "sha":BLOB_SHA,"size":len(BLOB)},
                {"type":"blob","path":"tests/test_invoice_match.py",
                 "sha":"c"*40,"size":20},
            ]}
        if path.startswith("/repos/") and "/git/blobs/" in path:
            repo=path[len("/repos/"):].split("/git/blobs/",1)[0]
            if (repo==MISSING or repo==BAD) and self.fail_stage=="blob":
                self._fail(path)
            return {"encoding":"base64","sha":BLOB_SHA,
                    "content":base64.b64encode(BLOB).decode()}
        if path.startswith("/repos/") and path.count("/")==3:
            name=path[len("/repos/"):]
            if name==MISSING and self.explicit:
                self._fail(path)
            return metadata(name)
        raise AssertionError("unexpected provider endpoint: "+path)

    def _fail(self,path):
        if self.fail_status==404:
            missing(path)
        raise urllib.error.HTTPError(
            "https://api.github.com"+path,
            self.fail_status,"provider error",{},None
        )


class StaleSearchResultTests(unittest.TestCase):
    def test_search_hit_branch_404_skipped_when_second_source_is_valid(self):
        transport=FakeGitHub(fail_stage="branch")
        api=GitHub(transport=transport)
        sources=api.discover(TARGET)
        self.assertEqual(len(sources),1)
        payload,private=sources[0]
        self.assertFalse(private)
        self.assertEqual(payload["repository"],GOOD)
        self.assertEqual(payload["blob_sha"],BLOB_SHA)
        self.assertEqual(payload["code_sha256"],hashlib.sha256(BLOB).hexdigest())
        self.assertEqual(payload["test_paths"],["tests/test_invoice_match.py"])
        self.assertEqual(api.discovery_unavailable,[{
            "repository":MISSING,"stage":"branch",
            "reason":"SEARCH_RESULT_SOURCE_404_NOT_INSPECTED",
        }])
        self.assertEqual(api.requests,5)
        self.assertEqual(len(transport.paths),api.requests)
        self.assertTrue(all(path.startswith(("/search/","/repos/")) for
                            path in transport.paths))

    def test_tree_or_blob_404_skips_only_search_derived_hit(self):
        for stage,expected_count in (("tree",6),("blob",7)):
            with self.subTest(stage=stage):
                api=GitHub(transport=FakeGitHub(fail_stage=stage))
                sources=api.discover(TARGET)
                self.assertEqual(len(sources),1)
                self.assertEqual(api.discovery_unavailable[0]["stage"],stage)
                self.assertEqual(api.requests,expected_count)

    def test_all_unavailable_results_still_fail_closed_with_stage_evidence(self):
        for stage in ("branch","tree","blob"):
            with self.subTest(stage=stage):
                api=GitHub(transport=FakeGitHub(
                    names=[MISSING,BAD],fail_stage=stage))
                with self.assertRaisesRegex(
                    BrainError,"DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE.*"+stage
                ):
                    api.discover(TARGET)
                self.assertEqual(len(api.discovery_unavailable),2)

    def test_explicit_requested_repo_404_is_not_skipped(self):
        transport=FakeGitHub(names=[MISSING],fail_stage="branch")
        api=GitHub(transport=transport)
        with self.assertRaisesRegex(BrainError,"SOURCE_API_404"):
            api.discover(TARGET,repository=MISSING)
        self.assertEqual(api.discovery_unavailable,[])
        self.assertTrue(all("/search/" not in x for x in transport.paths))

    def test_search_api_404_is_fatal(self):
        api=GitHub(transport=FakeGitHub(search_failure=True))
        with self.assertRaisesRegex(BrainError,"SOURCE_API_404"):
            api.discover(TARGET)
        self.assertEqual(api.discovery_unavailable,[])

    def test_non404_source_failure_is_not_skipped(self):
        api=GitHub(transport=FakeGitHub(
            fail_stage="branch",fail_status=403))
        with self.assertRaisesRegex(BrainError,"SOURCE_API_403"):
            api.discover(TARGET)
        self.assertEqual(api.discovery_unavailable,[])

    def test_private_search_result_does_not_become_public(self):
        api=GitHub(transport=FakeGitHub(private_hit=True,
                                         fail_stage="branch"))
        with self.assertRaisesRegex(BrainError,"private search result"):
            api.discover(TARGET)
        self.assertEqual(api.discovery_unavailable,[])

    def test_genuinely_empty_search_is_not_an_error(self):
        api=GitHub(transport=FakeGitHub(names=[]))
        self.assertEqual(api.discover(TARGET),[])
        self.assertEqual(api.discovery_unavailable,[])
        self.assertEqual(api.requests,1)

    def test_per_discovery_diagnostics_are_not_reused(self):
        api=GitHub(transport=FakeGitHub(fail_stage="branch"))
        api.discover(TARGET)
        self.assertEqual(len(api.discovery_unavailable),1)
        api.transport=FakeGitHub(names=[GOOD])
        good=api.discover(TARGET)
        self.assertEqual(len(good),1)
        self.assertEqual(api.discovery_unavailable,[])

    def test_research_records_partial_verified_source_without_claiming_completeness(self):
        transport=FakeGitHub(fail_stage="branch")
        api=GitHub(transport=transport)
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/"state.sqlite",visibility="PUBLIC")
            try:
                source_repo="P00NSMASHER/portfolio-brain"
                payload={"repository":source_repo,"head_sha":SHA,
                         "default_branch":"main","checks":[],"open_issues":0,
                         "source_ref":f"https://github.com/{source_repo}/commit/{SHA}"}
                store.submit([event("repository",source_repo,payload,SHA,now=NOW)],
                             now=NOW)
                store.drain()
                import unittest.mock
                from unittest.mock import patch
                with patch("brain.__main__.ROOT",Path(__file__).resolve().parents[1]):
                    result=research(
                        store,SHA,Path(temp)/"output",api=api,
                    )
                self.assertEqual(result["status"],"PASS")
                self.assertEqual(result["operation"]["result"],
                                 "OBSERVED_WITH_SEARCH_RESULT_GAPS")
                self.assertEqual(result["operation"]["candidates_observed"],1)
                self.assertEqual(
                    result["operation"]["unavailable_search_results"][0]["stage"],
                    "branch",
                )
                self.assertEqual(result["state_sequence"],2)
                self.assertEqual(store.pending(),0)
                saved=json.loads((Path(temp)/"output"/"report.json").read_text())
                self.assertEqual(saved["operation"],result["operation"])
                self.assertEqual(result["reuse_candidates"][0]["repository"],GOOD)
                self.assertIsNone(result["learning"]["verified_revenue"])
                self.assertFalse(result["learning"]["autonomous_code_execution"])
                self.assertEqual(store.read_report(SHA)["state_sequence"],2)
            finally:
                store.close()

    def test_research_all_missing_never_claims_success_or_stores_candidate(self):
        api=GitHub(transport=FakeGitHub(
            names=[MISSING,BAD],fail_stage="branch"))
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/"state.sqlite",visibility="PUBLIC")
            try:
                with self.assertRaisesRegex(
                    BrainError,"DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE"
                ):
                    research(store,SHA,Path(temp)/"output",api=api)
                self.assertEqual(store.pending(),0)
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM events").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM attempts").fetchone()[0],
                    0,
                )
            finally:
                store.close()


if __name__=="__main__":
    unittest.main()
