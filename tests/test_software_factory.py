import base64,tempfile,unittest
from pathlib import Path
from software_factory.software_factory import SoftwareFactory,SoftwareFactoryError,hashv,make_commit_action
from software_factory.github_executor import GitHubExecutor
H=lambda c:"sha256:"+c*64
class FakeTransport:
    def __init__(self,base_sha="a"*40):self.calls=[];self.head=base_sha;self.tree="t"*40;self.n=0
    def __call__(self,method,url,payload=None):
        self.calls.append((method,url,payload))
        if method=="POST" and url.endswith("/git/refs"):self.head=payload["sha"];return {"ref":payload["ref"],"object":{"sha":self.head}}
        if method=="GET" and "/git/ref/heads/" in url:return {"object":{"sha":self.head}}
        if method=="GET" and "/git/commits/" in url:return {"sha":self.head,"tree":{"sha":self.tree}}
        if method=="POST" and url.endswith("/git/blobs"):self.n+=1;return {"sha":f"{self.n:040x}"}
        if method=="POST" and url.endswith("/git/trees"):self.n+=1;self.tree=f"{self.n:040x}";return {"sha":self.tree}
        if method=="POST" and url.endswith("/git/commits"):self.n+=1;self.head=f"{self.n:040x}";return {"sha":self.head}
        if method=="PATCH" and "/git/refs/heads/" in url:self.head=payload["sha"];return {"object":{"sha":self.head}}
        if method=="POST" and url.endswith("/pulls"):return {"number":7,"html_url":"https://example/pr/7","head":{"sha":self.head}}
        raise AssertionError((method,url,payload))
class FactoryTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.sf=SoftwareFactory(Path(self.tmp.name)/"factory.sqlite3");self.base="a"*40
    def tearDown(self):self.sf.close();self.tmp.cleanup()
    def enqueue(self,wid="SFW-TEST-0001"):self.sf.enqueue(work_id=wid,project_id="PRJ-000",repository_id="REPO-008",base_sha=self.base,title="candidate",issue_ref="test:issue",verifier_agent_id="AGT-TESTER",provenance_refs=["test:source"],now=100)
    def test_current_downstream_repo_is_not_write_enabled(self):
        with self.assertRaises(SoftwareFactoryError):self.sf.enqueue(work_id="SFW-X",project_id="PRJ-005",repository_id="REPO-002",base_sha=self.base,title="x",issue_ref="x",verifier_agent_id="AGT-TESTER",provenance_refs=["x"],now=100)
    def test_engineer_claim_creates_isolated_branch_packet(self):
        self.enqueue();p=self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=101);self.assertEqual(p["operation"],"CREATE_BRANCH");self.assertTrue(p["branch_name"].startswith("factory/"));self.assertNotEqual(p["branch_name"],"main")
    def test_non_engineer_cannot_claim(self):
        self.enqueue()
        with self.assertRaises(SoftwareFactoryError):self.sf.claim("SFW-TEST-0001","AGT-HUNTER",now=101)
    def test_forbidden_workflow_path_rejected(self):
        self.enqueue();self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=101)
        raw=b"x";files=[{"path":".github/workflows/evil.yml","content_b64":base64.b64encode(raw).decode(),"content_sha256":"sha256:"+__import__("hashlib").sha256(raw).hexdigest()}]
        with self.assertRaises(SoftwareFactoryError):make_commit_action(self.sf.get("SFW-TEST-0001"),files,"x")
    def test_candidate_requires_regression_test_evidence(self):
        self.enqueue();self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=101)
        with self.assertRaises(SoftwareFactoryError):self.sf.record_candidate_commit("SFW-TEST-0001","AGT-ENGINEER",commit_sha="b"*40,changed_paths=["src/x.py"],test_commands=[],test_receipt_hashes=[],diff_hash=H("d"),now=102)
    def test_builder_cannot_verify_and_independent_tester_can(self):
        self.enqueue();self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=101);self.sf.record_candidate_commit("SFW-TEST-0001","AGT-ENGINEER",commit_sha="b"*40,changed_paths=["src/x.py","tests/test_x.py"],test_commands=["python -m unittest tests.test_x"],test_receipt_hashes=[H("t")],diff_hash=H("d"),now=102)
        with self.assertRaises(SoftwareFactoryError):self.sf.verify("SFW-TEST-0001","AGT-ENGINEER","PASS",report_hash=H("r"),evidence_refs=["test:r"],now=103)
        self.sf.verify("SFW-TEST-0001","AGT-TESTER","PASS",report_hash=H("r"),evidence_refs=["test:r"],now=103);self.assertEqual(self.sf.get("SFW-TEST-0001")["state"],"READY_FOR_PR")
    def test_unbound_eligible_verifier_is_rejected(self):
        self.enqueue();self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=101);self.sf.record_candidate_commit("SFW-TEST-0001","AGT-ENGINEER",commit_sha="b"*40,changed_paths=["src/x.py"],test_commands=["pytest"],test_receipt_hashes=[H("t")],diff_hash=H("d"),now=102)
        with self.assertRaises(SoftwareFactoryError):self.sf.verify("SFW-TEST-0001","AGT-AUDITOR","PASS",report_hash=H("r"),evidence_refs=["audit:r"],now=103)

    def test_failed_audit_requeues_to_fresh_attempt(self):
        self.enqueue();p1=self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=101);self.sf.record_candidate_commit("SFW-TEST-0001","AGT-ENGINEER",commit_sha="b"*40,changed_paths=["src/x.py"],test_commands=["pytest"],test_receipt_hashes=[H("t")],diff_hash=H("d"),now=102);self.sf.verify("SFW-TEST-0001","AGT-TESTER","FAIL",report_hash=H("r"),evidence_refs=["test:r"],now=103);p2=self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=104);self.assertNotEqual(p1["branch_name"],p2["branch_name"])
    def test_pr_packet_only_after_pass(self):
        self.enqueue();self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=101)
        with self.assertRaises(SoftwareFactoryError):self.sf.pr_action("SFW-TEST-0001")
    def test_github_executor_has_only_branch_commit_pr_calls(self):
        self.enqueue();branch=self.sf.claim("SFW-TEST-0001","AGT-ENGINEER",now=101);tr=FakeTransport(self.base);ex=GitHubExecutor("token",transport=tr);ex.execute(branch)
        w=self.sf.get("SFW-TEST-0001");raw=b"print('ok')\n";files=[{"path":"src/x.py","content_b64":base64.b64encode(raw).decode(),"content_sha256":"sha256:"+__import__("hashlib").sha256(raw).hexdigest()}];cp=make_commit_action(w,files,"candidate");commit=ex.execute(cp);self.assertEqual(len(commit["sha"]),40)
        self.sf.record_candidate_commit("SFW-TEST-0001","AGT-ENGINEER",commit_sha=commit["sha"],changed_paths=["src/x.py"],test_commands=["python -m compileall src"],test_receipt_hashes=[H("t")],diff_hash=H("d"),now=102);self.sf.verify("SFW-TEST-0001","AGT-TESTER","PASS",report_hash=H("r"),evidence_refs=["audit:r"],now=103);pp=self.sf.pr_action("SFW-TEST-0001");pr=ex.execute(pp);self.sf.record_pr("SFW-TEST-0001",pr_number=pr["number"],pr_url=pr["html_url"],head_sha=tr.head,now=104);self.assertEqual(self.sf.get("SFW-TEST-0001")["state"],"PR_OPEN")
        self.assertFalse(any("/merge" in url for _,url,_ in tr.calls))
    def test_event_chain_is_tamper_evident(self):
        self.enqueue();self.assertTrue(self.sf.event_chain_valid());self.sf.conn.execute("UPDATE events SET payload_json='{}' WHERE seq=1");self.sf.conn.commit();self.assertFalse(self.sf.event_chain_valid())
if __name__=="__main__":unittest.main()
