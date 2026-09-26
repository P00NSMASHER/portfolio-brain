#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path
from runtime.artifact_http import open_url
from runtime.artifact_restore import restore_latest_valid_state
from cost_governor.cost_governor import validate_state

ROOT = Path(__file__).resolve().parents[1]

class RestoreError(RuntimeError):
    pass

def policy():
    return json.loads((ROOT / "cost_governor" / "COST_GOVERNOR_POLICY.json").read_text())

def restore(output: Path, metadata_output: Path | None = None) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run = os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:
        return "NO_ACTIONS_CONTEXT"
    p = policy()
    used = 0

    def get(url: str) -> bytes:
        nonlocal used
        last = None
        for attempt in range(3):
            if used >= 6:
                raise RestoreError("cost governor artifact request budget exceeded")
            used += 1
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "portfolio-brain-cost-governor/1.0",
                },
                method="GET",
            )
            try:
                with open_url(request,timeout=20) as response:
                    return response.read()
            except Exception as exc:
                last = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        raise RestoreError(str(last))

    name = p["state_persistence"]["artifact_name"]
    data = json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={name}&per_page=100").decode())
    max_bytes = p["state_persistence"].get("max_artifact_bytes", 5_242_880)
    return restore_latest_valid_state(
        data,current_run=run,download=get,output=output,
        member_name="cost_state.json",expected_state_id="portfolio-cost-governor-state",
        max_archive_bytes=max_bytes,max_state_bytes=max_bytes,
        validator=validate_state,metadata_output=metadata_output,
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output", default=None)
    args = parser.parse_args()
    print(restore(Path(args.output), None if args.metadata_output is None else Path(args.metadata_output)))

if __name__ == "__main__":
    main()
