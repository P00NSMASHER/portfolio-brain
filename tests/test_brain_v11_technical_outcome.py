"""Actual Git-source-backed regression for short-window engineering outcomes."""
import base64
import copy
import json
import unittest

from brain.v11 import technical_outcome as tech
from tests.test_brain_v11_results import MAIN as UNUSED_TEST_SHA

SHA="c1da4cd8cd6bf0067a1e5a3cf14d7fb4859a9dd8"
MERGE="dbd548034c6002009098c1cab9bee3aa65a64bdb"
OLD="00af34b4a128f7d59f9d35b8ad544ec9ff32d472"
BEFORE=["05ab80db2bf1d66c4f4e09923f5ca3388ba88c7d",
        "4e7bec5fc476c79f2ead74b6e021799de9c234cc"]
AFTER=["9c06fad17d8ca49c7e4a883252fb52fef01a8a6e",
       "75ad3036fc90b5ed6189c6203f7a71c0cdd1dd53"]
VALUES=[(104345600,13908574,"2026-11-05T12:22:56Z",OLD),
        (105545728,14046648,"2026-11-05T16:22:25Z",OLD),
        (105541632,14049130,"2026-11-05T16:28:09Z",MERGE),
        (105517056,14050636,"2026-11-05T17:03:09Z",MERGE)]
CASE={"schema_version":1,"kind":"OPERATOR_REQUESTED_STORAGE_REPAIR",
      "source_pr":865,"candidate_sha":SHA,"merge_sha":MERGE,
      "before":BEFORE,"after":AFTER}

class Provider:
    def __init__(self):
        self.reads=0
        self.forged_check=False
        self.moved_source=False
        self.duplicate=False
        self.missing=False

    def get(self,route):
        self.reads+=1
        if route=="pulls/865":
            return {"number":865,"state":"closed","merged":True,"merged_at":"2026-11-05T16:25:12Z",
                    "head":{"sha":SHA},"merge_commit_sha":MERGE,
                    "base":{"ref":"main","repo":{"full_name":tech.REPO}}}
        if route=="commits/"+SHA+"/check-runs?per_page=100":
            rows=[{"name":name,"app":{"id": app if not self.forged_check else 999999},
                   "head_sha":SHA,"status":"completed","conclusion":"success"}
                  for name,app in tech.REQUIRED.items()]
            return {"total_count":len(rows),"check_runs":rows}
        if route.startswith("compare/"):
            return {"total_commits":3,"ahead_by":3,"behind_by":0,
                    "merge_base_commit":{"sha":BEFORE[0]},
                    "commits":[{"sha":x} for x in BEFORE[1:]+AFTER]}
        if route.startswith("git/commits/"):
            ref=route.rsplit("/",1)[-1]
            if ref==AFTER[-1] and self.missing:
                return {}
            i=(BEFORE+AFTER).index(ref)
            _,_,when,source=VALUES[i]
            if ref==AFTER[-1] and self.moved_source:
                source=OLD
            return {"sha":ref,"message":"Persist Brain v2 cycle 1234 source "+source,
                    "committer":{"date":when}}
        if route.startswith("contents/state-manifest.json?ref="):
            ref=route.rsplit("=",1)[-1]
            i=(BEFORE+AFTER).index(ref)
            raw,compressed,_,_=VALUES[i]
            chunks=[]
            remaining=raw
            while remaining:
                size=min(8*1024*1024,remaining)
                chunks.append({"raw_size":size,"size":compressed if not chunks else 1})
                remaining-=size
            # Make the fake manifest exactly internally consistent.
            chunks[0]["size"]=compressed-(len(chunks)-1)
            manifest={"format":"sqlite-zlib-chunks-v1","schema_version":1,
                      "raw_size":raw,"compressed_size":compressed,
                      "raw_sha256":"0"*64,"chunks":chunks}
            encoded=base64.b64encode(json.dumps(manifest).encode()).decode()
            return {"type":"file","encoding":"base64","content":encoded}
        raise AssertionError(route)

class VerifiedTechnicalOutcomeTests(unittest.TestCase):
    def test_exact_protected_release_and_real_original_state_slope(self):
        result=tech.evaluate(Provider(),copy.deepcopy(CASE))
        self.assertEqual(result["review"],"TWO_ORIGINAL_EXACT_HEAD_APP_CHECKS_PASSED")
        self.assertEqual(result["release"],"MERGED_ON_PROTECTED_MAIN")
        self.assertEqual(result["before_raw_delta_bytes"],1200128)
        self.assertEqual(result["after_raw_delta_bytes"],-24576)
        self.assertEqual(result["before_raw_bytes_per_hour"],300679)
        self.assertEqual(result["after_raw_bytes_per_hour"],-42130)
        self.assertFalse(result["sustained_improvement_verified"])
        self.assertFalse(result["causal_attribution_verified"])
        self.assertIsNone(result["customer_value_verified"])
        self.assertEqual(result["verified_provider_reads"],11)
    def test_fake_independent_check_is_not_accepted(self):
        p=Provider();p.forged_check=True
        with self.assertRaisesRegex(tech.MeasurementHold,"REVIEW"):
            tech.evaluate(p,CASE)
    def test_changed_or_missing_original_state_is_not_accepted(self):
        for flag in ("missing","moved_source"):
            p=Provider();setattr(p,flag,True)
            with self.subTest(flag=flag),self.assertRaises(tech.MeasurementHold):
                tech.evaluate(p,CASE)
    def test_source_refs_and_schema_are_exact(self):
        bad=copy.deepcopy(CASE);bad["after"][1]=bad["before"][0]
        with self.assertRaisesRegex(tech.MeasurementHold,"SCHEMA"):
            tech.evaluate(Provider(),bad)
    def test_unapproved_network_endpoints_refused(self):
        try:
            api=tech.GitHubOriginal("x"*40)
            with self.assertRaisesRegex(tech.MeasurementHold,"ROUTE_REFUSED"):
                api.get("repos/other/secrets")
        except OSError:
            self.fail("Unapproved endpoint should be rejected before any network call")

if __name__=="__main__":
    unittest.main()
