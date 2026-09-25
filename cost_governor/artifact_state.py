#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class RestoreError(RuntimeError):
    pass

def policy():
    return json.loads((ROOT / "cost_governor" / "COST_GOVERNOR_POLICY.json").read_text())

def restore(output: Path) -> str:
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
                with urllib.request.urlopen(request, timeout=20) as response:
                    return response.read()
            except Exception as exc:
                last = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        raise RestoreError(str(last))

    name = p["state_persistence"]["artifact_name"]
    data = json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={name}&per_page=100").decode())
    items = [
        item for item in data.get("artifacts", [])
        if not item.get("expired") and str((item.get("workflow_run") or {}).get("id")) != str(run)
    ]
    if not items:
        return "NO_PRIOR_ARTIFACT"
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    raw = get(items[0]["archive_download_url"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if "cost_state.json" not in archive.namelist():
            raise RestoreError("cost_state.json missing")
        body = archive.read("cost_state.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body)
    return "RESTORED"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(restore(Path(args.output)))

if __name__ == "__main__":
    main()
