#!/usr/bin/env python3
"""Restore REPO-001 scout-intake dedupe state from the Hunter artifact."""
from __future__ import annotations
import argparse,json,os,time,urllib.request
from pathlib import Path
from runtime.artifact_http import open_url
from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from hunting.repo_scout_intake import seed_state, validate_state

ARTIFACT_NAME="portfolio-hunter-state"
SCOUT_STATE_INTRODUCED_AT="2026-09-30T20:26:40Z"

class RestoreError(RuntimeError): pass

def _eligible_candidates(data,current_run=None,expected_head_branch=None):
    return [
      item for item in data.get("artifacts",[])
      if not item.get("expired")
      and str((item.get("workflow_run") or {}).get("id")) != str(current_run)
      and (
        expected_head_branch is None
        or (item.get("workflow_run") or {}).get("head_branch")==expected_head_branch
      )
    ]

def _write_seed(output:Path,metadata_output:Path|None,status:str)->str:
    state=seed_state();validate_state(state)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(state,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if metadata_output is not None:
        metadata_output.parent.mkdir(parents=True,exist_ok=True)
        metadata_output.write_text(json.dumps({
          "schema_version":"1.0.0",
          "restore_status":status,
          "artifact_id":None,
          "artifact_name":None,
          "artifact_created_at":None,
          "artifact_expires_at":None,
          "source_run_id":None,
          "source_head_sha":None,
          "seed_state_id":state["state_id"],
          "seed_sequence":state["sequence"],
        },sort_keys=True)+"\n",encoding="utf-8")
    return status

def restore_from_listing(data,*,current_run=None,expected_head_branch=None,download,output:Path,metadata_output:Path|None=None)->str:
    candidates=_eligible_candidates(data,current_run=current_run,expected_head_branch=expected_head_branch)
    try:
        status=restore_latest_valid_state(
          data,current_run=current_run,expected_head_branch=expected_head_branch,
          download=download,output=output,member_name="repo_scout_intake_state.json",
          expected_state_id="portfolio-repo-scout-intake-state",max_archive_bytes=5_242_880,
          max_state_bytes=1_048_576,validator=validate_state,metadata_output=metadata_output,
        )
    except InvalidStateArtifact as exc:
        legacy_only=bool(candidates) and all(
          isinstance(item.get("created_at"),str)
          and item["created_at"] < SCOUT_STATE_INTRODUCED_AT
          for item in candidates
        )
        if str(exc)=="no valid prior state artifact found" and legacy_only:
            return _write_seed(output,metadata_output,"SEEDED_LEGACY_PRE_SCOUT_ARTIFACTS")
        raise
    if status=="NO_PRIOR_ARTIFACT":
        return _write_seed(output,metadata_output,"SEEDED_NO_PRIOR_ARTIFACT")
    return status

def restore(output:Path,metadata_output:Path|None=None)->str:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN");repo=os.environ.get("GITHUB_REPOSITORY");run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:return "NO_ACTIONS_CONTEXT"
    used=0
    def get(url):
        nonlocal used
        last=None
        for attempt in range(3):
            if used>=6: raise RestoreError("scout intake artifact request budget exceeded")
            used+=1
            req=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","Authorization":f"Bearer {token}","X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-repo-scout-intake/1.0"},method="GET")
            try:
                with open_url(req,timeout=20) as response:return response.read()
            except Exception as exc:
                last=exc
                if attempt<2:time.sleep(attempt+1)
        raise RestoreError(str(last))
    data=json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={ARTIFACT_NAME}&per_page=100").decode())
    return restore_from_listing(
      data,current_run=run,expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
      download=get,output=output,metadata_output=metadata_output,
    )

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",required=True);ap.add_argument("--metadata-output");a=ap.parse_args()
    print(restore(Path(a.output),None if a.metadata_output is None else Path(a.metadata_output)))

if __name__=="__main__":main()
