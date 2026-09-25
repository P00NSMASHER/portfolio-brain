import copy, unittest
from graph.universal_graph import (
  UniversalGraphError, canonicalization_route, find_paths, load_contract,
  upstream_node_projection, validate_canonicalization_proposal, validate_graph,
  validate_node
)

def node(node_id,node_type,key,*,state="OBSERVED",mapping=("PORTFOLIO_ONLY",None),attrs=None,projects=None,refs=None,classification="SANITIZED"):
    return {
      "schema_version":"1.0.0","node_id":node_id,"node_type":node_type,
      "canonical_key":key,"label":key,"project_ids":projects or [],
      "attributes":attrs or {},"provenance_refs":refs or ["git:source"],
      "verification_state":state,"data_classification":classification,"status":"ACTIVE",
      "upstream_mapping":{"mode":mapping[0],"upstream_node_type":mapping[1]}
    }

def edge(edge_id,source,etype,target,*,state="OBSERVED",status="ACTIVE",start="2026-09-25T17:00:00Z",end=None,sup=None):
    refs=["git:relationship-source","ci-run:hostile-fixture"] if state=="VERIFIED" else ["git:relationship-source"]
    return {
      "schema_version":"1.0.0","edge_id":edge_id,"source_node_id":source,
      "edge_type":etype,"target_node_id":target,"attributes":{},
      "provenance_refs":refs,"verification_state":state,
      "status":status,"valid_from":start,"valid_to":end,"supersedes_edge_id":sup
    }

class UniversalGraphTests(unittest.TestCase):
    def test_required_universal_vocabulary_present(self):
        c=load_contract()
        self.assertEqual(len(c["node_types"]),22)
        required={
          "IMPLEMENTS","USES","DISCOVERED_BY","CREATED","DEPENDS_ON","ENABLES",
          "STRENGTHENS","WEAKENS","TESTED_BY","PRODUCED","FAILED","IMPROVED",
          "INVALIDATES","REUSED_BY","GENERATED_VALUE_FOR","SUPERSEDES","CONTRADICTS"
        }
        self.assertTrue(required<=set(c["edge_contracts"]))

    def test_every_contract_pair_uses_real_node_types(self):
        c=load_contract(); types=set(c["node_types"])
        for pairs in c["edge_contracts"].values():
            for a,b in pairs:
                self.assertIn(a,types); self.assertIn(b,types)

    def test_provenance_required_for_nodes_and_edges(self):
        r=node("GN-REPO-00000001","REPOSITORY","repo",mapping=("NATIVE","REPO"))
        c=node("GN-CAP-00000001","CAPABILITY","cap",mapping=("NATIVE","CAPABILITY"))
        bad=copy.deepcopy(r); bad["provenance_refs"]=[]
        with self.assertRaises(UniversalGraphError): validate_node(bad)
        e=edge("GE-EDGE-00000001",r["node_id"],"IMPLEMENTS",c["node_id"]); e["provenance_refs"]=[]
        with self.assertRaises(UniversalGraphError): validate_graph([r,c],[e])

    def test_invalid_relationship_contract_fails_closed(self):
        r=node("GN-REPO-00000001","REPOSITORY","repo",mapping=("NATIVE","REPO"))
        customer=node("GN-CUSTOMER-0001","CUSTOMER","customer",mapping=("NATIVE","CUSTOMER"))
        with self.assertRaises(UniversalGraphError):
            validate_graph([r,customer],[edge("GE-EDGE-00000001",r["node_id"],"GENERATED_VALUE_FOR",customer["node_id"])])

    def test_self_edge_rejected(self):
        p=node("GN-PROJECT-000001","PROJECT","PRJ-000",projects=["PRJ-000"])
        with self.assertRaises(UniversalGraphError):
            validate_graph([p],[edge("GE-EDGE-00000001",p["node_id"],"DEPENDS_ON",p["node_id"])])

    def test_verified_outcome_requires_event_or_evidence_provenance(self):
        o=node("GN-OUTCOME-000001","OUTCOME","out",state="VERIFIED",mapping=("NATIVE","OUTCOME"))
        with self.assertRaises(UniversalGraphError): validate_node(o)
        o["provenance_refs"]=["EVT-OUTCOME-00000001"]
        o["attributes"]={"event_id":"EVT-OUTCOME-00000001"}
        validate_node(o)
        self.assertEqual(upstream_node_projection(o)["provenance"]["verified"],True)

    def test_private_reference_node_rejects_raw_payload(self):
        c=node("GN-CUSTOMER-0001","CUSTOMER","customer",mapping=("NATIVE","CUSTOMER"),
               classification="PRIVATE_REFERENCE_ONLY",attrs={"reference":"vault:1","redacted":True,"name":"secret"})
        with self.assertRaises(UniversalGraphError): validate_node(c)

    def test_portfolio_only_node_is_not_lossily_projected_upstream(self):
        p=node("GN-PROJECT-000001","PROJECT","PRJ-000",projects=["PRJ-000"])
        self.assertIsNone(upstream_node_projection(p))

    def test_supported_node_projects_upstream_without_losing_provenance(self):
        r=node("GN-REPO-00000001","REPOSITORY","repo",mapping=("NATIVE","REPO"),refs=["git:repo@sha"])
        projected=upstream_node_projection(r)
        self.assertEqual(projected["node_type"],"REPO")
        self.assertEqual(projected["provenance"]["evidence_refs"],["git:repo@sha"])

    def test_path_hash_preserves_provenance_chain(self):
        r=node("GN-REPO-00000001","REPOSITORY","repo",mapping=("NATIVE","REPO"))
        c=node("GN-CAP-00000001","CAPABILITY","cap",mapping=("NATIVE","CAPABILITY"))
        p=node("GN-PROJECT-000001","PROJECT","PRJ-000",projects=["PRJ-000"])
        edges=[
          edge("GE-EDGE-00000001",r["node_id"],"IMPLEMENTS",c["node_id"],state="VERIFIED"),
          edge("GE-EDGE-00000002",c["node_id"],"ENABLES",p["node_id"],state="VERIFIED"),
        ]
        paths=find_paths([r,c,p],edges,r["node_id"],p["node_id"])
        self.assertEqual(len(paths),1)
        self.assertTrue(paths[0]["provenance_chain_hash"].startswith("sha256:"))
        self.assertEqual(r["verification_state"],"OBSERVED")

    def test_supersession_preserves_temporal_history(self):
        f=node("GN-FINDING-0001","FINDING","finding")
        o=node("GN-OPPORTUNITY-01","OPPORTUNITY","opp")
        old=edge("GE-EDGE-00000001",f["node_id"],"STRENGTHENS",o["node_id"],status="SUPERSEDED",start="2026-09-25T10:00:00Z",end="2026-09-25T11:00:00Z")
        new=edge("GE-EDGE-00000002",f["node_id"],"STRENGTHENS",o["node_id"],start="2026-09-25T11:00:00Z",sup=old["edge_id"])
        validate_graph([f,o],[old,new])

    def test_duplicate_active_relationship_rejected(self):
        r=node("GN-REPO-00000001","REPOSITORY","repo",mapping=("NATIVE","REPO"))
        c=node("GN-CAP-00000001","CAPABILITY","cap",mapping=("NATIVE","CAPABILITY"))
        with self.assertRaises(UniversalGraphError):
            validate_graph([r,c],[
              edge("GE-EDGE-00000001",r["node_id"],"IMPLEMENTS",c["node_id"]),
              edge("GE-EDGE-00000002",r["node_id"],"IMPLEMENTS",c["node_id"]),
            ])

    def test_canonicalization_routes_only_supported_identity_types(self):
        for t in ["REPOSITORY","DATASET","MODEL","PRODUCT","BUSINESS","CUSTOMER"]:
            self.assertEqual(canonicalization_route(t),"UPSTREAM_REVERSIBLE_CANONICALIZER")
        self.assertEqual(canonicalization_route("PROJECT"),"NO_AUTOMATIC_CANONICALIZATION")

    def test_hard_identifier_conflict_forces_keep_separate(self):
        proposal={
          "left_node_id":"GN-CUSTOMER-0001","right_node_id":"GN-CUSTOMER-0002","node_type":"CUSTOMER",
          "decision":"AUTO_MERGE","hard_identifier_conflicts":["ein"],"reviewer_kind":None,
          "reviewer_principal":None,"review_provenance_refs":[],"reversible":True
        }
        with self.assertRaises(UniversalGraphError): validate_canonicalization_proposal(proposal)
        proposal["decision"]="KEEP_SEPARATE"; validate_canonicalization_proposal(proposal)

    def test_ambiguous_merge_requires_human_review_and_provenance(self):
        p={
          "left_node_id":"GN-CUSTOMER-0001","right_node_id":"GN-CUSTOMER-0002","node_type":"CUSTOMER",
          "decision":"REVIEW","hard_identifier_conflicts":[],"reviewer_kind":"MODEL",
          "reviewer_principal":"agent","review_provenance_refs":["EVD-REVIEW-0000001"],"reversible":True
        }
        with self.assertRaises(UniversalGraphError): validate_canonicalization_proposal(p)
        p["reviewer_kind"]="HUMAN"; p["reviewer_principal"]="owner"; validate_canonicalization_proposal(p)

if __name__=="__main__": unittest.main()
