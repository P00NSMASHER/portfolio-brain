#!/usr/bin/env python3
"""Restore newest validated durable Hunter proposal inbox artifact."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

from hunting.autonomous_hunter import load_policy
from hunting.proposal_state import validate_state
from runtime.artifact_http import open_url
from runtime.artifact_restore import restore_latest_valid_state

class RestoreError(RuntimeError):
    pass

def restore(
    output:Path,metadata_output:Path|None=None,*,preferred_state_hash:str|None=None
)->str:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repo=os.environ.get("GITHUB_REPOSITORY")
    run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:
        return "NO_ACTIONS_CONTEXT"
    cfg=load_policy()["proposal_persistence"]
    used=0
    def get(url:str)->bytes:
        nonlocal used
        last=None
        for attempt in range(3):
            if used>=6:
                raise RestoreError("Hunter proposal artifact restore request budget exceeded")
            used+=1
            req=urllib.request.Request(url,headers={
              "Accept":"application/vnd.github+json",
              "Authorization":f"Bearer {token}",
              "X-GitHub-Api-Version":"2022-11-28",
              "User-Agent":"portfolio-brain-hunter-proposal-state/1.0",
            },method="GET")
            try:
                with open_url(req,timeout=20) as response:
                    return response.read()
            except Exception as exc:
                last=exc
                if attempt<2:
                    time.sleep(attempt+1)
        raise RestoreError(str(last))
    data=json.loads(get(
      f"https://api.github.com/repos/{repo}/actions/artifacts?name={cfg['artifact_name']}&per_page=100"
    ).decode())
    return restore_latest_valid_state(
      data,
      current_run=run,
      expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
      download=get,
      output=output,
      member_name="hunter_proposal_state.json",
      expected_state_id="portfolio-hunter-proposal-state",
      max_archive_bytes=1_048_576,
      max_state_bytes=1_048_576,
      validator=validate_state,
      metadata_output=metadata_output,
      max_candidates=5,
      preferred_state_hash=preferred_state_hash,
    )

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",required=True)
    ap.add_argument("--metadata-output",default=None)
    args=ap.parse_args()
    print(restore(Path(args.output),None if args.metadata_output is None else Path(args.metadata_output)))

if __name__=="__main__":
    main()
