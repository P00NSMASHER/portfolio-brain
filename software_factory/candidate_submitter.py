"""Idempotently submit an exact replayed candidate to its isolated remote branch.

This stage may create/update only the factory candidate branch and commit already
described by replay evidence. It never verifies, opens a PR, merges, deploys, or
changes repository settings. Reruns inspect provider state and reuse an exact
candidate instead of creating competing work.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote

from software_factory.candidate_replay import read_json
from software_factory.candidate_worker import BuildError, digest, object_hash, require
from software_factory.github_executor import GitHubExecutor
from software_factory.software_factory import hashv

MAX_JSON = 2 * 1024 * 1024


def _packet_hash(packet: dict) -> str:
    body = dict(packet)
    given = body.pop("action_hash", None)
    require(given == hashv(body), "factory action packet hash mismatch")
    return given


def validate_export(root: Path) -> dict:
    root = root.resolve(strict=True)
    replay = read_json(root, "replay_receipt.json", MAX_JSON)
    work = read_json(root, "factory_work.json", MAX_JSON)
    branch = read_json(root, "factory_branch_action.json", MAX_JSON)
    commit = read_json(root, "factory_commit_action.json", MAX_JSON)
    files = read_json(root, "candidate_files.json", MAX_JSON)
    require(isinstance(replay, dict) and replay.get("status") == "REPLAY_PASSED_AWAITING_INDEPENDENT_REVIEW",
            "replay is not submission eligible")
    require(replay.get("independent_verification") is False
            and replay.get("remote_submission_performed") is False
            and replay.get("production_changed") is False
            and replay.get("merge_authorized") is False
            and replay.get("deployment_authorized") is False,
            "replay artifact unexpectedly grants authority")
    require(isinstance(work, dict) and work.get("state") == "VERIFYING"
            and work.get("verification_id") is None and work.get("pr_number") is None,
            "factory work is not awaiting verification")
    require(branch.get("operation") == "CREATE_BRANCH" and commit.get("operation") == "COMMIT_CANDIDATE",
            "unexpected factory action kind")
    branch_hash = _packet_hash(branch)
    commit_hash = _packet_hash(commit)
    require(branch_hash == replay.get("branch_packet_hash")
            and commit_hash == replay.get("commit_packet_hash"), "factory packet/replay hash mismatch")
    for packet in (branch, commit):
        require(packet.get("factory_work_id") == work.get("work_id"), "factory work identity mismatch")
        require(packet.get("repository_full_name") == replay.get("repository"), "repository identity mismatch")
        require(packet.get("base_sha") == replay.get("base_sha"), "base identity mismatch")
        require(packet.get("branch_name") == work.get("branch_name"), "candidate branch identity mismatch")
        require(packet.get("branch_name") != packet.get("default_branch"), "candidate branch is default branch")
    require(branch.get("expected_head_sha") is None and branch.get("files") == [],
            "branch action carries unexpected mutation")
    require(commit.get("expected_head_sha") == replay.get("base_sha"), "commit packet expected head mismatch")
    require(isinstance(files, dict) and set(files) == set(replay.get("changed_paths") or []),
            "candidate file manifest mismatch")
    packet_files = commit.get("files")
    require(isinstance(packet_files, list) and len(packet_files) == len(files), "candidate packet file count mismatch")
    decoded = {}
    for row in packet_files:
        require(isinstance(row, dict) and set(row) == {"path", "content_b64", "content_sha256"},
                "candidate packet file fields changed")
        require(row["path"] not in decoded and row["path"] in files, "candidate packet path mismatch")
        raw = base64.b64decode(row["content_b64"], validate=True)
        require(row["content_sha256"] == digest(raw) and raw == files[row["path"]].encode(),
                "candidate packet bytes mismatch")
        decoded[row["path"]] = raw
    require(set(decoded) == set(files), "candidate packet paths incomplete")
    require(work.get("commit_sha") == replay.get("candidate_commit_sha"), "local candidate commit identity mismatch")
    require(work.get("diff_hash") == replay.get("patch_sha256"), "factory diff/replay mismatch")
    lineage_core = {
        "repository": replay["repository"],
        "base_sha": replay["base_sha"],
        "task_hash": replay["task_hash"],
        "patch_sha256": replay["patch_sha256"],
        "candidate_git_tree_sha": replay["candidate_git_tree_sha"],
        "branch_name": branch["branch_name"],
    }
    return {"replay": replay, "work": work, "branch": branch, "commit": commit,
            "files": files, "submission_key": object_hash(lineage_core)}


def _ref(executor, base: str, branch: str):
    url = base + "/git/ref/heads/" + quote(branch, safe="/")
    try:
        return executor.transport("GET", url, None)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _verify_remote(executor, export: dict, remote_sha: str) -> dict:
    replay = export["replay"]
    commit_packet = export["commit"]
    base = "https://api.github.com/repos/" + replay["repository"]
    require(isinstance(remote_sha, str) and len(remote_sha) == 40, "remote commit SHA invalid")
    require(remote_sha != replay["base_sha"], "remote candidate did not advance base")
    commit = executor.transport("GET", base + "/git/commits/" + remote_sha, None)
    require(isinstance(commit, dict), "remote commit missing")
    parents = commit.get("parents")
    require(isinstance(parents, list) and [p.get("sha") for p in parents] == [replay["base_sha"]],
            "remote candidate parent mismatch")
    tree = commit.get("tree")
    require(isinstance(tree, dict) and tree.get("sha") == replay["candidate_git_tree_sha"],
            "remote candidate tree differs from replayed tree")
    if commit_packet.get("commit_message") is not None:
        require(commit.get("message") == commit_packet["commit_message"], "remote candidate message mismatch")
    compare = executor.transport(
        "GET", base + "/compare/" + replay["base_sha"] + "..." + remote_sha, None)
    require(isinstance(compare, dict) and compare.get("ahead_by") == 1
            and compare.get("behind_by") == 0 and compare.get("status") == "ahead",
            "remote candidate is not exactly one commit ahead of base")
    remote_paths = {row.get("filename") for row in (compare.get("files") or [])}
    require(remote_paths == set(replay["changed_paths"]), "remote candidate changed-path set mismatch")
    return {"remote_commit_sha": remote_sha, "remote_tree_sha": tree["sha"]}


def submit_candidate(*, replay_dir: Path, token: str | None = None, executor=None,
                     output_path: Path | None = None) -> dict:
    export = validate_export(replay_dir)
    executor = executor or GitHubExecutor(token or os.environ.get("PORTFOLIO_FACTORY_TOKEN")
                                         or os.environ.get("GITHUB_TOKEN"))
    replay = export["replay"]
    branch_packet = export["branch"]
    commit_packet = export["commit"]
    api = "https://api.github.com/repos/" + replay["repository"]
    existing = _ref(executor, api, branch_packet["branch_name"])
    mutation = False
    disposition = "REMOTE_CANDIDATE_REUSED"
    if existing is None:
        executor.execute(branch_packet)
        mutation = True
        existing = _ref(executor, api, branch_packet["branch_name"])
        require(existing is not None and existing.get("object", {}).get("sha") == replay["base_sha"],
                "created candidate branch does not point to exact base")
    head = existing.get("object", {}).get("sha") if isinstance(existing, dict) else None
    if head == replay["base_sha"]:
        result = executor.execute(commit_packet)
        require(isinstance(result, dict) and isinstance(result.get("sha"), str),
                "candidate commit execution returned no SHA")
        remote_sha = result["sha"]
        mutation = True
        disposition = "REMOTE_CANDIDATE_SUBMITTED"
    else:
        remote_sha = head
    verified = _verify_remote(executor, export, remote_sha)
    final_ref = _ref(executor, api, branch_packet["branch_name"])
    require(final_ref is not None and final_ref.get("object", {}).get("sha") == remote_sha,
            "candidate branch head changed during submission verification")
    receipt_core = {
        "schema_version": 1,
        "status": disposition,
        "submission_key": export["submission_key"],
        "task_id": replay["task_id"],
        "task_hash": replay["task_hash"],
        "repository": replay["repository"],
        "base_sha": replay["base_sha"],
        "branch_name": branch_packet["branch_name"],
        "local_candidate_commit_sha": replay["candidate_commit_sha"],
        "candidate_git_tree_sha": replay["candidate_git_tree_sha"],
        "remote_commit_sha": verified["remote_commit_sha"],
        "remote_tree_sha": verified["remote_tree_sha"],
        "changed_paths": replay["changed_paths"],
        "mutation_performed_this_run": mutation,
        "remote_candidate_present": True,
        "independent_verification": False,
        "pr_created": False,
        "production_changed": False,
        "merge_authorized": False,
        "deployment_authorized": False,
    }
    receipt = {**receipt_core, "receipt_hash": object_hash(receipt_core)}
    if output_path is not None:
        require(not output_path.exists(), "submission receipt already exists")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = submit_candidate(replay_dir=args.replay_dir, output_path=args.output)
    print(json.dumps({"status": receipt["status"], "remote_commit_sha": receipt["remote_commit_sha"],
                      "branch_name": receipt["branch_name"],
                      "mutation_performed_this_run": receipt["mutation_performed_this_run"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
