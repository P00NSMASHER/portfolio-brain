#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,time,urllib.request
from pathlib import Path
from runtime.artifact_http import open_url
from runtime.artifact_restore import restore_latest_valid_state
from notifications.notification_engine import validate_state
ROOT=Path(__file__).resolve().parents[1]
class RestoreError(RuntimeError):pass
def policy():return json.loads((ROOT/"notifications"/"NOTIFICATION_POLICY.json").read_text())
def restore(output:Path,metadata_output=None):
    token=os.environ.get("GITHUB_TOKEN");repo=os.environ.get("GITHUB_REPOSITORY");run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:return "NO_ACTIONS_CONTEXT"
    used=0
    def get(url):
        nonlocal used
        last=None
        for attempt in range(3):
            if used>=6:raise RestoreError("notification artifact request budget exceeded")
            used+=1
            req=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","Authorization":f"Bearer {token}","X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-notifications/1.0"},method="GET")
            try:
                with open_url(req,timeout=20) as resp:return resp.read()
            except Exception as exc:
                last=exc
                if attempt<2:time.sleep(attempt+1)
        raise RestoreError(str(last))
    name=policy()["state_persistence"]["artifact_name"]
    data=json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={name}&per_page=100").decode())
    max_bytes=policy()["state_persistence"].get("max_artifact_bytes",5_242_880)
    return restore_latest_valid_state(data,current_run=run,download=get,output=output,member_name="notification_state.json",expected_state_id="portfolio-notification-state",max_archive_bytes=max_bytes,max_state_bytes=max_bytes,validator=validate_state,metadata_output=metadata_output)
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",required=True);ap.add_argument("--metadata-output",default=None);a=ap.parse_args();print(restore(Path(a.output),None if a.metadata_output is None else Path(a.metadata_output)))
if __name__=="__main__":main()
