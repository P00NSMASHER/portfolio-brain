"""Restore latest valid cost state for the serialized repair candidate lane.

Unlike the generic restorer, this lane may consume an artifact from an earlier
attempt of the same GitHub run. The lane is globally serialized with other paid
work, so a same-run artifact here represents completed prior-attempt accounting
rather than concurrent mutable state.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import urllib.request
import zipfile

from cost_governor.cost_governor import validate_state
from runtime.artifact_http import open_url

ARTIFACT_NAME = "portfolio-cost-governor-state"
MAX_REQUESTS = 8
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_STATE_BYTES = 5 * 1024 * 1024


class RepairCostRestoreError(RuntimeError):
    pass


def _get(url: str, token: str, counter: list[int]) -> bytes:
    if counter[0] >= MAX_REQUESTS:
        raise RepairCostRestoreError("repair cost artifact request budget exceeded")
    counter[0] += 1
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portfolio-brain-repair-cost-restore/1.0",
        },
        method="GET",
    )
    with open_url(request, timeout=20) as response:
        raw = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise RepairCostRestoreError("repair cost artifact response too large")
    return raw


def _state_from_zip(raw: bytes) -> dict | None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None
    members = [x for x in archive.infolist()
               if not x.is_dir() and Path(x.filename).name == "cost_state.json"]
    if len(members) != 1 or members[0].file_size > MAX_STATE_BYTES:
        return None
    try:
        state = json.loads(archive.read(members[0]).decode("utf-8"))
        validate_state(state)
    except Exception:
        return None
    return state


def restore(output: Path, *, token: str | None = None, repository: str | None = None,
            expected_branch: str = "main") -> str:
    token = token or os.environ.get("GITHUB_TOKEN")
    repository = repository or os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        return "NO_ACTIONS_CONTEXT"
    counter = [0]
    listing = _get(
        f"https://api.github.com/repos/{repository}/actions/artifacts?name={ARTIFACT_NAME}&per_page=50",
        token, counter)
    data = json.loads(listing.decode("utf-8"))
    rows = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RepairCostRestoreError("repair cost artifact listing invalid")
    eligible = []
    for row in rows:
        if not isinstance(row, dict) or row.get("expired") is True:
            continue
        run = row.get("workflow_run") or {}
        if expected_branch and run.get("head_branch") != expected_branch:
            continue
        if not isinstance(row.get("archive_download_url"), str):
            continue
        eligible.append(row)
    eligible.sort(key=lambda row: (row.get("created_at") or "", int(row.get("id") or 0)), reverse=True)
    for row in eligible[:6]:
        try:
            state = _state_from_zip(_get(row["archive_download_url"], token, counter))
        except Exception:
            continue
        if state is None:
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(state, indent=2) + "\n")
        return "RESTORED"
    return "NOT_FOUND"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-branch", default="main")
    args = parser.parse_args()
    print(restore(args.output, expected_branch=args.expected_branch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
