#!/usr/bin/env python3
from __future__ import annotations
import argparse,io,json,os,time,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class RestoreError(RuntimeError):pass
def policy():return json.loads((ROOT/"scheduler"/"SCHEDULER_POLICY.json").read_text())
def restore(output):
    token=os.environ.get("GITHUB_TOKEN");repo=os.environ.get("GITHUB_REPOSITORY");run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:return "NO_ACTIONS_CONTEXT"
    p=policy();used=0
    def get(url):
        nonlocal used
        last=None
        for attempt in range(3):
            if used>=6:raise RestoreError("scheduler artifact request budget exceeded")
            used+=1
            req=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","Authorization":f"Bearer {token}","X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-scheduler/1.0"},method="GET")
            try:
                with urllib.request.urlopen(req,timeout=20) as resp:return resp.read()
            except Exception as exc:
                last=exc
                if attempt<2:time.sleep(attempt+1)
        raise RestoreError(str(last))
    data=json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={p['state_persistence']['artifact_name']}&per_page=100").decode())
    items=[x for x in data.get("artifacts",[]) if not x.get("expired") and str((x.get("workflow_run") or {}).get("id"))!=str(run)]
    if not items:return "NO_PRIOR_ARTIFACT"
    items.sort(key=lambda x:x.get("created_at",""),reverse=True);raw=get(items[0]["archive_download_url"])
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        if "scheduler_state.json" not in zf.namelist():raise RestoreError("scheduler_state.json missing")
        body=zf.read("scheduler_state.json")
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(body);return "RESTORED"
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",required=True);a=ap.parse_args();print(restore(Path(a.output)))
if __name__=="__main__":main()
