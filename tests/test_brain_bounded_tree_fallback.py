"""Pinned bounded Git tree discovery after a strict 2MB recursive GET failure.

All GitHub results in this file are synthetic; a PASS proves only bounded
source classification and original SHA checks, never real upstream coverage or
retrospective identification of a 2026-10-10 production failure endpoint.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from brain.__main__ import research
from brain.adapters import GitHub, event
from brain.core import BrainError, Store, utcnow

HEAD="a"*40
ROOT="b"*40
SRC="c"*40
SUB="d"*40
TESTS="e"*40
LIB="f"*40
GIT_SHA=lambda data:hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
CODE=b"def invoice_match(rows):\n    return rows  # freight invoice audit\n"
CODE_SHA=GIT_SHA(CODE)
TEST=b"def test_invoice_match():\n    assert True\n"
TEST_SHA=GIT_SHA(TEST)
NAME="ExampleOrg/oversized-tree"
TARGET={"project":"freight-recovery","query":"freight invoice audit",
        "terms":["freight","invoice","audit"]}


class PinnedProvider:
    def __init__(self, *, damaged_commit=False, bad_root=False,
                 bad_child=False, truncated=False, bad_blob=False,
                 no_code=False, second=False):
        self.calls=[]
        self.damaged_commit=damaged_commit
        self.bad_root=bad_root
        self.bad_child=bad_child
        self.truncated=truncated
        self.bad_blob=bad_blob
        self.no_code=no_code
        self.second=second
    def __call__(self,path):
        self.calls.append(path)
        other="ExampleOrg/verified-small"
        if path.startswith("/search/repositories?"):
            repos=[NAME,other] if self.second else [NAME]
            return {"incomplete_results":False,"items":[
                {"full_name":repo,"default_branch":"main","private":False,
                 "size":2000,"license":{"spdx_id":"MIT"}} for repo in repos
            ]}
        if path=="/repos/"+NAME:
            return {"full_name":NAME,"default_branch":"main",
                    "private":False,"size":2000}
        if path=="/repos/"+NAME+"/branches/main":
            return {"commit":{"sha":HEAD}}
        if path=="/repos/"+NAME+"/git/trees/"+HEAD+"?recursive=1":
            raise BrainError("SOURCE_RESPONSE_TOO_LARGE")
        if path=="/repos/"+NAME+"/git/commits/"+HEAD:
            return {"sha":("9"*40 if self.damaged_commit else HEAD),
                    "tree":{"sha":ROOT}}
        if path=="/repos/"+NAME+"/git/trees/"+ROOT:
            return {"sha":("8"*40 if self.bad_root else ROOT),
                    "truncated":self.truncated,
                    "tree":[
                        {"path":"src","type":"tree","sha":SRC},
                        {"path":"tests","type":"tree","sha":TESTS},
                        {"path":"lib","type":"tree","sha":LIB},
                        {"path":"docs","type":"tree","sha":"1"*40},
                        {"path":"assets","type":"tree","sha":"2"*40},
                        {"path":"frontend","type":"tree","sha":"3"*40},
                        {"path":"vendor","type":"tree","sha":"4"*40},
                    ]}
        if path=="/repos/"+NAME+"/git/trees/"+SRC:
            return {"sha":SRC,"truncated":False,"tree":[
                {"path":"freight","type":"tree","sha":SUB},
            ]}
        if path=="/repos/"+NAME+"/git/trees/"+SUB:
            return {"sha":("7"*40 if self.bad_child else SUB),
                    "truncated":False,
                    "tree":[] if self.no_code else [
                        {"path":"invoice_match.py","type":"blob",
                         "size":len(CODE),"sha":CODE_SHA},
                    ]}
        if path=="/repos/"+NAME+"/git/trees/"+TESTS:
            return {"sha":TESTS,"truncated":False,"tree":[
                {"path":"test_invoice_match.py","type":"blob",
                 "size":len(TEST),"sha":TEST_SHA},
            ]}
        if path=="/repos/"+NAME+"/git/trees/"+LIB:
            return {"sha":LIB,"truncated":False,"tree":[]}
        if path=="/repos/"+NAME+"/git/blobs/"+CODE_SHA:
            return {"encoding":"base64",
                    "sha":("6"*40 if self.bad_blob else CODE_SHA),
                    "content":base64.b64encode(CODE).decode()}
        if path=="/repos/"+other+"/branches/main" and self.second:
            return {"commit":{"sha":HEAD}}
        if path=="/repos/"+other+"/git/trees/"+HEAD+"?recursive=1" and self.second:
            return {"truncated":False,"tree":[{
                "path":"audit.py","type":"blob","sha":CODE_SHA,
                "size":len(CODE),
            }]}
        if path=="/repos/"+other+"/git/blobs/"+CODE_SHA and self.second:
            return {"encoding":"base64","sha":CODE_SHA,
                    "content":base64.b64encode(CODE).decode()}
        raise AssertionError("Unexpected API read: "+path)


class BoundedPinnedTreeTests(unittest.TestCase):
    def test_fallback_inspects_only_four_children_and_verifies_original_source(self):
        provider=PinnedProvider()
        api=GitHub(transport=provider)
        found=api.discover(TARGET)
        self.assertEqual(len(found),1)
        source=found[0][0]
        self.assertEqual(source["repository"],NAME)
        self.assertEqual(source["path"],"src/freight/invoice_match.py")
        self.assertEqual(source["blob_sha"],CODE_SHA)
        self.assertEqual(source["code_sha256"],hashlib.sha256(CODE).hexdigest())
        self.assertEqual(source["test_paths"],["tests/test_invoice_match.py"])
        self.assertEqual(source["matched_terms"],["freight","invoice","audit"])
        self.assertEqual(api.requests,len(provider.calls))
        self.assertLessEqual(api.requests,11)
        self.assertEqual(api.discovery_unavailable,[])
        self.assertEqual(api.discovery_bounded_trees,[{
            "repository":NAME,"head_sha":HEAD,
            "source_path":"src/freight/invoice_match.py",
            "child_trees_inspected":4,
            "scope":"PARTIAL_TREE_ORIGINAL_BLOB_VERIFIED",
        }])
        self.assertEqual(sum("/git/trees/" in v and "recursive" not in v
                             for v in provider.calls),5)
        self.assertFalse(any("/git/trees/"+"4"*40 in v for v in provider.calls))
        self.assertEqual(provider.calls.count(
            "/repos/"+NAME+"/git/commits/"+HEAD),1)

    def test_commit_root_or_child_mismatch_fatal_not_quarantined(self):
        for field in ("damaged_commit","bad_root","bad_child"):
            with self.subTest(field=field):
                provider=PinnedProvider(**{field:True})
                api=GitHub(transport=provider)
                with self.assertRaisesRegex(BrainError,
                                            "BOUNDED_TREE_.*INVALID"):
                    api.discover(TARGET)
                self.assertEqual(api.discovery_unavailable,[])
                self.assertEqual(api.discovery_bounded_trees,[])

    def test_truncated_nonrecursive_tree_remains_fatal(self):
        api=GitHub(transport=PinnedProvider(truncated=True))
        with self.assertRaisesRegex(BrainError,"BOUNDED_TREE_OBJECT_INVALID"):
            api.discover(TARGET)
        self.assertEqual(api.discovery_unavailable,[])

    def test_verified_git_blob_required_even_with_valid_tree(self):
        api=GitHub(transport=PinnedProvider(bad_blob=True))
        with self.assertRaisesRegex(BrainError,"source blob identity invalid"):
            api.discover(TARGET)
        self.assertEqual(api.discovery_unavailable,[])
        self.assertEqual(api.discovery_bounded_trees,[])

    def test_partial_tree_with_no_source_fails_closed(self):
        api=GitHub(transport=PinnedProvider(no_code=True))
        with self.assertRaisesRegex(
            BrainError,
            "DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE:"
            " partial tree no eligible source at tree; verified_candidates=0",
        ):
            api.discover(TARGET)
        self.assertEqual(api.discovery_unavailable,[{
            "repository":NAME,"stage":"tree",
            "reason":"SEARCH_RESULT_BOUNDED_TREE_NO_ELIGIBLE_SOURCE",
        }])
        self.assertEqual(api.discovery_bounded_trees,[])

    def test_one_unverified_partial_can_be_skipped_only_if_another_blob_is_hash_verified(self):
        provider=PinnedProvider(no_code=True,second=True)
        api=GitHub(transport=provider)
        found=api.discover(TARGET)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0][0]["repository"],"ExampleOrg/verified-small")
        self.assertEqual(found[0][0]["code_sha256"],hashlib.sha256(CODE).hexdigest())
        self.assertEqual(len(api.discovery_unavailable),1)
        self.assertEqual(api.discovery_bounded_trees,[])

    def test_request_budget_no_unbounded_fallback(self):
        provider=PinnedProvider()
        api=GitHub(transport=provider)
        api.requests=19
        with self.assertRaisesRegex(BrainError,"REQUEST_BUDGET_EXHAUSTED"):
            api.discover(TARGET)
        self.assertEqual(api.requests,25)
        self.assertLessEqual(len(provider.calls),5)

    def test_empty_discovery_resets_partial_provenance(self):
        provider=PinnedProvider()
        api=GitHub(transport=provider)
        api.discover(TARGET)
        self.assertEqual(len(api.discovery_bounded_trees),1)
        class Empty:
            def __call__(self,path):
                self.calls=getattr(self,"calls",0)+1
                assert path.startswith("/search/repositories?")
                return {"incomplete_results":False,"items":[]}
        api.transport=Empty()
        self.assertEqual(api.discover(TARGET),[])
        self.assertEqual(api.discovery_bounded_trees,[])
        self.assertEqual(api.discovery_unavailable,[])

    def test_research_explicitly_labels_verified_blob_under_partial_tree(self):
        with tempfile.TemporaryDirectory(prefix="brain-bounded-root-") as temp:
            store=Store(Path(temp)/"db.sqlite",visibility="PUBLIC")
            try:
                now=utcnow()
                repository="P00NSMASHER/portfolio-brain"
                store.submit([event("repository",repository,{
                    "repository":repository, "head_sha":HEAD,
                    "default_branch":"main","checks":[],"open_issues":0,
                    "source_ref":"https://github.com/"+repository+"/commit/"+HEAD,
                },HEAD,now=now)],now=now)
                store.drain()
                api=GitHub(transport=PinnedProvider())
                report=research(store,HEAD,Path(temp)/"research",api=api)
                self.assertEqual(report["status"],"PASS")
                self.assertEqual(report["operation"]["result"],
                                 "OBSERVED_WITH_BOUNDED_TREE_COVERAGE")
                self.assertEqual(report["operation"]["candidates_observed"],1)
                self.assertEqual(report["operation"]["bounded_tree_scans"],
                                 api.discovery_bounded_trees)
                self.assertEqual(len(report["reuse_candidates"]),1)
                self.assertEqual(report["reuse_candidates"][0]["blob_sha"],CODE_SHA)
                self.assertFalse(report["learning"]["autonomous_code_execution"])
                self.assertIsNone(report["learning"]["verified_revenue"])
                self.assertEqual(store.pending(),0)
                saved=json.loads((Path(temp)/"research"/"report.json").read_text())
                self.assertEqual(saved["operation"],report["operation"])
            finally:
                store.close()

    def test_optional_only_does_not_change_private_or_explicit_gate(self):
        provider=PinnedProvider()
        for scope in ("explicit","private"):
            with self.subTest(scope=scope):
                api=GitHub(
                    transport=provider,
                    private=(scope=="private")
                )
                if scope=="private":
                    # Private mode requires the separately provided token.
                    import os
                    from unittest.mock import patch
                    with patch.dict(os.environ,{"GITHUB_TOKEN":"fake-token"}):
                        api=GitHub(private=True,transport=PinnedProvider())
                    with self.assertRaisesRegex(
                        BrainError,"SOURCE_RESPONSE_TOO_LARGE"
                    ):
                        api.discover(TARGET)
                    self.assertFalse(api.discovery_bounded_trees)
                else:
                    with self.assertRaisesRegex(
                        BrainError,"SOURCE_RESPONSE_TOO_LARGE"
                    ):
                        api.discover(TARGET,repository=NAME)
                    self.assertFalse(api.discovery_bounded_trees)


if __name__=="__main__":
    unittest.main()
