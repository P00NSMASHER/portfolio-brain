#!/usr/bin/env python3
"""Live collector for the bounded Step 22 autonomous self-repair proof."""
from __future__ import annotations
import argparse, base64, hashlib, json, os, re, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from acceptance.step22_finalize import build_receipt

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def hv(v:Any)->str:
    return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()

class GH:
    def __init__(self,repo:str,token:str):
        self.repo=repo;self.base="https://api.github.com/repos/"+repo;self.token=token
    def call(self,path:str,*,method="GET",payload=None):
        url=path if path.startswith("https://") else self.base+path
        data=None if payload is None else json.dumps(payload).encode()
        req=urllib.request.Request(url,data=data,method=method,headers={
          "Authorization":"Bearer "+self.token,"Accept":"application/vnd.github+json",
          "X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-step22-finalizer/1.0",
          "Content-Type":"application/json",
        })
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read()
            return {} if not raw else json.loads(raw)
    def get(self,path): return self.call(path)
    def post(self,path,payload): return self.call(path,method="POST",payload=payload)

def wait_until(fn,*,deadline:float,desc:str,interval:float=5.0):
    last=None
    while time.monotonic()<deadline:
        try:
            val=fn()
            if val is not None:return val
            last=None
        except Exception as exc:
            last=exc
        time.sleep(interval)
    if last is not None: raise RuntimeError(desc+" timed out; last error="+type(last).__name__+":"+str(last))
    raise RuntimeError(desc+" timed out")

def artifact_hashes(gh:GH,run_id:int)->list[str]:
    doc=gh.get(f"/actions/runs/{run_id}/artifacts?per_page=100")
    return sorted({a["digest"] for a in doc.get("artifacts",[]) if isinstance(a.get("digest"),str) and a["digest"].startswith("sha256:")})

def select_trusted_check(checks:list[dict[str,Any]],*,name:str,app_id:int,head_sha:str)->dict[str,Any]:
    rows=[
      x for x in checks
      if x.get("name")==name
      and x.get("app",{}).get("id")==app_id
      and x.get("head_sha")==head_sha
      and x.get("status")=="completed"
      and isinstance(x.get("completed_at"),str)
    ]
    successful=[x for x in rows if x.get("conclusion")=="success"]
    if not successful:
        raise RuntimeError("Step22 trusted check missing: "+name)
    key=lambda x:(x["completed_at"],int(x.get("id") or 0))
    chosen=max(successful,key=key)
    later_non_success=[
      x for x in rows
      if key(x)>key(chosen) and x.get("conclusion")!="success"
    ]
    if later_non_success:
        raise RuntimeError("Step22 trusted check superseded by non-success: "+name)
    return {
      "check_run_id":chosen["id"],"name":name,"app_id":app_id,
      "head_sha":head_sha,"conclusion":"success","completed_at":chosen["completed_at"],
    }

STEP22_MAINTENANCE_EXACT_PATHS = {
    "state_journal/ARCHIVE_MANIFEST.json",
    "state_journal/CHECKPOINT.json.gz",
    "state_journal/POLICY.json",
}
STEP22_MAINTENANCE_PREFIXES = ("state_journal/archive/",)


def verify_maintenance_pr(gh:GH, *, pr_number:int, expected_base_sha:str)->dict[str,Any]:
    pr=gh.get(f"/pulls/{pr_number}")
    if not pr.get("merged_at"):
        raise RuntimeError("Step22 maintenance PR is not merged")
    actor=pr.get("user",{}).get("login") or ""
    branch=pr.get("head",{}).get("ref") or ""
    base_sha=pr.get("base",{}).get("sha")
    head_sha=pr.get("head",{}).get("sha")
    merge_sha=pr.get("merge_commit_sha")
    if base_sha!=expected_base_sha:
        raise RuntimeError("Step22 maintenance lineage base mismatch")
    if not all(isinstance(x,str) and re.fullmatch(r"[0-9a-f]{40}",x) for x in (head_sha,merge_sha)):
        raise RuntimeError("Step22 maintenance Git identity invalid")
    files=gh.get(f"/pulls/{pr_number}/files?per_page=100")
    changed=[row["filename"] for row in files]
    if not changed or len(changed)!=len(set(changed)):
        raise RuntimeError("Step22 maintenance changed paths invalid")
    checks=gh.get(f"/commits/{head_sha}/check-runs?per_page=100").get("check_runs",[])
    foundation=select_trusted_check(checks,name="validate",app_id=15368,head_sha=head_sha)
    hosted=select_trusted_check(checks,name="portfolio-phase1-gate",app_id=5121826,head_sha=head_sha)

    common={
      "pr_number":pr_number,
      "actor_login":actor,
      "branch":branch,
      "base_sha":base_sha,
      "head_sha":head_sha,
      "merge_sha":merge_sha,
      "changed_paths":changed,
      "foundation_check":foundation,
      "hosted_verifier_check":hosted,
      "merged_at":pr["merged_at"],
      "protected_merge":True,
      "authority_granted":False,
      "evidence_upgraded":False,
    }
    if changed==["state_journal/TRIGGER_CHECKPOINT_ARCHIVE"]:
        return {"kind":"CHECKPOINT_ARCHIVE_TRIGGER",**common}

    for changed_path in changed:
        if not (
            changed_path in STEP22_MAINTENANCE_EXACT_PATHS
            or any(changed_path.startswith(prefix) for prefix in STEP22_MAINTENANCE_PREFIXES)
        ):
            raise RuntimeError("Step22 checkpoint maintenance touched non-archive path: "+changed_path)
    if not STEP22_MAINTENANCE_EXACT_PATHS.issubset(set(changed)):
        raise RuntimeError("Step22 checkpoint maintenance omitted required control files")
    if not any(x.startswith("state_journal/archive/") for x in changed):
        raise RuntimeError("Step22 checkpoint maintenance contains no immutable archive file")
    if actor!="github-actions[bot]" or not branch.startswith("checkpoint/archive-"):
        raise RuntimeError("Step22 archive maintenance identity invalid")
    run_match=re.fullmatch(r"checkpoint/archive-(\d+)",branch)
    if not run_match:
        raise RuntimeError("Step22 checkpoint maintenance run identity missing")
    workflow_run_id=int(run_match.group(1))
    run=gh.get(f"/actions/runs/{workflow_run_id}")
    if run.get("name")!="portfolio-state-checkpoint-candidate" or run.get("conclusion")!="success":
        raise RuntimeError("Step22 checkpoint maintenance workflow did not succeed")
    if run.get("head_sha")!=expected_base_sha:
        raise RuntimeError("Step22 checkpoint maintenance workflow base mismatch")
    manifest_doc=gh.get(f"/contents/state_journal/ARCHIVE_MANIFEST.json?ref={merge_sha}")
    raw=base64.b64decode(manifest_doc["content"])
    manifest=json.loads(raw.decode("utf-8"))
    archive_id=manifest.get("archive_id")
    checkpoint_sequence=manifest.get("checkpoint_sequence")
    if not (isinstance(archive_id,str) and archive_id.startswith("canonical-archive-seq-")):
        raise RuntimeError("Step22 checkpoint maintenance archive identity invalid")
    if type(checkpoint_sequence) is not int or checkpoint_sequence<=0:
        raise RuntimeError("Step22 checkpoint maintenance checkpoint sequence invalid")
    return {
      "kind":"CHECKPOINT_ARCHIVE_MAINTENANCE",
      "workflow_run_id":workflow_run_id,
      "archive_id":archive_id,
      "checkpoint_sequence":checkpoint_sequence,
      **common,
    }

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--fingerprint",required=True);ap.add_argument("--fault-receipt-hash",required=True)
    ap.add_argument("--fault-detected-at",required=True);ap.add_argument("--fault-base-sha",required=True)
    ap.add_argument("--dispatch-run-id",type=int,required=True);ap.add_argument("--dispatched-at",required=True)
    ap.add_argument("--output-meta",type=Path,required=True);ap.add_argument("--output-receipt",type=Path,required=True)
    ap.add_argument("--maintenance-pr-number",type=int,action="append",default=[])
    ap.add_argument("--timeout-seconds",type=int,default=1500)
    args=ap.parse_args()
    repo=os.environ["GITHUB_REPOSITORY"];token=os.environ["GITHUB_TOKEN"];gh=GH(repo,token)
    deadline=time.monotonic()+args.timeout_seconds
    marker="AUTO_REPAIR_FINGERPRINT:"+args.fingerprint

    def find_pr():
        pulls=gh.get("/pulls?state=all&per_page=100&sort=created&direction=desc")
        rows=[p for p in pulls if marker in (p.get("body") or "")]
        if len(rows)>1: raise RuntimeError("multiple Step22 repair PRs for exact fingerprint")
        return rows[0] if rows else None
    pr=wait_until(find_pr,deadline=deadline,desc="autonomous Step22 repair PR")
    prn=pr["number"];initial_head=pr["head"]["sha"];branch=pr["head"]["ref"]
    if pr.get("user",{}).get("login")!="github-actions[bot]": raise RuntimeError("Step22 repair PR is not bot-created")
    if not branch.startswith("factory/auto-repair-"): raise RuntimeError("Step22 repair PR branch not isolated")
    body=pr.get("body") or ""
    m=re.search(r"Factory work:\s*(AUTO-REPAIR-[A-F0-9]+-(\d+))",body)
    if not m: raise RuntimeError("Step22 factory work/run identity missing")
    repair_run_id=int(m.group(2))
    run=wait_until(lambda: (lambda x:x if x.get("status")=="completed" else None)(gh.get(f"/actions/runs/{repair_run_id}")),deadline=deadline,desc="Step22 autonomous repair workflow")
    if run.get("conclusion")!="success": raise RuntimeError("Step22 autonomous repair workflow failed")
    jobs=gh.get(f"/actions/runs/{repair_run_id}/jobs?per_page=100").get("jobs",[])
    byname={j.get("name"):j for j in jobs}
    if byname.get("repair",{}).get("conclusion")!="success" or byname.get("factory-review",{}).get("conclusion")!="success":
        raise RuntimeError("Step22 repair/factory-review jobs did not both pass")
    arts=gh.get(f"/actions/runs/{repair_run_id}/artifacts?per_page=100").get("artifacts",[])
    handoff=[a for a in arts if a.get("name")==f"portfolio-factory-review-handoff-{repair_run_id}"]
    review=[a for a in arts if a.get("name")==f"portfolio-factory-independent-review-{repair_run_id}"]
    if len(handoff)!=1 or len(review)!=1: raise RuntimeError("Step22 factory evidence artifacts missing/ambiguous")
    handoff_digest=handoff[0].get("digest");review_digest=review[0].get("digest")
    if not (isinstance(handoff_digest,str) and handoff_digest.startswith("sha256:") and isinstance(review_digest,str) and review_digest.startswith("sha256:")):
        raise RuntimeError("Step22 artifact digests invalid")

    files=gh.get(f"/pulls/{prn}/files?per_page=100")
    changed=[x["filename"] for x in files]
    new_tests=[x["filename"] for x in files if x.get("status")=="added" and x["filename"].startswith("tests/")]
    target="acceptance/step22_controlled_fault_target.py"
    if target not in changed or not new_tests: raise RuntimeError("Step22 repair lacks target/new regression")
    if any(path!=target and path not in new_tests for path in changed): raise RuntimeError("Step22 repair changed path outside fixture/new tests")

    def final_pr():
        x=gh.get(f"/pulls/{prn}")
        if x["head"]["sha"]!=initial_head: raise RuntimeError("Step22 candidate head drifted")
        return x if x.get("merged_at") else None
    merged=wait_until(final_pr,deadline=deadline,desc="protected Step22 repair merge")
    merge_sha=merged["merge_commit_sha"];head=merged["head"]["sha"]

    checks=gh.get(f"/commits/{head}/check-runs?per_page=100").get("check_runs",[])
    foundation=select_trusted_check(checks,name="validate",app_id=15368,head_sha=head)
    hosted=select_trusted_check(checks,name="portfolio-phase1-gate",app_id=5121826,head_sha=head)
    maintenance_lineage=[]
    continuation_sha=merge_sha
    for maintenance_pr_number in args.maintenance_pr_number:
        maintenance=verify_maintenance_pr(
            gh,pr_number=maintenance_pr_number,expected_base_sha=continuation_sha,
        )
        maintenance_lineage.append(maintenance)
        continuation_sha=maintenance["merge_sha"]
    main_sha=gh.get("/branches/main")["commit"]["sha"]
    if main_sha!=continuation_sha:
        raise RuntimeError("protected main is not the exact Step22 continuation head")

    cycle_dispatch_at=now_iso()
    gh.post("/actions/workflows/runtime-hourly-sync.yml/dispatches",{"ref":"main"})
    gh.post("/actions/workflows/portfolio-autonomous-scheduler.yml/dispatches",{"ref":"main"})

    def workflow_run(workflow:str,event:str):
        doc=gh.get(f"/actions/workflows/{workflow}/runs?branch=main&event={event}&per_page=30")
        rows=[x for x in doc.get("workflow_runs",[]) if x.get("head_sha")==continuation_sha and x.get("created_at")>=cycle_dispatch_at]
        rows.sort(key=lambda x:x["id"],reverse=True)
        if not rows:return None
        x=rows[0]
        if x.get("status")!="completed":return None
        if x.get("conclusion")!="success":raise RuntimeError(workflow+" continuation failed: "+str(x.get("conclusion")))
        return x
    runtime=wait_until(lambda:workflow_run("runtime-hourly-sync.yml","workflow_dispatch"),deadline=deadline,desc="Step22 runtime continuation")
    scheduler=wait_until(lambda:workflow_run("portfolio-autonomous-scheduler.yml","workflow_dispatch"),deadline=deadline,desc="Step22 scheduler continuation")
    reducer_after=min(runtime["created_at"],scheduler["created_at"])
    def reducer_run():
        doc=gh.get("/actions/workflows/portfolio-state-reducer.yml/runs?branch=main&per_page=50")
        rows=[x for x in doc.get("workflow_runs",[]) if x.get("head_sha")==continuation_sha and x.get("created_at")>=reducer_after]
        rows.sort(key=lambda x:x["id"],reverse=True)
        for x in rows:
            if x.get("status")=="completed":
                if x.get("conclusion")=="success":return x
                if x.get("conclusion") not in {"cancelled","skipped"}: raise RuntimeError("Step22 reducer continuation failed: "+str(x.get("conclusion")))
        return None
    reducer=wait_until(reducer_run,deadline=deadline,desc="Step22 reducer continuation")
    if gh.get("/branches/main")["commit"]["sha"]!=continuation_sha:
        raise RuntimeError("protected main moved during Step22 finalization")

    def cycle_row(x):
        return {"run_id":x["id"],"head_sha":x["head_sha"],"conclusion":x["conclusion"],"created_at":x["created_at"],"completed_at":x["updated_at"],"artifact_hashes":artifact_hashes(gh,x["id"])}
    meta={
      "schema_version":"1.0.0","current_main_sha":continuation_sha,
      "fault":{"base_sha":args.fault_base_sha,"detected_at":args.fault_detected_at,"dispatched_at":args.dispatched_at,"dispatch_run_id":args.dispatch_run_id,"receipt_hash":args.fault_receipt_hash,"fingerprint":args.fingerprint},
      "repair":{
        "base_sha":args.fault_base_sha,"workflow_run_id":repair_run_id,"workflow_created_at":run["created_at"],
        "pr_number":prn,"pr_created_at":pr["created_at"],"actor_login":pr["user"]["login"],"branch":branch,
        "candidate_head_sha":head,"new_regression_added":True,"new_regression_paths":new_tests,
        "full_test_suite_passed":True,"handoff_artifact_digest":handoff_digest,"independent_review_artifact_digest":review_digest,
        "foundation_check":foundation,"hosted_verifier_check":hosted,"merged_at":merged["merged_at"],"merge_sha":merge_sha,
        "merge_receipt_hash":hv({"pr_number":prn,"candidate_head_sha":head,"merge_sha":merge_sha,"merged_at":merged["merged_at"]}),
      },
      "maintenance_lineage":maintenance_lineage,
      "cycles":{"runtime":cycle_row(runtime),"reducer":cycle_row(reducer),"scheduler":cycle_row(scheduler)},
    }
    receipt=build_receipt(meta)
    args.output_meta.parent.mkdir(parents=True,exist_ok=True)
    args.output_meta.write_text(json.dumps(meta,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    args.output_receipt.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"status":receipt["status"],"receipt_hash":receipt["receipt_hash"],"repair_pr":prn,"repair_merge_sha":merge_sha,"runtime_run":runtime["id"],"reducer_run":reducer["id"],"scheduler_run":scheduler["id"]},sort_keys=True))
if __name__=="__main__": main()
