#!/usr/bin/env python3
"""Bounded REPO-001 scout intake for the existing Portfolio Brain Hunter.

This is not a second Hunter. It reads one pre-verification scout queue at an
exact source revision and emits only candidate hints. Existing Hunter inspection,
rights handling, ranking, proposal gating, and independent verification remain
authoritative.
"""
from __future__ import annotations
import argparse,base64,hashlib,json,os,re,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY="P00NSMASHER/github-value-hunt-ledger"
SOURCE_PATH="intelligence/scout_queue/HUNTER-01.json"
SOURCE_REF="main"
STATE_ID="portfolio-repo-scout-intake-state"
MAX_INTAKE=2
MIN_TRIAGE_SCORE=35
WORKER_PROJECTS={"HUNTER-01":["PRJ-005"]}
SHA40=re.compile(r"^[0-9a-f]{40}$")

class ScoutIntakeError(ValueError): pass
def req(ok,msg):
    if not ok: raise ScoutIntakeError(msg)
def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v): return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def now_iso(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def seed_state(): return json.loads((ROOT/"hunting/REPO_SCOUT_INTAKE_STATE_SEED.json").read_text())

def validate_state(state):
    req(isinstance(state,dict) and set(state)=={"schema_version","state_id","sequence","updated_at","source_keys","candidate_keys"},"scout intake state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,"scout intake state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"scout intake sequence invalid")
    req(state["updated_at"] is None or isinstance(state["updated_at"],str),"scout intake updated_at invalid")
    for name in ("source_keys","candidate_keys"):
        rows=state[name]
        req(isinstance(rows,list) and len(rows)<=4096 and len(rows)==len(set(rows)),f"scout intake {name} invalid")
        req(all(isinstance(x,str) and x.startswith("sha256:") for x in rows),f"scout intake {name} key invalid")

def load_state(path=None):
    if path is not None and Path(path).exists(): state=json.loads(Path(path).read_text())
    else: state=seed_state()
    validate_state(state); return state

def _candidate_identity(row):
    return hashv({"repository":row["repository"].casefold(),"exact_revision":row["exact_revision"]})

def build_intake(queue,*,source_revision,source_path=SOURCE_PATH,prior_state=None,at=None):
    state=json.loads(json.dumps(prior_state if prior_state is not None else seed_state()));validate_state(state)
    at=at or now_iso()
    req(isinstance(source_revision,str) and SHA40.fullmatch(source_revision) is not None,"scout source revision must be exact SHA")
    req(source_path==SOURCE_PATH,"scout source path is not allowlisted")
    req(isinstance(queue,dict) and queue.get("schema_version")==2,"scout queue schema mismatch")
    req(queue.get("authority")=="PRE_VERIFICATION_DISCOVERY_ONLY","scout queue authority widened")
    worker=queue.get("worker_id");req(worker in WORKER_PROJECTS,"scout worker is not allowlisted")
    candidates=queue.get("candidates");req(isinstance(candidates,list),"scout candidate list invalid")
    eligible=[]
    for row in candidates:
        if not isinstance(row,dict): continue
        if row.get("status")!="PRE_VERIFICATION_CANDIDATE" or row.get("archived") is not False: continue
        repo_name=row.get("repository");revision=row.get("exact_revision");score=row.get("triage_score")
        license_spdx=row.get("published_license_spdx")
        roots=row.get("root_code_signals")
        if not (isinstance(repo_name,str) and "/" in repo_name and isinstance(revision,str) and SHA40.fullmatch(revision)): continue
        if type(score) is not int or score<MIN_TRIAGE_SCORE: continue
        if license_spdx is not None and not isinstance(license_spdx,str): continue
        if not isinstance(roots,list) or not roots: continue
        candidate_key=_candidate_identity(row)
        source_key=hashv({"source_repository":SOURCE_REPOSITORY,"source_revision":source_revision,"source_path":source_path,
                          "finding_identity":candidate_key})
        if source_key in state["source_keys"] or candidate_key in state["candidate_keys"]: continue
        eligible.append((score,repo_name,revision,candidate_key,source_key,row))
    eligible.sort(key=lambda x:(-x[0],x[1].casefold(),x[2]))
    selected=eligible[:MAX_INTAKE]
    hints=[]
    for score,repo_name,revision,candidate_key,source_key,row in selected:
        hints.append({
          "source_repository":SOURCE_REPOSITORY,"source_revision":source_revision,"source_path":source_path,
          "source_key":source_key,"finding_identity":candidate_key,
          "worker_id":worker,"project_ids":WORKER_PROJECTS[worker],
          "repository_full_name":repo_name,"exact_revision":revision,
          "published_license_spdx":license_spdx,"triage_score":score,
          "status":"ELIGIBLE_FOR_EXISTING_HUNTER_INSPECTION",
          "authority_class":"OBSERVE","rights_granted":False,"value_verified":False,
          "reuse_authority_granted":False
        })
    if hints:
        state["sequence"]+=1;state["updated_at"]=at
        state["source_keys"]=list(dict.fromkeys([*state["source_keys"],*(x["source_key"] for x in hints)]))[-4096:]
        state["candidate_keys"]=list(dict.fromkeys([*state["candidate_keys"],*(x["finding_identity"] for x in hints)]))[-4096:]
    validate_state(state)
    receipt={"schema_version":"1.0.0","status":"PASS","source_repository":SOURCE_REPOSITORY,"source_revision":source_revision,
             "source_path":source_path,"worker_id":worker,"input_candidates":len(candidates),"eligible_candidates":len(eligible),
             "selected_candidates":len(hints),"max_intake":MAX_INTAKE,"hints":hints,
             "license_policy_ref":"hunting/LICENSE_ADMISSION_POLICY.json","license_based_blocking":False,
             "authority_granted":False,"rights_granted":False,"value_verified":False}
    receipt["receipt_hash"]=hashv(receipt)
    return state,receipt

def _get_json(url):
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-repo-scout-intake/1.0"}
    if token: headers["Authorization"]=f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers,method="GET"),timeout=20) as response:
        return json.loads(response.read().decode())

def fetch_queue():
    base="https://api.github.com/repos/"+SOURCE_REPOSITORY
    head=_get_json(base+"/commits/"+urllib.parse.quote(SOURCE_REF,safe=""))["sha"]
    req(isinstance(head,str) and SHA40.fullmatch(head) is not None,"scout repository returned invalid head")
    payload=_get_json(base+"/contents/"+urllib.parse.quote(SOURCE_PATH,safe="/")+"?ref="+head)
    req(payload.get("encoding")=="base64" and isinstance(payload.get("content"),str),"scout queue content encoding invalid")
    raw=base64.b64decode(payload["content"])
    req(len(raw)<=1_048_576,"scout queue exceeds byte budget")
    return head,json.loads(raw.decode("utf-8"))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--state",default="hunting/live/repo_scout_intake_state.json");ap.add_argument("--output-dir",default="hunting/out");a=ap.parse_args()
    state=load_state(a.state);revision,queue=fetch_queue();state,receipt=build_intake(queue,source_revision=revision,prior_state=state)
    out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/"repo_scout_intake_state.json").write_text(json.dumps(state,indent=2,sort_keys=True)+"\n")
    (out/"repo_scout_intake.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":receipt["status"],"source_revision":revision,"selected":receipt["selected_candidates"]},sort_keys=True))
if __name__=="__main__": main()
