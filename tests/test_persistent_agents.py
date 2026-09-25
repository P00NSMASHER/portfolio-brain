import tempfile,unittest
from pathlib import Path
from agents.persistent_agents import AgentRuntimeError,PortfolioAgentRuntime
H=lambda c:"sha256:"+c*64
class PersistentAgentTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/"agents.sqlite3";self.rt=PortfolioAgentRuntime(self.db)
    def tearDown(self):self.rt.close();self.tmp.cleanup()
    def enqueue_engineering(self,work_id="AWORK-ENGINEERING-0001"):return self.rt.enqueue_work("AGT-PORTFOLIO-MANAGER","AGT-ENGINEER","ISOLATED_IMPLEMENTATION","Implement isolated candidate",["PRJ-000"],"MODIFY","HIGH",priority=90,state_refs=["branch:isolated"],work_id=work_id,now=100.0)
    def test_ten_stable_agents_bootstrap(self):
        rows=self.rt.conn.execute("SELECT agent_id,role_key FROM agents ORDER BY agent_id").fetchall();self.assertEqual(len(rows),10);self.assertIn(("AGT-ENGINEER","ENGINEER"),[(r["agent_id"],r["role_key"]) for r in rows])
    def test_restart_persists_identity_and_work(self):
        wid=self.enqueue_engineering();self.rt.close();self.rt=PortfolioAgentRuntime(self.db);self.assertEqual(self.rt.get_work(wid)["state"],"PENDING");self.assertEqual(self.rt.conn.execute("SELECT count(*) AS n FROM agents").fetchone()["n"],10)
    def test_only_manager_can_delegate(self):
        with self.assertRaises(AgentRuntimeError):self.rt.enqueue_work("AGT-HUNTER","AGT-RESEARCHER","RESEARCH_EVIDENCE","x",["PRJ-000"],"OBSERVE","LOW",now=100.0)
    def test_goal_type_and_authority_ceiling_fail_closed(self):
        with self.assertRaises(AgentRuntimeError):self.rt.enqueue_work("AGT-PORTFOLIO-MANAGER","AGT-HUNTER","ISOLATED_IMPLEMENTATION","x",["PRJ-000"],"OBSERVE","LOW",now=100.0)
        with self.assertRaises(AgentRuntimeError):self.rt.enqueue_work("AGT-PORTFOLIO-MANAGER","AGT-HUNTER","PUBLIC_HUNT","x",["PRJ-000"],"MODIFY","LOW",now=100.0)
        with self.assertRaises(AgentRuntimeError):self.rt.enqueue_work("AGT-PORTFOLIO-MANAGER","AGT-COMMERCIAL-ANALYST","COMMERCIAL_ANALYSIS","x",["PRJ-001"],"ACT","HIGH",now=100.0)
    def test_submission_requires_verification_before_complete(self):
        wid=self.enqueue_engineering();c=self.rt.claim_work("AGT-ENGINEER","worker-1",now=101.0);self.rt.submit_work("AGT-ENGINEER",wid,"worker-1",c["run_id"],c["lease_generation"],output_hash=H("a"),evidence_refs=["evidence:test"],now=102.0);self.assertEqual(self.rt.get_work(wid)["state"],"VERIFYING")
    def test_builder_cannot_self_verify(self):
        wid=self.enqueue_engineering();c=self.rt.claim_work("AGT-ENGINEER","worker-1",now=101.0);self.rt.submit_work("AGT-ENGINEER",wid,"worker-1",c["run_id"],c["lease_generation"],output_hash=H("a"),evidence_refs=["evidence:test"],now=102.0)
        with self.assertRaises(AgentRuntimeError):self.rt.verify_work("AGT-ENGINEER",wid,"PASS",report_hash=H("b"),evidence_refs=["audit:test"],now=103.0)
    def test_independent_tester_can_complete_engineering_work(self):
        wid=self.enqueue_engineering();c=self.rt.claim_work("AGT-ENGINEER","worker-1",now=101.0);self.rt.submit_work("AGT-ENGINEER",wid,"worker-1",c["run_id"],c["lease_generation"],output_hash=H("a"),evidence_refs=["evidence:test"],now=102.0);vid=self.rt.verify_work("AGT-TESTER",wid,"PASS",report_hash=H("b"),evidence_refs=["audit:test"],now=103.0);self.assertTrue(vid.startswith("AVER-"));self.assertEqual(self.rt.get_work(wid)["state"],"COMPLETE")
    def test_unknown_verification_blocks(self):
        wid=self.enqueue_engineering();c=self.rt.claim_work("AGT-ENGINEER","worker-1",now=101.0);self.rt.submit_work("AGT-ENGINEER",wid,"worker-1",c["run_id"],c["lease_generation"],output_hash=H("a"),evidence_refs=["evidence:test"],now=102.0);self.rt.verify_work("AGT-AUDITOR",wid,"UNKNOWN",report_hash=H("b"),evidence_refs=["audit:unknown"],now=103.0);self.assertEqual(self.rt.get_work(wid)["state"],"BLOCKED")
    def test_expired_lease_requeues_and_fences_stale_generation(self):
        wid=self.enqueue_engineering();c=self.rt.claim_work("AGT-ENGINEER","worker-1",lease_seconds=30,now=101.0);self.assertEqual(self.rt.requeue_expired(now=132.0),1);fresh=self.rt.claim_work("AGT-ENGINEER","worker-2",lease_seconds=30,now=133.0);self.assertGreater(fresh["lease_generation"],c["lease_generation"])
        with self.assertRaises(AgentRuntimeError):self.rt.submit_work("AGT-ENGINEER",wid,"worker-1",c["run_id"],c["lease_generation"],output_hash=H("a"),evidence_refs=["evidence:stale"],now=134.0)
    def test_agent_model_tier_ceiling(self):
        self.assertTrue(self.rt.authorize_model_tier("AGT-AUDITOR",3))
        with self.assertRaises(AgentRuntimeError):self.rt.authorize_model_tier("AGT-ENGINEER",3)
        with self.assertRaises(AgentRuntimeError):self.rt.authorize_model_tier("AGT-HUNTER",2)
    def test_snapshot_restore_preserves_event_history(self):
        wid=self.enqueue_engineering();sid=self.rt.checkpoint_work(wid,now=101.0);before=self.rt.conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"];self.rt.restore_state_refs(wid,sid,now=102.0);after=self.rt.conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"];self.assertGreater(after,before);self.assertTrue(self.rt.event_chain_valid())
    def test_event_chain_detects_tampering(self):
        self.enqueue_engineering();self.assertTrue(self.rt.event_chain_valid());self.rt.conn.execute("UPDATE events SET payload_json='{}' WHERE seq=(SELECT min(seq) FROM events)");self.rt.conn.commit();self.assertFalse(self.rt.event_chain_valid())
if __name__=="__main__":unittest.main()
