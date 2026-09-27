#!/usr/bin/env python3
"""Restore newest sanitized model-routing feedback state artifact."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

from model_router.feedback_state import ARTIFACT_NAME, validate_state
from runtime.artifact_http import open_url
from runtime.artifact_restore import restore_latest_valid_state

class RestoreError(RuntimeError):
    pass

def restore(output:Path,metadata_output:Path|None=None)->str:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repo=os.environ.get("GITHUB_REPOSITORY")
    run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:
        return "NO_ACTIONS_CONTEXT"
    used=0
    def get(url:str)->bytes:
        nonlocal used
        last=None
        for attempt in range(3):
            if used>=6:
                raise RestoreError("model feedback artifact request budget exceeded")
            used+=1
            request=urllib.request.Request(
              url,
              headers={
                "Accept":"application/vnd.github+json",
                "Authorization":f"Bearer {token}",
                "X-GitHub-Api-Version":"2022-11-28",
                "User-Agent":"portfolio-brain-model-feedback/1.0",
              },
              method="GET",
            )
            try:
                with open_url(request,timeout=20) as response:
                    return response.read()
            except Exception as exc:
                last=exc
                if attempt<2:
                    time.sleep(attempt+1)
        raise RestoreError(str(last))
    data=json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={ARTIFACT_NAME}&per_page=100").decode())
    return restore_latest_valid_state(
      data,
      current_run=run,
      expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
      download=get,
      output=output,
      member_name="model_feedback_state.json",
      expected_state_id="portfolio-model-feedback-state",
      max_archive_bytes=2_000_000,
      max_state_bytes=2_000_000,
      validator=validate_state,
      metadata_output=metadata_output,
    )

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",required=True)
    ap.add_argument("--metadata-output",default=None)
    args=ap.parse_args()
    print(restore(Path(args.output),None if args.metadata_output is None else Path(args.metadata_output)))

if __name__=="__main__":
    main()
