#!/usr/bin/env python3
"""Read-only, sanitized ABVM automation health/progress observer."""
from __future__ import annotations
import argparse,hashlib,json,os,re,urllib.parse,urllib.request
from urllib.error import HTTPError
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
REPOSITORY="P00NSMASHER/abvmschoolstarworld"
PROJECT_ID="PRJ-006"
REPOSITORY_ID="REPO-003"
SOURCE_REF="main"
HEALTH_WORKFLOW_PATH=".github/workflows/health-dashboard.yml"
SHA40=re.compile(r"^[0-9a-f]{40}$")

class AbvmHealthError(ValueError): pass
def req(ok:bool,msg:str)->None:
    if not ok: raise AbvmHealthError(msg)
def canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v:Any)->str:
    return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def _boundary()->dict[str,Any]:
    policy=json.loads((ROOT/"governance/boundaries.json").read_text(encoding="utf-8"))
    cap=next(x for x in policy["project_capabilities"] if x["project_id"]==PROJECT_ID)
    constrained=policy["constrained_integrations"][PROJECT_ID]
    req(cap["READ_OBSERVE"]["allowed"] is True and cap["READ_OBSERVE"]["repository_ids"]==[REPOSITORY_ID],"ABVM observation capability denied")
    req(cap["CANDIDATE_PR"]["allowed"] is False and cap["DEPLOY"]["allowed"] is False and cap["EXTERNAL_ACTION"]["allowed"] is False,"ABVM gained write/deploy/external authority")
    req(set(constrained["allowed_evidence"])=={"AUTOMATION_HEALTH","PROGRESS_EVIDENCE"},"ABVM evidence scope widened")
    req(constrained["child_facing_mutation"] is False and constrained["deployment_authority"] is False and constrained["school_content_publication_authority"] is False,"ABVM constrained boundary widened")
    return constrained

def build_evidence(source_revision:str,runs:list[dict[str,Any]],*,observed_at:str)->dict[str,Any]:
    _boundary()
    req(isinstance(source_revision,str) and SHA40.fullmatch(source_revision) is not None,"ABVM source revision must be exact SHA")
    req(isinstance(runs,list),"ABVM workflow runs must be a list")
    exact=[
        r for r in runs if isinstance(r,dict)
        and r.get("path")==HEALTH_WORKFLOW_PATH
        and r.get("head_branch")==SOURCE_REF
        and r.get("head_sha")==source_revision
    ]
    exact.sort(key=lambda r:(int(r.get("run_number") or 0),int(r.get("run_attempt") or 0),int(r.get("id") or 0)),reverse=True)
    run=exact[0] if exact else None
    if run is None:
        health="BLOCKED_NO_EXACT_HEAD_HEALTH_RUN"
        progress="SOURCE_REVISION_OBSERVED_HEALTH_RUN_MISSING"
        run_fields={
          "source_run_id":None,"source_run_number":None,"source_run_attempt":None,
          "source_run_status":None,"source_run_conclusion":None,"source_run_head_sha":None,
          "source_workflow_name":"ABVM Operational Health Dashboard",
          "source_workflow_path":HEALTH_WORKFLOW_PATH,
          "source_run_created_at":None,"source_run_updated_at":None,
        }
        sequence=None
    else:
        req(type(run.get("id")) is int and type(run.get("run_number")) is int,"ABVM workflow run identity invalid")
        req(run.get("status") in {"queued","in_progress","completed","pending","waiting","requested"},"ABVM workflow status invalid")
        conclusion=run.get("conclusion")
        if run["status"]=="completed" and conclusion=="success":
            health="HEALTHY"
        elif run["status"]=="completed":
            health="DEGRADED"
        else:
            health="IN_PROGRESS"
        progress="EXACT_HEAD_HEALTH_RUN_OBSERVED"
        run_fields={
          "source_run_id":run["id"],"source_run_number":run["run_number"],"source_run_attempt":int(run.get("run_attempt") or 1),
          "source_run_status":run["status"],"source_run_conclusion":conclusion,"source_run_head_sha":run["head_sha"],
          "source_workflow_name":run.get("name"),"source_workflow_path":run["path"],
          "source_run_created_at":run.get("created_at"),"source_run_updated_at":run.get("updated_at"),
        }
        sequence=run["run_number"]
    core={
      "schema_version":"1.0.0","status":"PASS","project_id":PROJECT_ID,"repository_id":REPOSITORY_ID,
      "source_repository":REPOSITORY,"source_ref":SOURCE_REF,"source_revision":source_revision,
      "observed_at":observed_at,"observation_method":"GITHUB_ACTIONS_READ_ONLY",
      "evidence_scope":["AUTOMATION_HEALTH","PROGRESS_EVIDENCE"],
      "automation_health":health,"automation_progress":progress,
      "source_sequence":sequence,**run_fields,
      "payload_scope":"SANITIZED_OPERATIONAL_METADATA_ONLY",
      "content_body_included":False,"child_data_included":False,
      "authority_granted":False,"mutation_performed":False,"deploy_authority":False,
      "external_action_authority":False,"child_facing_mutation_authority":False,
      "school_content_publication_authority":False,
      "technical_verification_credit":False,"market_verification_credit":False,"revenue_verification_credit":False,
    }
    state_basis={k:core[k] for k in (
      "source_repository","source_ref","source_revision","source_run_id","source_run_number",
      "source_run_status","source_run_conclusion","source_run_head_sha","automation_health","automation_progress"
    )}
    core["source_state_hash"]=hashv(state_basis)
    core["receipt_hash"]=hashv(core)
    return core

def _get_json(url:str)->Any:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    def request(use_token:bool):
        headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-abvm-observer/1.0"}
        if use_token and token: headers["Authorization"]=f"Bearer {token}"
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers,method="GET"),timeout=20) as response:
            return json.loads(response.read().decode())
    try:
        return request(True)
    except HTTPError as exc:
        if token and exc.code in {401,403,404}:
            return request(False)
        raise

def fetch_live_evidence(*,observed_at:str|None=None)->dict[str,Any]:
    base="https://api.github.com/repos/"+REPOSITORY
    head=_get_json(base+"/commits/"+urllib.parse.quote(SOURCE_REF,safe=""))["sha"]
    req(isinstance(head,str) and SHA40.fullmatch(head) is not None,"ABVM GitHub head invalid")
    workflow=urllib.parse.quote("health-dashboard.yml",safe="")
    payload=_get_json(base+"/actions/workflows/"+workflow+"/runs?branch="+SOURCE_REF+"&per_page=20")
    runs=payload.get("workflow_runs")
    req(isinstance(runs,list),"ABVM GitHub workflow response invalid")
    return build_evidence(head,runs,observed_at=observed_at or now_iso())

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",default="runtime/out/abvm_health_progress_evidence.json")
    args=ap.parse_args()
    evidence=fetch_live_evidence()
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
      "status":evidence["status"],"source_revision":evidence["source_revision"],
      "source_run_id":evidence["source_run_id"],"automation_health":evidence["automation_health"],
      "automation_progress":evidence["automation_progress"],"authority_granted":False
    },sort_keys=True))

if __name__=="__main__":
    main()
