#!/usr/bin/env python3
"""Deterministic autonomous Step 8 observation runtime."""
from __future__ import annotations
import argparse, hashlib, json, os, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adapters.github_readonly import GitHubReadOnlyClient, observe_repository
from runtime.state import advance_cycle, bootstrap_state, canonical_hash, load_json, validate_state
from learning.continuous_learning import rebuild_from_ledger

ROOT=Path(__file__).resolve().parents[1]

class RuntimePolicyError(RuntimeError): pass

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def load_policy()->dict[str,Any]:
    return load_json(ROOT/"runtime"/"RUNTIME_POLICY.json")

def killed()->tuple[bool,str|None]:
    ks=load_json(ROOT/"runtime"/"KILL_SWITCH.json")
    if ks.get("disabled") is True:
        return True, ks.get("reason") or "file kill switch"
    if os.environ.get("PORTFOLIO_RUNTIME_DISABLED","").strip().lower()=="true":
        return True, "repository/environment kill switch"
    return False,None

class RequestBudget:
    def __init__(self, fetch, *, limit: int, retries: int, backoff: float):
        self.fetch=fetch; self.limit=limit; self.retries=retries; self.backoff=backoff; self.used=0
    def __call__(self,url: str)->dict[str,Any]:
        last=None
        for attempt in range(self.retries+1):
            if self.used>=self.limit: raise RuntimePolicyError("GitHub API request budget exceeded")
            self.used+=1
            try: return self.fetch(url)
            except Exception as exc:
                last=exc
                if attempt<self.retries: time.sleep(self.backoff*(attempt+1))
        raise RuntimePolicyError(f"GitHub read failed after bounded retries: {last}")

def load_runtime_state(path: Path, *, now: str)->dict[str,Any]:
    if path.exists():
        state=load_json(path); validate_state(state); return state
    return bootstrap_state(now=now)

def _repo_cursor(state: dict[str,Any], rid: str)->dict[str,Any]:
    item=state["repositories"][rid]
    return {"source_ref":item["source_ref"],"cursor_sha":item["cursor_sha"],"status":item["status"]}

def _sanitize_observation(obs: dict[str,Any], max_files: int)->dict[str,Any]:
    result=json.loads(json.dumps(obs))
    comp=result.get("compare")
    if comp and isinstance(comp.get("files"),list):
        if len(comp["files"])>max_files:
            raise RuntimePolicyError("changed-file budget exceeded for repository")
    return result

def observe(mode: str, state: dict[str,Any], *, target_repository_id: str|None, finished_at: str,
            fetch_json=None)->tuple[list[dict[str,Any]],int]:
    policy=load_policy(); budgets=policy["budgets"]
    registry=load_json(ROOT/"adapters"/"ADAPTER_REGISTRY.json")["adapters"]
    by_id={a["repository_id"]:a for a in registry}
    ids=[target_repository_id] if target_repository_id else sorted(by_id)
    if len(ids)>budgets["max_repositories_per_cycle"]:
        raise RuntimePolicyError("repository budget exceeded")
    for rid in ids:
        if rid not in by_id: raise RuntimePolicyError(f"unknown target repository: {rid}")

    if fetch_json is None:
        client=GitHubReadOnlyClient(os.environ.get("PORTFOLIO_GITHUB_TOKEN"))
        fetch_json=client.get_json
    budgeted=RequestBudget(fetch_json,limit=budgets["max_api_requests_per_cycle"],
                           retries=budgets["retry_limit"],backoff=budgets["retry_backoff_seconds"])
    observations=[]; total_files=0
    for rid in ids:
        adapter=by_id[rid]
        obs=observe_repository(adapter,_repo_cursor(state,rid),fetch_json=budgeted,observed_at=finished_at)
        obs=_sanitize_observation(obs,budgets["max_changed_files_per_repository"])
        if obs.get("compare"):
            total_files+=len(obs["compare"].get("files",[]))
            if total_files>budgets["max_total_changed_files_per_cycle"]:
                raise RuntimePolicyError("total changed-file budget exceeded")
        observations.append(obs)
    return observations,budgeted.used

def daily_snapshot(state: dict[str,Any], observations: list[dict[str,Any]], at: str)->dict[str,Any]:
    memory=load_json(ROOT/"memory"/"SHARED_VALUE_MEMORY_LEDGER.json")
    graph=load_json(ROOT/"graph"/"UNIVERSAL_GRAPH_LEDGER.json")
    return {
      "schema_version":"1.0.0","generated_at":at,
      "repository_status_counts":{
        key:sum(1 for x in observations if x["status"]==key)
        for key in ["CHANGED","UNCHANGED","INITIALIZED","BLOCKED"]
      },
      "verified_memory_outcomes":sum(1 for x in memory["outcomes"] if x.get("evidence_state")=="VERIFIED"),
      "verified_graph_nodes":sum(1 for x in graph["nodes"] if x.get("verification_state")=="VERIFIED"),
      "runtime_sequence_before_rebuild":state["sequence"],
    }

def weekly_snapshot(state: dict[str,Any], observations: list[dict[str,Any]], at: str)->dict[str,Any]:
    projects=load_json(ROOT/"registry"/"projects.json")["projects"]
    graph=load_json(ROOT/"graph"/"UNIVERSAL_GRAPH_LEDGER.json")
    memory=load_json(ROOT/"memory"/"SHARED_VALUE_MEMORY_LEDGER.json")
    return {
      "schema_version":"1.0.0","generated_at":at,
      "registered_projects":len(projects),
      "active_or_declared_repository_cursors":sum(1 for x in state["repositories"].values() if x["status"]=="CURRENT"),
      "blocked_repository_cursors":sum(1 for x in state["repositories"].values() if x["status"]!="CURRENT"),
      "graph_nodes":len(graph["nodes"]),"graph_edges":len(graph["edges"]),
      "verified_memory_outcomes":sum(1 for x in memory["outcomes"] if x.get("evidence_state")=="VERIFIED"),
      "changed_repositories_this_cycle":sum(1 for x in observations if x["status"]=="CHANGED"),
    }

def run(mode: str, *, state_path: Path, output_dir: Path, target_repository_id: str|None=None,
        fetch_json=None, forced_now: str|None=None)->dict[str,Any]:
    policy=load_policy()
    if policy["authority_class"]!="OBSERVE" or policy["model_calls_allowed"]!=0 or policy["downstream_writes_allowed"]!=0 or policy["external_actions_allowed"]!=0:
        raise RuntimePolicyError("runtime authority policy weakened")
    disabled,reason=killed()
    at=forced_now or now_iso()
    output_dir.mkdir(parents=True,exist_ok=True)
    state=load_runtime_state(state_path,now=at)
    if disabled:
        receipt={"schema_version":"1.0.0","cycle_id":"disabled","mode":mode,"started_at":at,"finished_at":at,
                 "status":"DISABLED","reason":reason,"observations":[],"api_requests":0}
        receipt["receipt_hash"]=canonical_hash(receipt)
        (output_dir/"runtime_state.json").write_text(json.dumps(state,indent=2)+"\n")
        (output_dir/"cycle_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
        return receipt
    started=time.monotonic()
    target=target_repository_id if mode=="observe" else None
    observations,api_requests=observe(mode,state,target_repository_id=target,finished_at=at,fetch_json=fetch_json)
    if time.monotonic()-started>policy["budgets"]["max_runtime_seconds"]:
        raise RuntimePolicyError("runtime time budget exceeded")
    seed={"mode":mode,"target_repository_id":target,"prior_sequence":state["sequence"],
          "prior_cursors":{k:v["cursor_sha"] for k,v in sorted(state["repositories"].items())},
          "observed_heads":{x["repository_id"]:x.get("current_sha") for x in observations}}
    cycle_id="cycle-"+hashlib.sha256(json.dumps(seed,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24]
    receipt={"schema_version":"1.0.0","cycle_id":cycle_id,"mode":mode,"started_at":at,"finished_at":at,
             "status":"PASS","reason":None,"observations":observations,"api_requests":api_requests}
    receipt["receipt_hash"]=canonical_hash(receipt)
    updated=advance_cycle(state,receipt)

    if mode=="daily":
        learning_state=rebuild_from_ledger()
        (output_dir/"portfolio_learning_state.json").write_text(json.dumps(learning_state,indent=2)+"\n")
        snap=daily_snapshot(updated,observations,at)
        snap["portfolio_learning_state_hash"]=learning_state["state_hash"]
        snap["snapshot_hash"]=canonical_hash(snap)
        updated["daily_learning_state"]={"generated_at":at,"snapshot_hash":snap["snapshot_hash"],"portfolio_learning_state_hash":learning_state["state_hash"]}
        (output_dir/"daily_learning_state.json").write_text(json.dumps(snap,indent=2)+"\n")
    elif mode=="weekly":
        snap=weekly_snapshot(updated,observations,at); snap["snapshot_hash"]=canonical_hash(snap)
        updated["weekly_synthesis"]={"generated_at":at,"snapshot_hash":snap["snapshot_hash"]}
        (output_dir/"weekly_portfolio_synthesis.json").write_text(json.dumps(snap,indent=2)+"\n")

    validate_state(updated)
    (output_dir/"runtime_state.json").write_text(json.dumps(updated,indent=2)+"\n")
    (output_dir/"cycle_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    total=sum(p.stat().st_size for p in output_dir.iterdir() if p.is_file())
    if total>policy["budgets"]["max_output_bytes"]:
        raise RuntimePolicyError("runtime output byte budget exceeded")
    return receipt

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",choices=["observe","sync","daily","weekly"],required=True)
    ap.add_argument("--state-path",default="runtime/live/runtime_state.json")
    ap.add_argument("--output-dir",default="runtime/out")
    ap.add_argument("--target-repository-id",default=None)
    args=ap.parse_args()
    receipt=run(args.mode,state_path=Path(args.state_path),output_dir=Path(args.output_dir),
                target_repository_id=(args.target_repository_id or None))
    print(json.dumps({"cycle_id":receipt["cycle_id"],"mode":receipt["mode"],"status":receipt["status"],
                      "api_requests":receipt["api_requests"],"observations":len(receipt["observations"])}))
if __name__=="__main__": main()
