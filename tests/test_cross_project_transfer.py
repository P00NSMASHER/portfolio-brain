import copy,unittest
from transfer.cross_project_transfer import TransferError,detect_transfer_hypotheses,hashv,load,validate_outcome,verified_success_edge_candidates
from uncertainty.highest_value_uncertainty import build_snapshot

def add_capability(graph,source_project_id,key,node_id):
    g=copy.deepcopy(graph);source=next(n for n in g["nodes"] if n["node_type"]=="PROJECT" and n["canonical_key"]==source_project_id)
    g["nodes"].append({"node_id":node_id,"node_type":"CAPABILITY","canonical_key":key,"label":key,"verification_state":"VERIFIED","project_ids":[source_project_id],"provenance_refs":[f"test:{key}"],"status":"ACTIVE","attributes":{}})
    g["edges"].append({"edge_id":"GE-"+node_id,"source_node_id":source["node_id"],"target_node_id":node_id,"edge_type":"HAS_CAPABILITY","verification_state":"VERIFIED","status":"ACTIVE","provenance_refs":[f"test:{key}"],"attributes":{}})
    return g

def outcome(p,result="VERIFIED_EFFECTIVE",direction="HIGHER_BETTER",baseline=10,observed=15,delta=5,actor="AGT-RESEARCHER",verifier="AGT-AUDITOR",state="VERIFIED",violations=0):
    core={"schema_version":"1.0.0","outcome_id":"XOUT-TEST-0001","transfer_id":p["transfer_id"],"source_capability_key":p["source_capability_key"],"target_project_id":p["target_project_id"],"result":result,"evidence_state":state,"actor_agent_id":actor,"verifier_agent_id":verifier,"implementation_evidence_ids":["EVD-IMPL-0001"],"measurement_evidence_ids":["EVD-MEAS-0001"],"metric_name":"target_metric","metric_unit":"units","metric_direction":direction,"baseline_value":baseline,"observed_value":observed,"measurable_delta":delta,"authority_violations":violations,"started_at":"2026-09-25T20:00:00Z","completed_at":"2026-09-25T20:01:00Z","outcome_event_id":"EVT-XFER-0001","provenance_refs":["test:transfer-outcome"]}
    return {**core,"outcome_hash":hashv(core)}

class CrossProjectTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph=load("graph/UNIVERSAL_GRAPH_LEDGER.json");cls.projects=load("registry/projects.json")["projects"];cls.uncertainty=build_snapshot();cls.build=load("PORTFOLIO_BUILD_STATE.json")
    def test_current_graph_produces_hypotheses_not_success(self):
        ps=detect_transfer_hypotheses();self.assertEqual(len(ps),44);self.assertTrue(all(p["source_project_id"]=="PRJ-000" for p in ps))
    def test_permitplate_blocker_is_preserved(self):
        ps=[p for p in detect_transfer_hypotheses() if p["target_project_id"]=="PRJ-003"];self.assertEqual(len(ps),4);self.assertTrue(all(p["state"]=="BLOCKED" and "BLK-001" in p["hard_blockers"] for p in ps))
    def test_graph_similarity_never_generates_success_without_outcome(self):
        ps=detect_transfer_hypotheses();self.assertEqual(verified_success_edge_candidates(ps,[]),[])
    def test_verified_effective_outcome_generates_two_success_edge_candidates(self):
        p=next(x for x in detect_transfer_hypotheses() if x["state"]=="ASSESSMENT_READY");edges=verified_success_edge_candidates([p],[outcome(p)],self.graph)
        self.assertEqual({e["edge_type"] for e in edges},{"REUSED_BY","GENERATED_VALUE_FOR"});self.assertTrue(all(e["verification_state"]=="VERIFIED" for e in edges))
    def test_observed_or_self_verified_outcome_cannot_claim_success(self):
        p=next(x for x in detect_transfer_hypotheses() if x["state"]=="ASSESSMENT_READY")
        with self.assertRaises(TransferError):validate_outcome(outcome(p,state="OBSERVED"),p)
        with self.assertRaises(TransferError):validate_outcome(outcome(p,actor="AGT-AUDITOR",verifier="AGT-AUDITOR"),p)
    def test_no_value_is_negative_not_success(self):
        p=next(x for x in detect_transfer_hypotheses() if x["state"]=="ASSESSMENT_READY");o=outcome(p,result="VERIFIED_NO_VALUE",baseline=10,observed=10,delta=0);validate_outcome(o,p);self.assertEqual(verified_success_edge_candidates([p],[o],self.graph),[])
    def test_authority_violation_blocks_effective_claim(self):
        p=next(x for x in detect_transfer_hypotheses() if x["state"]=="ASSESSMENT_READY")
        with self.assertRaises(TransferError):validate_outcome(outcome(p,violations=1),p)
    def test_recovery_evidence_can_target_capturebrief_when_source_exists(self):
        g=add_capability(self.graph,"PRJ-001","recovery:evidence-architecture","GN-CAP-RECOVERY-EVIDENCE");ps=detect_transfer_hypotheses(g,self.projects,self.uncertainty,self.build)
        self.assertTrue(any(p["source_project_id"]=="PRJ-001" and p["target_project_id"]=="PRJ-004" and p["source_capability_key"]=="recovery:evidence-architecture" for p in ps))
    def test_starblox_experimentation_can_target_abvm_when_source_exists(self):
        g=add_capability(self.graph,"PRJ-005","product:experimentation","GN-CAP-PRODUCT-EXPERIMENT");ps=detect_transfer_hypotheses(g,self.projects,self.uncertainty,self.build)
        self.assertTrue(any(p["source_project_id"]=="PRJ-005" and p["target_project_id"]=="PRJ-006" for p in ps if p["source_capability_key"]=="product:experimentation"))
    def test_research_evaluation_can_target_hunter_when_source_exists(self):
        g=add_capability(self.graph,"PRJ-007","research:evaluation-methods","GN-CAP-RESEARCH-EVAL");ps=detect_transfer_hypotheses(g,self.projects,self.uncertainty,self.build)
        self.assertTrue(any(p["source_project_id"]=="PRJ-007" and p["target_project_id"]=="PRJ-008" for p in ps if p["source_capability_key"]=="research:evaluation-methods"))
    def test_hunter_discovery_can_target_recoveryworks_when_source_exists(self):
        g=add_capability(self.graph,"PRJ-008","hunter:discovery-engine","GN-CAP-HUNTER-DISCOVERY");ps=detect_transfer_hypotheses(g,self.projects,self.uncertainty,self.build)
        self.assertTrue(any(p["source_project_id"]=="PRJ-008" and p["target_project_id"]=="PRJ-001" for p in ps if p["source_capability_key"]=="hunter:discovery-engine"))
    def test_portfolio_continuous_learning_can_transfer_broadly_when_registered(self):
        g=add_capability(self.graph,"PRJ-000","portfolio:continuous-learning","GN-CAP-CONTINUOUS-LEARNING");ps=detect_transfer_hypotheses(g,self.projects,self.uncertainty,self.build)
        targets={p["target_project_id"] for p in ps if p["source_capability_key"]=="portfolio:continuous-learning"};self.assertTrue({"PRJ-001","PRJ-005","PRJ-008"}<=targets)
if __name__=="__main__":unittest.main()
