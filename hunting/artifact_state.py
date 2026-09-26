#!/usr/bin/env python3
"""Restore newest Portfolio Hunter state artifact."""
from __future__ import annotations
import argparse, json, os, time, urllib.request
from pathlib import Path
from runtime.artifact_http import open_url
from runtime.artifact_restore import restore_latest_valid_state
from hunting.autonomous_hunter import validate_state
ROOT=Path(__file__).resolve().parents[1]
class RestoreError(RuntimeError): pass
def policy(): return json.loads((ROOT/"hunting"/"HUNTER_POLICY.json").read_text())
def restore(output,metadata_output=None):
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN"); repo=os.environ.get("GITHUB_REPOSITORY"); run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo: return "NO_ACTIONS_CONTEXT"
    p=policy(); used=0
    def get(url):
        nonlocal used
        last=None
        for attempt in range(p["budgets"]["retry_limit"]+1):
            if used>=6: raise RestoreError("artifact restore request budget exceeded")
            used+=1
            reqq=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","Authorization":f"Bearer {token}","X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-hunter/1.0"},method="GET")
            try:
                with open_url(reqq,timeout=20) as resp:return resp.read()
            except Exception as exc:
                last=exc
                if attempt<p["budgets"]["retry_limit"]:time.sleep(p["budgets"]["retry_backoff_seconds"]*(attempt+1))
        raise RestoreError(str(last))
    data=json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={p['state_persistence']['artifact_name']}&per_page=100").decode())
    max_bytes=p["budgets"]["max_output_bytes"]
    return restore_latest_valid_state(data,current_run=run,download=get,output=Path(output),member_name="hunter_state.json",expected_state_id="portfolio-hunter-state",max_archive_bytes=max_bytes,max_state_bytes=max_bytes,validator=validate_state,metadata_output=metadata_output)
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",required=True);ap.add_argument("--metadata-output",default=None);a=ap.parse_args();print(restore(Path(a.output),None if a.metadata_output is None else Path(a.metadata_output)))
if __name__=="__main__":main()
