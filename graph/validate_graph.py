#!/usr/bin/env python3
"""Cross-file validator for Step 7 universal knowledge graph."""
from __future__ import annotations
import json
from pathlib import Path
from graph.universal_graph import (
    canonical_hash, load_contract, upstream_edge_projection, upstream_node_projection,
    validate_graph
)

ROOT=Path(__file__).resolve().parents[1]

class GraphConformanceError(ValueError): pass
def require(ok: bool,msg: str)->None:
    if not ok: raise GraphConformanceError(msg)
def load(path: str):
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def validate_graph_bundle()->dict[str,object]:
    state=load("PORTFOLIO_BUILD_STATE.json")
    pin=load("graph/AI_BUSINESS_OS_GRAPH_PIN.json")
    conf=load("graph/GRAPH_CONFORMANCE.json")
    ledger=load("graph/UNIVERSAL_GRAPH_LEDGER.json")
    projects=load("registry/projects.json")["projects"]
    node_schema=load("schemas/GRAPH_NODE_SCHEMA.json")
    edge_schema=load("schemas/GRAPH_EDGE_SCHEMA.json")
    contract=load_contract()

    require(state["repositories"]["REPO-001"]["last_inspected_sha"]==pin["source_revision"],
            "canonical graph source cursor drifted; reconformance required")
    require(pin["source_revision"]==conf["source_revision"],"graph conformance revision mismatch")
    require(pin["knowledge_graph"]["blob_sha"]==conf["knowledge_graph_blob"],"knowledge graph blob mismatch")
    require(pin["entity_canonicalization"]["blob_sha"]==conf["entity_canonicalization_blob"],"canonicalizer blob mismatch")
    require(pin["copied_source_code"] is False,"canonical graph source must not be copied")
    require(pin["integration_mode"]=="PINNED_INTERFACE_PLUS_LOSSLESS_PORTFOLIO_ENVELOPE","graph integration mode weakened")
    require(conf["authority_change"]=="NONE","graph integration cannot grant authority")
    require(node_schema["additionalProperties"] is False and edge_schema["additionalProperties"] is False,"graph schemas must be closed")

    required_nodes={
      "OWNER_OBJECTIVE","PROJECT","BUSINESS","PRODUCT","REPOSITORY","CAPABILITY",
      "DATASET","MODEL","AGENT","SKILL","SEARCH","FINDING","EXPERIMENT","CHANGE",
      "BUG","CUSTOMER","MARKET","OPPORTUNITY","OUTCOME","REVENUE","COST","EVIDENCE"
    }
    required_edges={
      "IMPLEMENTS","USES","DISCOVERED_BY","CREATED","DEPENDS_ON","ENABLES",
      "STRENGTHENS","WEAKENS","TESTED_BY","PRODUCED","FAILED","IMPROVED",
      "INVALIDATES","REUSED_BY","GENERATED_VALUE_FOR","SUPERSEDES","CONTRADICTS"
    }
    require(required_nodes==set(contract["node_types"]),"universal node vocabulary mismatch")
    require(required_edges<=set(contract["edge_contracts"]),"required edge vocabulary missing")

    nodes=ledger["nodes"]; edges=ledger["edges"]
    result=validate_graph(nodes,edges)
    by_id={n["node_id"]:n for n in nodes}

    project_ids={p["project_id"] for p in projects}
    graph_projects={n["canonical_key"] for n in nodes if n["node_type"]=="PROJECT"}
    require(graph_projects==project_ids,"seed graph must contain all registered projects")
    repo_names={b["full_name"] for p in projects for b in p["repository_bindings"]}
    graph_repos={n["canonical_key"] for n in nodes if n["node_type"]=="REPOSITORY"}
    require(graph_repos==repo_names,"seed graph repository set mismatch")

    capability_nodes=[n for n in nodes if n["node_type"]=="CAPABILITY"]
    require(len(capability_nodes)>=4,"verified Portfolio Brain capabilities missing")
    require(all(n["verification_state"]=="VERIFIED" for n in capability_nodes),"seed capabilities must be verified")

    # Seed graph deliberately does not invent commercial entities/outcomes.
    for t in {"CUSTOMER","REVENUE","OPPORTUNITY","OUTCOME"}:
        require(not any(n["node_type"]==t for n in nodes),f"unsupported seed {t} node found")

    upstream_nodes=sum(upstream_node_projection(n) is not None for n in nodes)
    upstream_edges=sum(upstream_edge_projection(e,by_id) is not None for e in edges)

    semantics=conf["semantics"]
    require(semantics["typed_edges"]=="FAIL_CLOSED","typed edge semantics weakened")
    require(semantics["node_provenance"]=="REQUIRED","node provenance weakened")
    require(semantics["edge_evidence"]=="REQUIRED","edge evidence weakened")
    require(semantics["hard_identifier_conflict"]=="KEEP_SEPARATE","canonicalization conflict gate weakened")
    require(semantics["ambiguous_merge"]=="HUMAN_REVIEW_REQUIRED","canonicalization review gate weakened")
    require(semantics["canonicalization_reversal"]=="SUPPORTED_WITH_DEPENDENCY_GATES","canonicalization reversibility weakened")
    require(conf["universal_extension"]["graph_connectivity_truth_effect"]=="NONE","graph cannot upgrade truth")

    return {
      **result,
      "upstream_projectable_nodes":upstream_nodes,
      "upstream_projectable_edges":upstream_edges,
      "registered_projects":len(project_ids),
      "ledger_hash":canonical_hash({"nodes":nodes,"edges":edges}),
    }

if __name__=="__main__":
    print("portfolio-brain Step 7 graph: PASS",json.dumps(validate_graph_bundle(),sort_keys=True))
