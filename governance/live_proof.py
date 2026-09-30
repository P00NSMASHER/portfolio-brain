#!/usr/bin/env python3
from __future__ import annotations
import argparse,base64,json,os
from pathlib import Path
from adapters.github_readonly import GitHubReadOnlyClient,observe_repository
from adapters.project_forwarder import forward_observation,load_seed_state as forwarding_seed
from adapters.abvm_observer import build_abvm_evidence
from hunting.autonomous_hunter import GitHubPublicProvider,load_seed_state as hunter_seed
from hunting.repo_scout_intake import ingest_queue,load_seed_state as intake_seed
ROOT=Path(__file__).resolve().parents[1]
def _load(p):return json.loads((ROOT/p).read_text())
def _adapter(i):return next(x for x in _load("adapters/ADAPTER_REGISTRY.json")["adapters"] if x["adapter_id"]==i)
def _health(r):
 if r is None:return "UNKNOWN"
 if r.get("status")!="completed":return "RUNNING"
 return "HEALTHY" if r.get("conclusion")=="success" else "DEGRADED"
def run(at):
 token=os.environ.get("GITHUB_TOKEN");client=GitHubReadOnlyClient(token=token);fetch=lambda u:client.get_json(u,timeout=15)
 brain=observe_repository(_adapter("ADP-008"),None,fetch_json=fetch,observed_at=at);d=[];s,a=forward_observation("PRJ-000",brain,forwarding_seed(),d.append);s,b=forward_observation("PRJ-000",brain,s,d.append)
 if len(d)!=1 or a["status"]!="FORWARDED" or b["status"]!="DUPLICATE_SUPPRESSED":raise RuntimeError("Step 13 exact-once proof failed")
 ar=observe_repository(_adapter("ADP-003"),None,fetch_json=fetch,observed_at=at);runs=fetch("https://api.github.com/repos/P00NSMASHER/abvmschoolstarworld/actions/runs?per_page=1");lr=(runs.get("workflow_runs") or [None])[0]
 ae=build_abvm_evidence(ar,automation_health=_health(lr),progress={"latest_run_id":None if lr is None else lr.get("id"),"latest_run_status":None if lr is None else lr.get("status"),"latest_run_conclusion":None if lr is None else lr.get("conclusion"),"source_sequence":1,"source_revision":ar["current_sha"]})
 sh=fetch("https://api.github.com/repos/P00NSMASHER/github-value-hunt-ledger/commits/main")["sha"];raw=fetch("https://api.github.com/repos/P00NSMASHER/github-value-hunt-ledger/contents/intelligence/scout_queue/HUNTER-01.json?ref="+sh);q=json.loads(base64.b64decode(raw["content"]).decode());provider=GitHubPublicProvider(token=token)
 ist,r=ingest_queue(queue=q,source_revision=sh,source_path="intelligence/scout_queue/HUNTER-01.json",hunter_state=hunter_seed(),provider=provider,intake_state=intake_seed(),at=at);_,rr=ingest_queue(queue=q,source_revision=sh,source_path="intelligence/scout_queue/HUNTER-01.json",hunter_state=hunter_seed(),provider=provider,intake_state=ist,at=at)
 if r["inspected_candidates"]!=1 or not r["admitted"] or rr["inspected_candidates"]!=0 or not rr["duplicates"]:raise RuntimeError("Step 14 live intake/dedupe proof failed")
 return {"schema_version":"1.0.0","proof_id":"steps13-15-controlled-live-proof-v1","status":"PASS","captured_at":at,"authority_class":"OBSERVE","network_method":"GITHUB_API_GET_ONLY","step13":{"forwarded_exactly_once":True,"deliveries":len(d),"duplicate_status":b["status"],"source_revision":brain["current_sha"]},"step14":{"source_repository":"REPO-001","source_revision":sh,"source_path":r["source_path"],"inspected_candidates":r["inspected_candidates"],"admitted_count":len(r["admitted"]),"repeat_duplicate_count":len(rr["duplicates"]),"downstream_write_authority":False},"step15":{"project_id":"PRJ-006","source_revision":ae["source_revision"],"automation_health":ae["automation_health"],"evidence_scope":ae["evidence_scope"],"child_facing_mutation_authority":False,"deployment_authority":False,"school_content_publication_authority":False},"technical_verification_created":False,"market_verification_created":False,"revenue_verification_created":False}
def main():
 p=argparse.ArgumentParser();p.add_argument("--at",required=True);p.add_argument("--output",required=True);a=p.parse_args();o=run(a.at);x=Path(a.output);x.parent.mkdir(parents=True,exist_ok=True);x.write_text(json.dumps(o,indent=2,sort_keys=True)+"\n");print(json.dumps(o,sort_keys=True))
if __name__=="__main__":main()
