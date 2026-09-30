"""Restore a prior exact-lineage repair plan from bounded GitHub artifact history."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import urllib.request
import zipfile

from runtime.artifact_http import open_url
from software_factory.candidate_worker import require

ARTIFACT_NAME = "portfolio-repair-plan-state"
MAX_REQUESTS = 8
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_PLAN_BYTES = 512 * 1024


class RepairPlanRestoreError(RuntimeError):
    pass


def _get(url: str, *, token: str, counter: list[int]) -> bytes:
    if counter[0] >= MAX_REQUESTS:
        raise RepairPlanRestoreError("repair plan artifact request budget exceeded")
    counter[0] += 1
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portfolio-brain-repair-plan-restore/1.0",
        },
        method="GET",
    )
    with open_url(request, timeout=20) as response:
        raw = response.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise RepairPlanRestoreError("repair plan artifact response too large")
    return raw


def _plan_from_zip(raw: bytes, lineage_id: str) -> dict | None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None
    members = [info for info in archive.infolist()
               if not info.is_dir() and Path(info.filename).name == "repair_plan.json"]
    if len(members) != 1 or members[0].file_size > MAX_PLAN_BYTES:
        return None
    try:
        plan = json.loads(archive.read(members[0]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, KeyError):
        return None
    if not isinstance(plan, dict) or plan.get("lineage_id") != lineage_id:
        return None
    if plan.get("task_hash") is None or not isinstance(plan.get("task"), dict):
        return None
    return plan


def restore(*, lineage_id: str, output: Path, token: str | None = None,
            repository: str | None = None, expected_branch: str = "main",
            current_run_id: str | None = None) -> str:
    token = token or os.environ.get("GITHUB_TOKEN")
    repository = repository or os.environ.get("GITHUB_REPOSITORY")
    current_run_id = current_run_id or os.environ.get("GITHUB_RUN_ID")
    if not token or not repository:
        return "NO_ACTIONS_CONTEXT"
    counter = [0]
    api = f"https://api.github.com/repos/{repository}/actions/artifacts?name={ARTIFACT_NAME}&per_page=50"
    data = json.loads(_get(api, token=token, counter=counter).decode("utf-8"))
    rows = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RepairPlanRestoreError("repair plan artifact listing invalid")
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
            raw = _get(row["archive_download_url"], token=token, counter=counter)
            plan = _plan_from_zip(raw, lineage_id)
        except Exception:
            continue
        if plan is None:
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, indent=2) + "\n")
        return "RESTORED"
    return "NOT_FOUND"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-branch", default="main")
    args = parser.parse_args()
    status = restore(lineage_id=args.lineage_id, output=args.output,
                     expected_branch=args.expected_branch)
    print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
