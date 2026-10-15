"""Production double-404 research cannot pin all future cycles to one target.

All GitHub responses are synthetic. Original failed source observations stay
unverified; only an independent hash-inspected alternate becomes canonical.
"""
import base64
import hashlib
import io
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from brain.__main__ import research
from brain.adapters import GitHub
from brain.core import BrainError, Store
from brain.adapters import policy

SHA = "a"*40
HEAD = "b"*40
CODE = b"def payment_verify_settle():\n    return 'verified source, not commercial value'\n"
OID = hashlib.sha1(b"blob "+str(len(CODE)).encode()+b"\0"+CODE).hexdigest()
BAD = ("ExampleOrg/deleted-first", "ExampleOrg/deleted-second")
GOOD = "ExampleOrg/real-verified-source"


class SearchFixture:
    def __init__(self, *, alternate="source", first_size=0):
        self.alternate = alternate
        self.first_size = first_size
        self.paths = []

    @staticmethod
    def hit(repo, size):
        return {"full_name":repo,"private":False,"size":size,
                "default_branch":"main","license":{"spdx_id":"MIT"}}

    def __call__(self, path):
        self.paths.append(path)
        if path.startswith("/search/repositories?"):
            if "freight%20invoice%20audit" in path:
                return {"incomplete_results":False,
                        "items":[self.hit(name,self.first_size) for name in BAD]}
            if self.alternate == "missing":
                return {"incomplete_results":False,
                        "items":[self.hit(name,0) for name in BAD]}
            if self.alternate == "no_matches":
                return {"incomplete_results":False,"items":[]}
            if (self.alternate == "second_empty_third_source"
                    and "x402%20python" in path):
                return {"incomplete_results":False,"items":[]}
            return {"incomplete_results":False,"items":[self.hit(GOOD,42)]}
        if any(path == f"/repos/{name}/branches/main" for name in BAD):
            raise urllib.error.HTTPError("https://api.github.com/"+path,404,
                                         "Not Found",{},None)
        if path == f"/repos/{GOOD}/branches/main":
            return {"commit":{"sha":HEAD}}
        if path == f"/repos/{GOOD}/git/trees/{HEAD}?recursive=1":
            return {"truncated":False,"tree":[
                {"type":"blob","path":"src/payment_verify.py",
                 "sha":OID,"size":len(CODE)},
                {"type":"blob","path":"tests/test_payment_verify.py",
                 "sha":"c"*40,"size":40}
            ]}
        if path == f"/repos/{GOOD}/git/blobs/{OID}":
            return {"sha":OID,"encoding":"base64",
                    "content":base64.b64encode(CODE).decode()}
        if path == "/repos/ExampleOrg/deleted-first":
            return self.hit(BAD[0],0)
        raise AssertionError("Unexpected external GitHub read: "+path)


class ResearchRecoveredOnlyByRealSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/"state.sqlite",visibility="PUBLIC")
        self.addCleanup(self.store.close)
        self.output = Path(self.tmp.name)/"research"

    def test_two_vanished_public_sources_then_real_hash_verified_alternative(self):
        transport=SearchFixture()
        api=GitHub(transport=transport)
        with redirect_stderr(io.StringIO()):
            result=research(self.store,SHA,self.output,api=api)
        operation=result["operation"]
        self.assertEqual(operation["original_target"],"freight-recovery")
        self.assertEqual(operation["target"],"agent-products")
        self.assertEqual(operation["result"],"VERIFIED_ALTERNATE_SOURCE_AFTER_SEARCH_FAILURE")
        self.assertEqual(operation["requests"],7)
        self.assertEqual(operation["candidates_observed"],1)
        self.assertEqual(operation["prior_unavailable_targets"][0]["get_requests"],3)
        self.assertEqual(len(operation["prior_unavailable_targets"][0]["source_gaps"]),2)
        self.assertEqual(self.store.pending(),0)
        events,seq,chain=self.store._verified_events()
        self.assertEqual(seq,1)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["payload"]["repository"],GOOD)
        self.assertEqual(events[0]["payload"]["target"],"agent-products")
        self.assertEqual(events[0]["payload"]["code_sha256"],hashlib.sha256(CODE).hexdigest())
        self.assertFalse(any(e["payload"]["repository"] in BAD for e in events))
        attempt=self.store.db.execute(
            "SELECT status,details FROM attempts WHERE operation='research'"
        ).fetchone()
        self.assertEqual(attempt["status"],"PASS")
        self.assertIn('"fallback_used":true',attempt["details"])
        self.assertIsNone(result["learning"]["verified_revenue"])
        self.assertFalse(result["learning"]["autonomous_code_execution"])
        self.assertEqual(len(transport.paths),7)

    def test_all_alternatives_uninspectable_still_fails_without_state_write(self):
        transport=SearchFixture(alternate="missing")
        api=GitHub(transport=transport)
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(BrainError,"DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE"):
                research(self.store,SHA,self.output,api=api)
        self.assertEqual(self.store.pending(),0)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0],0)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM attempts").fetchone()[0],0)
        self.assertLessEqual(api.requests,24)
        self.assertEqual(sum(path.startswith("/search/repositories?") for path in transport.paths),3)

    def test_second_domain_empty_but_third_real_hash_verified_source_succeeds(self):
        transport=SearchFixture(alternate="second_empty_third_source")
        api=GitHub(transport=transport)
        with redirect_stderr(io.StringIO()):
            report=research(self.store,SHA,self.output,api=api)
        self.assertEqual(report["operation"]["target"],"school-tools")
        self.assertEqual(report["operation"]["original_target"],"freight-recovery")
        self.assertEqual(report["operation"]["result"],
                         "VERIFIED_ALTERNATE_SOURCE_AFTER_SEARCH_FAILURE")
        self.assertEqual(report["operation"]["requests"],8)
        self.assertEqual(report["operation"]["candidates_observed"],1)
        self.assertEqual(
            [x["classification"] for x in report["operation"]["prior_unavailable_targets"]],
            ["PUBLIC_SEARCH_RESULTS_UNINSPECTABLE",
             "ALTERNATE_SEARCH_NO_SOURCE_INSPECTED"],
        )
        self.assertEqual(self.store.db.execute(
            "SELECT count(*) FROM events").fetchone()[0],1)
        self.assertEqual(len(transport.paths),8)

    def test_nonempty_index_branch_404_still_fatal_and_does_not_try_other_domain(self):
        transport=SearchFixture(first_size=100)
        api=GitHub(transport=transport)
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(BrainError,"SOURCE_API_404"):
                research(self.store,SHA,self.output,api=api)
        self.assertEqual(len(transport.paths),2)
        self.assertEqual(self.store.pending(),0)

    def test_true_empty_original_search_is_still_original_no_matches(self):
        class Empty:
            def __init__(self):self.paths=[]
            def __call__(self,path):
                self.paths.append(path)
                return {"incomplete_results":False,"items":[]}
        transport=Empty()
        report=research(self.store,SHA,self.output,api=GitHub(transport=transport))
        self.assertEqual(report["operation"]["result"],"NO_MATCHES")
        self.assertEqual(report["operation"]["target"],"freight-recovery")
        self.assertEqual(report["operation"]["prior_unavailable_targets"],[])
        self.assertEqual(report["operation"]["requests"],1)
        self.assertEqual(len(transport.paths),1)

    def test_empty_alternates_cannot_launder_primary_source_failure(self):
        transport=SearchFixture(alternate="no_matches")
        api=GitHub(transport=transport)
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(
                BrainError,"DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE"
            ):
                research(self.store,SHA,self.output,api=api)
        self.assertEqual(self.store.db.execute(
            "SELECT count(*) FROM events").fetchone()[0],0)
        self.assertEqual(self.store.db.execute(
            "SELECT count(*) FROM attempts").fetchone()[0],0)
        self.assertEqual(api.requests,5)
        self.assertEqual(sum(p.startswith("/search/repositories?")
                             for p in transport.paths),3)

    def test_low_get_budget_preserves_original_failure_without_extra_provider_call(self):
        transport=SearchFixture()
        api=GitHub(transport=transport)
        api.requests=20
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(BrainError,"DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE"):
                research(self.store,SHA,self.output,api=api)
        self.assertEqual(api.requests,23)
        self.assertEqual(len(transport.paths),3)
        self.assertEqual(sum(p.startswith("/search/repositories?") for p in transport.paths),1)

    def test_explicit_requested_repo_cannot_be_replaced_by_alternate(self):
        transport=SearchFixture()
        api=GitHub(transport=transport)
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(BrainError,"SOURCE_API_404"):
                research(self.store,SHA,self.output,api=api,repository=BAD[0])
        self.assertEqual(len(transport.paths),2)
        self.assertEqual(self.store.pending(),0)

    def test_private_mode_cannot_use_public_search_fallback(self):
        private_store=Store(Path(self.tmp.name)/"private.sqlite",visibility="PRIVATE")
        self.addCleanup(private_store.close)
        transport=SearchFixture()
        with patch.dict("os.environ",{"GITHUB_TOKEN":"existing-fixture-token"}):
            api=GitHub(private=True,transport=transport)
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(BrainError,"SOURCE_API_404"):
                research(private_store,SHA,self.output,api=api)
        self.assertEqual(len(transport.paths),2)
        self.assertEqual(private_store.pending(),0)


if __name__=="__main__":
    unittest.main()
