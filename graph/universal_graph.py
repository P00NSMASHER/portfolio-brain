#!/usr/bin/env python3
"""Deterministic universal graph envelope for Portfolio Brain.

The canonical AI Business OS KnowledgeGraph remains the durable typed graph engine
for its native vocabulary. This module validates the larger portfolio vocabulary,
keeps unsupported types lossless, and only projects compatible records upstream.
"""
from __future__ import annotations
import hashlib, json, re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
CONTRACT_PATH=ROOT/"graph"/"UNIVERSAL_GRAPH_CONTRACT.json"

GN_ID=re.compile(r"^GN-[A-Z0-9-]{8,}$")
GE_ID=re.compile(r"^GE-[A-Z0-9-]{8,}$")
PRJ_ID=re.compile(r"^PRJ-[0-9]{3,}$")
TRUTH_STATES={"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"}
NODE_STATUSES={"ACTIVE","SUPERSEDED","RETIRED","CANONICALIZED","REVERSED"}
EDGE_STATUSES={"ACTIVE","SUPERSEDED","RETIRED"}
UPSTREAM_NODE_TYPES={"REPO","DATA","CAPABILITY","TECHNOLOGY","PRODUCT","BUSINESS","CUSTOMER","EXPERIMENT","OUTCOME","MEMORY"}
CANONICALIZABLE_UNIVERSAL_TYPES={"REPOSITORY","DATASET","MODEL","PRODUCT","BUSINESS","CUSTOMER"}

class UniversalGraphError(ValueError): pass

def _require(ok: bool,msg: str)->None:
    if not ok: raise UniversalGraphError(msg)

def canonical_hash(value: Any)->str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def _has_verification_anchor(refs: list[str])->bool:
    prefixes=("ci-run:","event:","evidence:","verification:","test-receipt:")
    return any(r.startswith(prefixes) or r.startswith("EVT-") or r.startswith("EVD-") for r in refs)

def _time(value: str, field: str)->datetime:
    _require(isinstance(value,str) and value,f"{field} required")
    try: dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc: raise UniversalGraphError(f"{field} invalid ISO-8601") from exc
    _require(dt.tzinfo is not None,f"{field} requires timezone")
    return dt

def load_contract()->dict[str,Any]:
    data=json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    validate_contract(data)
    return data

def validate_contract(contract: dict[str,Any])->None:
    _require(contract.get("schema_version")=="1.0.0","graph contract schema mismatch")
    node_types=contract.get("node_types"); required_edges=contract.get("required_relationships")
    _require(isinstance(node_types,list) and len(node_types)==len(set(node_types)),"node types invalid")
    _require(isinstance(required_edges,list) and len(required_edges)==len(set(required_edges)),"required relationships invalid")
    edge_contracts=contract.get("edge_contracts")
    _require(isinstance(edge_contracts,dict),"edge contracts missing")
    _require(set(required_edges)<=set(edge_contracts),"required relationship missing contract")
    node_set=set(node_types)
    for edge_type,pairs in edge_contracts.items():
        _require(isinstance(pairs,list) and pairs,f"{edge_type} requires at least one type contract")
        seen=set()
        for pair in pairs:
            _require(isinstance(pair,list) and len(pair)==2,f"{edge_type} invalid pair")
            _require(pair[0] in node_set and pair[1] in node_set,f"{edge_type} references unknown node type")
            _require(tuple(pair) not in seen,f"{edge_type} duplicate pair")
            seen.add(tuple(pair))

def validate_node(node: dict[str,Any], contract: dict[str,Any]|None=None)->None:
    contract=contract or load_contract()
    required={"schema_version","node_id","node_type","canonical_key","label","project_ids","attributes",
              "provenance_refs","verification_state","data_classification","status","upstream_mapping"}
    _require(isinstance(node,dict) and set(node)==required,"graph node fields must exactly match contract")
    _require(node["schema_version"]=="1.0.0","node schema mismatch")
    _require(GN_ID.fullmatch(node["node_id"]) is not None,"invalid node_id")
    _require(node["node_type"] in contract["node_types"],"unsupported node_type")
    _require(isinstance(node["canonical_key"],str) and node["canonical_key"],"canonical_key required")
    _require(isinstance(node["label"],str) and node["label"],"label required")
    pids=node["project_ids"]; _require(isinstance(pids,list) and len(pids)==len(set(pids)),"project_ids invalid")
    _require(all(PRJ_ID.fullmatch(x) for x in pids),"invalid project_id")
    _require(isinstance(node["attributes"],dict),"attributes must be object")
    refs=node["provenance_refs"]; _require(isinstance(refs,list) and refs and len(refs)==len(set(refs)),"provenance_refs required and unique")
    _require(all(isinstance(x,str) and x for x in refs),"invalid provenance_ref")
    _require(node["verification_state"] in TRUTH_STATES,"invalid verification_state")
    if node["verification_state"]=="VERIFIED":
        _require(_has_verification_anchor(refs),"VERIFIED graph node requires machine/human verification anchor")
    _require(node["data_classification"] in {"PUBLIC","SANITIZED","PRIVATE_REFERENCE_ONLY"},"invalid data classification")
    _require(node["status"] in NODE_STATUSES,"invalid node status")
    mapping=node["upstream_mapping"]
    _require(isinstance(mapping,dict) and set(mapping)=={"mode","upstream_node_type"},"invalid upstream mapping")
    _require(mapping["mode"] in {"NATIVE","ADAPTED","PORTFOLIO_ONLY"},"invalid mapping mode")
    if mapping["mode"]=="PORTFOLIO_ONLY":
        _require(mapping["upstream_node_type"] is None,"portfolio-only node cannot claim upstream type")
    else:
        _require(mapping["upstream_node_type"] in UPSTREAM_NODE_TYPES,"invalid upstream node type")

    if node["data_classification"]=="PRIVATE_REFERENCE_ONLY":
        _require(set(node["attributes"])<= {"reference","summary","redacted"},"private-reference node contains raw attributes")
        _require(node["attributes"].get("redacted") is True,"private-reference node must be redacted")
        _require(isinstance(node["attributes"].get("reference"),str) and node["attributes"]["reference"],"private-reference node requires reference")

    if node["node_type"] in {"OUTCOME","REVENUE"} and node["verification_state"]=="VERIFIED":
        _require(any(("EVT-" in x or "EVD-" in x or x.startswith("event:") or x.startswith("evidence:")) for x in refs),
                 "VERIFIED outcome/value node requires event/evidence provenance")

def validate_edge(edge: dict[str,Any], nodes_by_id: dict[str,dict[str,Any]], contract: dict[str,Any]|None=None)->None:
    contract=contract or load_contract()
    required={"schema_version","edge_id","source_node_id","edge_type","target_node_id","attributes",
              "provenance_refs","verification_state","status","valid_from","valid_to","supersedes_edge_id"}
    _require(isinstance(edge,dict) and set(edge)==required,"graph edge fields must exactly match contract")
    _require(edge["schema_version"]=="1.0.0","edge schema mismatch")
    _require(GE_ID.fullmatch(edge["edge_id"]) is not None,"invalid edge_id")
    _require(edge["source_node_id"] in nodes_by_id and edge["target_node_id"] in nodes_by_id,"edge references missing node")
    _require(edge["source_node_id"]!=edge["target_node_id"],"self edges forbidden")
    _require(edge["edge_type"] in contract["edge_contracts"],"unsupported edge type")
    source_type=nodes_by_id[edge["source_node_id"]]["node_type"]
    target_type=nodes_by_id[edge["target_node_id"]]["node_type"]
    allowed={tuple(x) for x in contract["edge_contracts"][edge["edge_type"]]}
    _require((source_type,target_type) in allowed,f"invalid edge contract: {source_type} -{edge['edge_type']}-> {target_type}")
    _require(isinstance(edge["attributes"],dict),"edge attributes must be object")
    refs=edge["provenance_refs"]; _require(isinstance(refs,list) and refs and len(refs)==len(set(refs)),"edge provenance required and unique")
    _require(all(isinstance(x,str) and x for x in refs),"invalid edge provenance")
    _require(edge["verification_state"] in TRUTH_STATES,"invalid edge verification state")
    if edge["verification_state"]=="VERIFIED":
        _require(_has_verification_anchor(refs),"VERIFIED graph edge requires machine/human verification anchor")
    _require(edge["status"] in EDGE_STATUSES,"invalid edge status")
    start=_time(edge["valid_from"],"valid_from")
    end=None if edge["valid_to"] is None else _time(edge["valid_to"],"valid_to")
    if end is not None: _require(end>=start,"valid_to precedes valid_from")
    if edge["status"]=="SUPERSEDED": _require(end is not None,"superseded edge requires valid_to")
    sup=edge["supersedes_edge_id"]
    _require(sup is None or GE_ID.fullmatch(sup) is not None,"invalid supersedes_edge_id")

def validate_graph(nodes: list[dict[str,Any]], edges: list[dict[str,Any]])->dict[str,Any]:
    contract=load_contract()
    nodes_by_id={}
    canonical=set()
    for node in nodes:
        validate_node(node,contract)
        _require(node["node_id"] not in nodes_by_id,"duplicate node_id")
        key=(node["node_type"],node["canonical_key"].casefold())
        _require(key not in canonical,"duplicate canonical identity within node type")
        canonical.add(key); nodes_by_id[node["node_id"]]=node

    edges_by_id={}
    active_triples=set()
    for edge in edges:
        validate_edge(edge,nodes_by_id,contract)
        _require(edge["edge_id"] not in edges_by_id,"duplicate edge_id")
        triple=(edge["source_node_id"],edge["edge_type"],edge["target_node_id"])
        if edge["status"]=="ACTIVE":
            _require(triple not in active_triples,"duplicate active source/type/target edge")
            active_triples.add(triple)
        edges_by_id[edge["edge_id"]]=edge

    for edge in edges:
        sup=edge["supersedes_edge_id"]
        if sup is not None:
            _require(sup in edges_by_id,"superseded edge missing")
            old=edges_by_id[sup]
            _require(old["status"]=="SUPERSEDED","prior edge must be SUPERSEDED")
            _require((old["source_node_id"],old["edge_type"],old["target_node_id"])==
                     (edge["source_node_id"],edge["edge_type"],edge["target_node_id"]),
                     "supersession must preserve source/type/target")
            _require(old["valid_to"]==edge["valid_from"],"supersession boundary must be contiguous")

    return {
      "nodes":len(nodes_by_id),
      "edges":len(edges_by_id),
      "node_types":len({n["node_type"] for n in nodes}),
      "edge_types":len({e["edge_type"] for e in edges}),
      "graph_hash":canonical_hash({"nodes":nodes,"edges":edges}),
    }

def find_paths(nodes: list[dict[str,Any]], edges: list[dict[str,Any]], start_id: str, target_id: str, *, max_depth: int=6)->list[dict[str,Any]]:
    validate_graph(nodes,edges)
    by_id={n["node_id"]:n for n in nodes}
    _require(start_id in by_id and target_id in by_id,"path endpoint missing")
    active=[e for e in edges if e["status"]=="ACTIVE"]
    outgoing={}
    for e in active: outgoing.setdefault(e["source_node_id"],[]).append(e)
    queue=deque([(start_id,[start_id],[])])
    paths=[]
    while queue:
        current,node_path,edge_path=queue.popleft()
        if len(edge_path)>=max_depth: continue
        for edge in outgoing.get(current,[]):
            nxt=edge["target_node_id"]
            if nxt in node_path: continue
            new_nodes=node_path+[nxt]; new_edges=edge_path+[edge["edge_id"]]
            if nxt==target_id:
                path_nodes=[by_id[x] for x in new_nodes]
                path_edges=[next(e for e in active if e["edge_id"]==x) for x in new_edges]
                paths.append({
                  "node_ids":new_nodes,"edge_ids":new_edges,
                  "provenance_chain_hash":canonical_hash({
                    "nodes":[n["provenance_refs"] for n in path_nodes],
                    "edges":[e["provenance_refs"] for e in path_edges],
                  })
                })
            else:
                queue.append((nxt,new_nodes,new_edges))
    return paths

def upstream_node_projection(node: dict[str,Any])->dict[str,Any]|None:
    validate_node(node)
    mapping=node["upstream_mapping"]
    if mapping["mode"]=="PORTFOLIO_ONLY": return None
    provenance={"evidence_refs":node["provenance_refs"]}
    if mapping["upstream_node_type"]=="OUTCOME":
        _require(node["verification_state"]=="VERIFIED","upstream OUTCOME must be VERIFIED")
        event_id=node["attributes"].get("event_id")
        _require(isinstance(event_id,str) and event_id,"upstream OUTCOME requires attributes.event_id")
        provenance.update({"verified":True,"event_id":event_id})
    return {
      "node_type":mapping["upstream_node_type"],
      "canonical_key":node["canonical_key"],
      "label":node["label"],
      "attributes":node["attributes"],
      "provenance":provenance,
      "node_id":node["node_id"],
    }

def canonicalization_route(node_type: str)->str:
    _require(node_type in load_contract()["node_types"],"unknown universal node type")
    return "UPSTREAM_REVERSIBLE_CANONICALIZER" if node_type in CANONICALIZABLE_UNIVERSAL_TYPES else "NO_AUTOMATIC_CANONICALIZATION"

def validate_canonicalization_proposal(proposal: dict[str,Any])->None:
    required={"left_node_id","right_node_id","node_type","decision","hard_identifier_conflicts",
              "reviewer_kind","reviewer_principal","review_provenance_refs","reversible"}
    _require(isinstance(proposal,dict) and set(proposal)==required,"canonicalization proposal fields changed")
    _require(GN_ID.fullmatch(proposal["left_node_id"]) and GN_ID.fullmatch(proposal["right_node_id"]),"invalid canonicalization node id")
    _require(proposal["left_node_id"]!=proposal["right_node_id"],"cannot canonicalize node with itself")
    _require(canonicalization_route(proposal["node_type"])=="UPSTREAM_REVERSIBLE_CANONICALIZER","node type not canonicalizable")
    _require(proposal["decision"] in {"KEEP_SEPARATE","REVIEW","AUTO_MERGE"},"invalid canonicalization decision")
    conflicts=proposal["hard_identifier_conflicts"]
    _require(isinstance(conflicts,list) and len(conflicts)==len(set(conflicts)),"hard conflicts invalid")
    _require(proposal["reversible"] is True,"canonicalization must remain reversible")
    if conflicts:
        _require(proposal["decision"]=="KEEP_SEPARATE","hard identifier conflict must keep separate")
    if proposal["decision"]=="REVIEW":
        _require(proposal["reviewer_kind"]=="HUMAN","ambiguous merge requires HUMAN reviewer")
        _require(isinstance(proposal["reviewer_principal"],str) and proposal["reviewer_principal"],"human reviewer identity required")
        refs=proposal["review_provenance_refs"]
        _require(isinstance(refs,list) and refs,"human review provenance required")
    elif proposal["decision"]=="AUTO_MERGE":
        _require(not conflicts,"auto merge cannot have hard conflicts")


UPSTREAM_EDGE_CONTRACTS = {
    "IMPLEMENTS": {("REPO","CAPABILITY"),("DATA","CAPABILITY"),("TECHNOLOGY","CAPABILITY")},
    "STRENGTHENS": {
        ("REPO","CAPABILITY"),("DATA","CAPABILITY"),("TECHNOLOGY","CAPABILITY"),
        ("EXPERIMENT","CAPABILITY"),("EXPERIMENT","PRODUCT"),("EXPERIMENT","BUSINESS"),
    },
    "ENABLES": {
        ("CAPABILITY","PRODUCT"),("CAPABILITY","BUSINESS"),
        ("TECHNOLOGY","PRODUCT"),("TECHNOLOGY","BUSINESS"),
    },
    "USES": {
        ("PRODUCT","CAPABILITY"),("PRODUCT","TECHNOLOGY"),("PRODUCT","DATA"),
        ("BUSINESS","CAPABILITY"),("BUSINESS","TECHNOLOGY"),("BUSINESS","DATA"),
    },
    "TESTED_BY": {
        ("CAPABILITY","EXPERIMENT"),("PRODUCT","EXPERIMENT"),("BUSINESS","EXPERIMENT"),
    },
    "PRODUCED": {
        ("EXPERIMENT","OUTCOME"),("PRODUCT","OUTCOME"),("BUSINESS","OUTCOME"),
    },
}
UPSTREAM_BROAD_EDGES={"DEPENDS_ON"}

def upstream_edge_projection(edge: dict[str,Any], nodes_by_id: dict[str,dict[str,Any]])->dict[str,Any]|None:
    validate_edge(edge,nodes_by_id)
    source=upstream_node_projection(nodes_by_id[edge["source_node_id"]])
    target=upstream_node_projection(nodes_by_id[edge["target_node_id"]])
    if source is None or target is None:
        return None
    et=edge["edge_type"]
    if et in UPSTREAM_BROAD_EDGES:
        pass
    elif et not in UPSTREAM_EDGE_CONTRACTS or (source["node_type"],target["node_type"]) not in UPSTREAM_EDGE_CONTRACTS[et]:
        return None
    return {
      "source_node_id":source["node_id"],
      "edge_type":et,
      "target_node_id":target["node_id"],
      "evidence":{"provenance_refs":edge["provenance_refs"],"verification_state":edge["verification_state"]},
      "attributes":edge["attributes"],
      "edge_id":edge["edge_id"],
    }
