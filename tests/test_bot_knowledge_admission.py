"""Exact-source GitHub bot data-admission unit tests."""
import json
import hashlib
import unittest
from verification.bot_knowledge_admission import (
    inspect, foundation_green, BotAdmissionError
)
A,B="a"*40,"b"*40
REPO="P00NSMASHER/portfolio-brain"

def fixture():
    rows=[]
    for i in range(3):
        path=f"brain/module{i}.py"
        rows.append(dict(key=f"source:{i}",repository=REPO,head_sha=A,path=path,
            blob_sha=B,code_sha256="d"*64,test_paths=["tests/test_brain_v2.py"],
            license="UNKNOWN",
            source_ref=f"https://github.com/{REPO}/blob/{A}/{path}",
            target="freight-recovery",matched_terms=["invoice","audit"]))
    fp=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),
                                 ensure_ascii=False).encode()).hexdigest()
    body=json.dumps(dict(schema_version=2,
        scope="STRUCTURAL_REUSE_KNOWLEDGE_NOT_EXECUTED_OR_REVENUE_VERIFIED",
        sources=rows,fingerprint=fp)).encode()
    pr=dict(number=688,state="open",merged=False,draft=False,
        user={"login":"github-actions[bot]"},
        head={"sha":B,"ref":"factory/auto-repair-v2-knowledge-"+fp[:16],
              "repo":{"full_name":REPO}},
        base={"ref":"main","repo":{"full_name":REPO}},
        body=f"AUTO_REPAIR_FINGERPRINT: {fp}\n")
    m={"commit":{"sha":A}}
    c={"merge_base_commit":{"sha":A},"files":[{
        "filename":"brain/REUSE_KNOWLEDGE.json","status":"modified"}]}
    return pr,m,c,body

class BotKnowledgeTests(unittest.TestCase):
    def test_source_bound_bot_only(self):
        p,m,c,body=fixture()
        result=inspect(p,m,c,body,number=688,head_sha=B)
        self.assertEqual(result["status"],"EXACT_BOT_DATA_ONLY_ADMITTED")
        self.assertFalse(result["released"])

    def test_untrusted_author_fork_branch_and_changed_code_denied(self):
        for label in ("human","fork","branch","other_file","stale","draft"):
            p,m,c,body=fixture()
            if label=="human":p["user"]["login"]="someone"
            if label=="fork":p["head"]["repo"]["full_name"]="someone/else"
            if label=="branch":p["head"]["ref"]="fix/skip"
            if label=="other_file":c["files"][0]["filename"]="brain/upgrades.py"
            if label=="stale":c["merge_base_commit"]["sha"]=B
            if label=="draft":p["draft"]=True
            with self.subTest(label=label),self.assertRaises(BotAdmissionError):
                inspect(p,m,c,body,number=688,head_sha=B)

    def test_corrupt_source_and_forged_fingerprint_denied(self):
        p,m,c,body=fixture()
        for data in (body[:-1]+b', "releaseApproved":true}',
                     body.replace(b'"schema_version": 2',b'"schema_version": 3'),
                     b'broken json'):
            with self.assertRaises(BotAdmissionError):
                inspect(p,m,c,data,number=688,head_sha=B)

    def test_foundation_app_provenance(self):
        checks={"total_count":1,"check_runs":[{"name":"validate",
            "head_sha":B,"status":"completed","conclusion":"success",
            "app":{"id":15368}}]}
        self.assertTrue(foundation_green(checks,B))
        checks["check_runs"][0]["app"]["id"]=1
        with self.assertRaises(BotAdmissionError):
            foundation_green(checks,B)

if __name__=="__main__":
    unittest.main()
