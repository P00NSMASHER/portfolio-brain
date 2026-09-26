#!/usr/bin/env python3
"""Governed model-assisted analysis for daily/weekly Portfolio Brain cycles.

Deterministic runtime remains authoritative for state/evidence construction.
This layer consumes only sanitized deterministic outputs, never grants
authority, never upgrades evidence, and writes advisory analysis + receipts.
"""
from __future__ import annotations
import argparse,hashlib,json,os
from pathlib import Path
from typing import Any,Callable

from cost_governor.cost_governor import load_state as load_cost_state
from model_router.openai_executor import OpenAIExecutorError,execute_openai

ROOT=Path(__file__).resolve().parents[1]
class ModelAnalysisError(ValueError):pass

def req(ok,msg):
    if not ok: raise ModelAnalysisError(msg)

def load(path):
    p=Path(path)
    if not p.is_absolute(): p=ROOT/p
    return json.loads(p.read_text())

def policy(): return load("runtime/RUNTIME_POLICY.json")

def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha(v): return "sha256:"+hashlib.sha256((v if isinstance(v,str) else canon(v)).encode()).hexdigest()

def _selected_uncertainty():
    from uncertainty.highest_value_uncertainty import build_snapshot
    s=build_snapshot()
    c=next(x for x in s["candidates"] if x["uncertainty_id"]==s["selected_uncertainty_id"])
    return {
      "uncertainty_id":c["uncertainty_id"],"question":c["question"],
      "project_ids":c["project_ids"],"components":{k:v["value"] for k,v in c["components"].items()},
      "authority_requirement":c["authority_requirement"],"actionability":c["actionability"],
      "approval_requirements":c["approval_requirements"],"evidence_refs":c["evidence_refs"]
    }

def _experiment_summary():
    from uncertainty.highest_value_uncertainty import build_snapshot
    from experiments.experiment_engine import build_experiment_portfolio
    p=build_experiment_portfolio(build_snapshot())
    selected=next(x for x in p["plans"] if x["experiment_id"]==p["selected_experiment_id"])
    return {
      "plan_count":p["plan_count"],"status_counts":p["status_counts"],
      "selected_experiment_id":selected["experiment_id"],"selected_uncertainty_id":selected["uncertainty_id"],
      "status":selected["status"],"execution_mode":selected["execution_mode"],
      "autonomous_execution_allowed":selected["autonomous_execution_allowed"],
      "hypothesis":selected["hypothesis"],"success_condition":selected["success_condition"],
      "failure_condition":selected["failure_condition"],"inconclusive_condition":selected["inconclusive_condition"]
    }

def _allocation_summary():
    from allocator.portfolio_allocator import build_allocation_snapshot
    s=build_allocation_snapshot()
    rows=[]
    for p in s["plans"]:
        recs=p.get("recommendations",[])
        rows.append({
          "resource_type":p["resource_type"],"status":p["status"],
          "allocated_share_basis_points":p["allocated_share_basis_points"],
          "top_recommendations":[
            {"project_id":r["project_id"],"uncertainty_id":r["source_uncertainty_id"],
             "authority_requirement":r["authority_requirement"],"actionability":r["actionability"]}
            for r in recs[:3]
          ]
        })
    return {"active_resource_count":s["active_resource_count"],"hold_resource_count":s["hold_resource_count"],"plans":rows}

def _learning_summary():
    from learning.continuous_learning import rebuild_from_ledger
    s=rebuild_from_ledger()
    return {
      "source_observation_count":s["source_observation_count"],
      "eligible_record_count":s["eligible_record_count"],
      "policy_effect":s["policy_effect"],"state_hash":s["state_hash"]
    }

def _gmail_gateway_summary():
    p=ROOT/"action_engine"/"GMAIL_GATEWAY_LEDGER.json"
    if not p.exists(): return {"execution_count":0,"latest":None}
    j=json.loads(p.read_text());rows=j.get("executions",[])
    latest=rows[-1] if rows else None
    return {
      "execution_count":len(rows),
      "latest":None if latest is None else {
        "action_id":latest["action_id"],"project_id":latest["project_id"],
        "action_type":latest["action_type"],"status":latest["status"],"sent_at":latest["sent_at"]
      }
    }

def build_packet(mode:str,runtime_out:Path)->dict[str,Any]:
    req(mode in {"daily","weekly"},"model analysis only supports daily/weekly")
    packet={
      "schema_version":"1.0.0","mode":mode,
      "selected_uncertainty":_selected_uncertainty(),
      "experiment":_experiment_summary(),
      "allocation":_allocation_summary(),
      "learning":_learning_summary(),
      "gmail_gateway":_gmail_gateway_summary()
    }
    if mode=="daily":
        f=runtime_out/"daily_learning_state.json"
        if f.exists():
            j=json.loads(f.read_text())
            packet["deterministic_cycle"]={
              k:j.get(k) for k in [
                "repository_status_counts","verified_memory_outcomes","verified_graph_nodes",
                "transfer_assessment_ready_count","verified_transfer_success_edge_candidates",
                "repair_task_count","active_allocation_resource_count","selected_experiment_id",
                "selected_uncertainty_id","portfolio_learning_state_hash","snapshot_hash"
              ]
            }
    else:
        f=runtime_out/"weekly_portfolio_synthesis.json"
        if f.exists():
            j=json.loads(f.read_text())
            packet["deterministic_cycle"]={k:j.get(k) for k in [
              "registered_projects","active_or_declared_repository_cursors","blocked_repository_cursors",
              "graph_nodes","graph_edges","verified_memory_outcomes","changed_repositories_this_cycle","snapshot_hash"
            ]}
    return packet

def _request(mode:str,packet:dict[str,Any],at:str|None):
    cfg=policy()["governed_model_analysis"][mode]
    packet_id=sha(packet).split(":",1)[1][:12].upper()
    return {
      "schema_version":"1.0.0","request_id":f"MRQ-{mode.upper()}-{packet_id}",
      "project_ids":["PRJ-000"],"task_kind":cfg["task_kind"],"deterministic_sufficient":False,
      "consequence":cfg["consequence"],"data_classification":"SANITIZED","authority_class":"OBSERVE",
      "requires_independent_adversarial":cfg["requires_independent_adversarial"],
      "builder_independence_group":cfg["builder_independence_group"],
      "max_cost_usd":cfg["max_cost_usd"],"max_input_tokens":cfg["max_input_tokens"],
      "max_output_tokens":cfg["max_output_tokens"],"provider_allowlist":["openai"],
      "evidence_refs":[f"runtime-analysis:{mode}",sha(packet)]
    }

def _prompt(mode:str,packet:dict[str,Any])->str:
    if mode=="daily":
        mission=(
          "Act as Portfolio Brain's daily operating analyst. Identify the single highest-value bottleneck, "
          "the next 3 concrete actions, one experiment improvement, one cross-project reuse opportunity, "
          "and any evidence/authority/cost risk. Prefer actions that create verified external value over internal activity."
        )
    else:
        mission=(
          "Act as an independent adversarial weekly reviewer of Portfolio Brain. Challenge current priorities, "
          "identify hidden failure modes or wasted effort, name the highest-value correction, and propose the next "
          "week's 3 most important actions. Do not grant authority or upgrade evidence."
        )
    return mission+"\n\nReturn concise JSON with keys summary, top_bottleneck, next_actions, experiment_improvement, reuse_opportunity, risks.\n\nSANITIZED STATE:\n"+json.dumps(packet,sort_keys=True)

def run_model_analysis(mode:str,*,runtime_out:Path,cost_state_path:Path,output_dir:Path,at:str|None=None,
                       executor:Callable|None=None)->dict[str,Any]:
    cfg=policy()["governed_model_analysis"]
    req(cfg["enabled"] is True,"governed model analysis disabled")
    req(mode in {"daily","weekly"} and cfg[mode]["max_calls"]==1,"mode/model call policy mismatch")
    output_dir.mkdir(parents=True,exist_ok=True)
    packet=build_packet(mode,runtime_out)
    packet_hash=sha(packet)
    if not os.environ.get("PORTFOLIO_MODEL_API_KEY","").strip():
        status={"schema_version":"1.0.0","mode":mode,"status":"BLOCKED_MISSING_CREDENTIAL",
                "packet_hash":packet_hash,"authority_granted":False,"evidence_upgraded":False}
        (output_dir/f"{mode}_model_analysis_status.json").write_text(json.dumps(status,indent=2)+"\n")
        return status
    state=load_cost_state(cost_state_path)
    request=_request(mode,packet,at)
    fn=executor or execute_openai
    try:
        next_state,result=fn(request,_prompt(mode,packet),state,attempt=1,
                             reasoning_effort=cfg[mode]["reasoning_effort"],at=at)
    except OpenAIExecutorError as exc:
        if exc.gate_status=="DUPLICATE_SUPPRESSED":
            status_name="SKIPPED_DUPLICATE_PACKET"
        elif exc.retryable:
            status_name="DEFERRED_PROVIDER_RETRY"
        elif exc.status_code==429 and (exc.provider_code=="billing_not_active" or exc.provider_type=="billing_not_active"):
            status_name="BLOCKED_PROVIDER_BILLING"
        elif exc.status_code==429 and (exc.provider_code in {
            "credit_balance_exhausted","organization_spend_limit_exceeded",
            "project_spend_limit_exceeded","organization_usage_limit_exceeded","insufficient_quota"
        } or exc.provider_type=="insufficient_quota"):
            status_name="BLOCKED_PROVIDER_QUOTA"
        else:
            status_name="BLOCKED_PROVIDER_ERROR"
        status={
          "schema_version":"1.0.0","mode":mode,"status":status_name,
          "packet_hash":packet_hash,"provider_status_code":exc.status_code,
          "provider_code":exc.provider_code,"provider_type":exc.provider_type,
          "retryable":exc.retryable,"retry_after_seconds":exc.retry_after,
          "cost_gate_status":exc.gate_status,"reason_codes":exc.reason_codes,
          "authority_granted":False,"evidence_upgraded":False
        }
        (output_dir/f"{mode}_model_analysis_status.json").write_text(json.dumps(status,indent=2)+"\n")
        return status
    cost_state_path.write_text(json.dumps(next_state,indent=2)+"\n")
    receipt=result["receipt"]
    advisory={
      "schema_version":"1.0.0","mode":mode,"status":"SUCCESS","packet_hash":packet_hash,
      "route":{"tier":result["route"]["tier"],"provider_id":result["route"]["provider_id"],
               "model_id":result["route"]["model_id"],"route_id":result["route"]["route_id"]},
      "receipt":receipt,"analysis_text":result["output_text"],
      "authority_granted":False,"evidence_upgraded":False
    }
    (output_dir/f"{mode}_model_analysis.json").write_text(json.dumps(advisory,indent=2)+"\n")
    return advisory

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",choices=["daily","weekly"],required=True)
    ap.add_argument("--runtime-out",default="runtime/out")
    ap.add_argument("--cost-state",default="cost_governor/out/cost_state.json")
    ap.add_argument("--output-dir",default="runtime/out")
    a=ap.parse_args()
    r=run_model_analysis(a.mode,runtime_out=Path(a.runtime_out),cost_state_path=Path(a.cost_state),output_dir=Path(a.output_dir))
    print(json.dumps({"mode":a.mode,"status":r["status"],"authority_granted":False,"evidence_upgraded":False},sort_keys=True))

if __name__=="__main__":main()
