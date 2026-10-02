from __future__ import annotations
import json, os, urllib.parse, urllib.request
from datetime import datetime
from state_journal.contracts import WORKFLOW_PRODUCERS
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT

repo=os.environ["GITHUB_REPOSITORY"]
token=os.environ["GITHUB_TOKEN"]
policy=json.load(open("state_journal/POLICY.json",encoding="utf-8"))
since=policy["artifact_scan_start"]
boundary=datetime.fromisoformat(since.replace("Z","+00:00"))
calls=0

def get(path):
    global calls
    calls += 1
    req=urllib.request.Request(
        "https://api.github.com/repos/"+repo+path,
        headers={
            "Authorization":"Bearer "+token,
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"step23-request-budget-diagnostic/1.0",
        },
    )
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.load(r)

def workflow_runs(name):
    encoded=urllib.parse.quote(">="+since,safe="")
    out=[]
    pages=0
    for page in range(1,21):
        rows=get(f"/actions/workflows/{name}.yml/runs?branch=main&created={encoded}&per_page=100&page={page}").get("workflow_runs",[])
        pages += 1
        out.extend(rows)
        if len(rows)<100:
            break
    return out,pages

reducers,reducer_pages=workflow_runs("portfolio-state-reducer")
snapshot_runs=[]
snapshot_queries=0
for run in reducers:
    if not (run.get("head_branch")=="main" and run.get("status")=="completed" and run.get("conclusion")=="success"):
        continue
    doc=get(f"/actions/runs/{run['id']}/artifacts?per_page=100")
    snapshot_queries += 1
    matches=[a for a in doc.get("artifacts",[]) if a.get("name")==SNAPSHOT_ARTIFACT and not a.get("expired")]
    if matches:
        snapshot_runs.append((run,matches[0]))
        if len(snapshot_runs)==2:
            break
if len(snapshot_runs)<2:
    raise SystemExit("NEED_TWO_SUCCESSFUL_REDUCER_SNAPSHOTS")
overlap_raw=min(snapshot_runs[0][0]["created_at"],snapshot_runs[1][0]["created_at"])
overlap=datetime.fromisoformat(overlap_raw.replace("Z","+00:00"))

terminal={"success","failure","cancelled","timed_out"}
post=[]
crossover=[]
producer_pages={}
for wf in sorted(WORKFLOW_PRODUCERS):
    rows,pages=workflow_runs(wf)
    producer_pages[wf]=pages
    for run in rows:
        if not (run.get("head_branch")=="main" and run.get("status")=="completed" and run.get("conclusion") in terminal):
            continue
        started=datetime.fromisoformat(run["created_at"].replace("Z","+00:00"))
        finished=datetime.fromisoformat(run["updated_at"].replace("Z","+00:00"))
        if started < overlap and finished < overlap:
            continue
        row={"id":int(run["id"]),"workflow":wf,"created_at":run["created_at"],"updated_at":run["updated_at"],"conclusion":run["conclusion"]}
        (crossover if started < overlap else post).append(row)

post_ids={r["id"] for r in post}
seen_artifacts={}
event_by_run={}
artifact_pages=0
for page in range(1,21):
    rows=get(f"/actions/artifacts?per_page=100&page={page}").get("artifacts",[])
    artifact_pages += 1
    for a in rows:
        seen_artifacts[a["id"]]=a
        rid=(a.get("workflow_run") or {}).get("id")
        if rid in post_ids and str(a.get("name") or "").startswith(EVENT_PREFIX):
            event_by_run.setdefault(int(rid),[]).append(a)
    if len(rows)<100:
        break

found_event_runs=set(event_by_run)
missing_post=[r for r in post if r["id"] not in found_event_runs]
discovery_calls=calls
exact_run_artifact_queries=len(crossover)+len(missing_post)
event_count=sum(len(v) for v in event_by_run.values())
# Each retained event requires at least jobs metadata + event ZIP.
event_validation_lower_bound=event_count*2
estimated_lower_bound=discovery_calls+exact_run_artifact_queries+event_validation_lower_bound

result={
    "artifact_scan_start":since,
    "overlap_at":overlap_raw,
    "snapshot_runs":[{"id":r[0]["id"],"created_at":r[0]["created_at"],"artifact_id":r[1]["id"]} for r in snapshot_runs],
    "producer_workflows":len(WORKFLOW_PRODUCERS),
    "producer_listing_pages":producer_pages,
    "post_overlap_runs":len(post),
    "crossover_runs":len(crossover),
    "repo_artifact_pages":artifact_pages,
    "repo_unique_artifacts":len(seen_artifacts),
    "event_artifacts_found":event_count,
    "post_runs_with_event_found":len(found_event_runs),
    "post_runs_missing_event_in_repo_scan":len(missing_post),
    "exact_run_artifact_queries_needed_if_scan_used_as_cache":exact_run_artifact_queries,
    "api_calls_before_exact_fallback":discovery_calls,
    "event_validation_calls_lower_bound":event_validation_lower_bound,
    "estimated_total_lower_bound":estimated_lower_bound,
    "max_requests":policy["limits"]["max_read_requests"],
    "sample_missing_post":missing_post[:20],
}
print(json.dumps(result,indent=2,sort_keys=True))
open("request_budget_diagnostic.json","w",encoding="utf-8").write(json.dumps(result,indent=2,sort_keys=True)+"\n")
