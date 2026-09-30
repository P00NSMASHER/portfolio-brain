#!/usr/bin/env python3
"""Bridge scheduler-admitted REPAIR work into the governed software factory.

This module is intentionally limited to scheduler-origin repairs for the
portfolio-brain repository. Workflow-failure repairs retain their existing
allowlisted workflow-repair lane. The factory bridge can create only an
isolated candidate branch, candidate commit, and pull request; it has no merge,
deployment, default-branch, settings, or secrets operation.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from repair.autonomous_repair import validate_request
from software_factory.github_executor import GitHubExecutor
from software_factory.software_factory import SoftwareFactory, hashv, make_commit_action, req

REPOSITORY_ID = "REPO-008"
PROJECT_ID = "PRJ-000"
VERIFIER_AGENT_ID = "AGT-TESTER"
TEST_COMMANDS = [
    "python -m compileall -q portfolio-brain modules",
    "python -m operations.validate_operating_mode",
    'python -m unittest discover -s tests -p "test_*.py" -v',
]


def _attempt_key(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    req(bool(cleaned), "factory repair attempt id missing")
    return cleaned[:20]


def factory_work_id(request: dict[str, Any], attempt_id: str) -> str:
    validate_request(request)
    req(request["source_kind"] == "SCHEDULER_REPAIR_TASK", "factory bridge accepts scheduler repair tasks only")
    fingerprint = request["fingerprint"].split(":", 1)[1][:16].upper()
    return f"AUTO-REPAIR-{fingerprint}-{_attempt_key(attempt_id)}"


def _issue_ref(request: dict[str, Any]) -> str:
    return (
        f"REPAIR_SOURCE_REF:{request['source_ref']}\n"
        f"AUTO_REPAIR_FINGERPRINT:{request['fingerprint']}"
    )


def _executor(token: str | None, executor: GitHubExecutor | None) -> GitHubExecutor:
    if executor is not None:
        return executor
    req(isinstance(token, str) and bool(token), "factory GitHub token required")
    return GitHubExecutor(token)


def start_factory_repair(
    request: dict[str, Any],
    *,
    db_path: Path,
    attempt_id: str,
    executor: GitHubExecutor | None = None,
    token: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Create and claim one isolated factory attempt, then create its branch."""
    validate_request(request)
    req(request["source_kind"] == "SCHEDULER_REPAIR_TASK", "factory bridge accepts scheduler repair tasks only")
    work_id = factory_work_id(request, attempt_id)
    ex = _executor(token, executor)
    sf = SoftwareFactory(db_path)
    try:
        sf.enqueue(
            work_id=work_id,
            project_id=PROJECT_ID,
            repository_id=REPOSITORY_ID,
            base_sha=request["base_sha"],
            title=f"repair {request['source_ref']}",
            issue_ref=_issue_ref(request),
            verifier_agent_id=VERIFIER_AGENT_ID,
            provenance_refs=list(dict.fromkeys([
                *request["evidence_refs"],
                f"repair-request:{request['request_id']}",
                f"repair-fingerprint:{request['fingerprint']}",
            ])),
            now=now,
        )
        branch_packet = sf.claim(work_id, "AGT-ENGINEER", now=now)
        ex.execute(branch_packet)
        work = sf.get(work_id)
        req(work["state"] == "RUNNING", "factory work did not enter RUNNING")
        req(work["branch_name"].startswith("factory/auto-repair-"), "factory branch is not protected-integration eligible")
        receipt = {
            "schema_version": "1.0.0",
            "status": "BRANCH_READY",
            "factory_work_id": work_id,
            "request_id": request["request_id"],
            "fingerprint": request["fingerprint"],
            "base_sha": request["base_sha"],
            "branch_name": work["branch_name"],
            "branch_action_id": branch_packet["action_id"],
            "factory_state": work["state"],
            "merge_authority_granted": False,
            "deployment_authority_granted": False,
            "default_branch_write_authority_granted": False,
        }
        receipt["receipt_hash"] = hashv(receipt)
        return receipt
    finally:
        sf.close()


def _candidate_files(root: Path, changed_paths: list[str]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for path in changed_paths:
        target = (root / path).resolve()
        req(root.resolve() in target.parents and target.is_file(), f"candidate path missing or escaped root: {path}")
        raw = target.read_bytes()
        files.append({
            "path": path,
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "content_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        })
    return files


def finalize_factory_repair(
    request: dict[str, Any],
    validation: dict[str, Any],
    *,
    test_log: bytes,
    candidate_root: Path,
    db_path: Path,
    attempt_id: str,
    executor: GitHubExecutor | None = None,
    token: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Commit a tested candidate through the factory and open its protected PR."""
    validate_request(request)
    req(request["source_kind"] == "SCHEDULER_REPAIR_TASK", "factory bridge accepts scheduler repair tasks only")
    req(validation.get("request_id") == request["request_id"], "factory diff validation request mismatch")
    req(validation.get("fingerprint") == request["fingerprint"], "factory diff validation fingerprint mismatch")
    changed_paths = validation.get("changed_paths")
    req(isinstance(changed_paths, list) and bool(changed_paths), "factory candidate changed paths missing")
    req(isinstance(test_log, bytes) and bool(test_log.strip()), "factory regression test log missing")
    diff_hash = validation.get("diff_hash")
    req(isinstance(diff_hash, str) and diff_hash.startswith("sha256:") and len(diff_hash) == 71,
        "factory diff hash missing")

    work_id = factory_work_id(request, attempt_id)
    ex = _executor(token, executor)
    sf = SoftwareFactory(db_path)
    try:
        work = sf.get(work_id)
        req(work["state"] == "RUNNING", "factory work is not RUNNING before candidate commit")
        files = _candidate_files(candidate_root, changed_paths)
        commit_packet = make_commit_action(
            work,
            files,
            f"Autonomous repair {request['source_ref']}",
        )
        commit = ex.execute(commit_packet)
        commit_sha = commit.get("sha")
        req(isinstance(commit_sha, str) and len(commit_sha) == 40, "factory candidate commit SHA invalid")

        test_receipt_hash = "sha256:" + hashlib.sha256(test_log).hexdigest()
        sf.record_candidate_commit(
            work_id,
            "AGT-ENGINEER",
            commit_sha=commit_sha,
            changed_paths=changed_paths,
            test_commands=TEST_COMMANDS,
            test_receipt_hashes=[test_receipt_hash],
            diff_hash=diff_hash,
            now=now,
        )
        report_hash = hashv({
            "factory_work_id": work_id,
            "request_fingerprint": request["fingerprint"],
            "candidate_commit_sha": commit_sha,
            "diff_hash": diff_hash,
            "test_receipt_hash": test_receipt_hash,
        })
        verification_id = sf.verify(
            work_id,
            VERIFIER_AGENT_ID,
            "PASS",
            report_hash=report_hash,
            evidence_refs=[
                f"repair-request:{request['request_id']}",
                f"candidate-commit:{commit_sha}",
                f"candidate-diff:{diff_hash}",
                f"factory-test-receipt:{test_receipt_hash}",
            ],
            now=now,
        )
        pr_packet = sf.pr_action(work_id)
        body = pr_packet.get("pr_body") or ""
        req(f"REPAIR_SOURCE_REF:{request['source_ref']}" in body, "factory PR missing repair source marker")
        req(f"AUTO_REPAIR_FINGERPRINT:{request['fingerprint']}" in body, "factory PR missing protected integration marker")
        pr = ex.execute(pr_packet)
        pr_number = pr.get("number")
        pr_url = pr.get("html_url")
        req(type(pr_number) is int and pr_number > 0, "factory PR number invalid")
        req(isinstance(pr_url, str) and bool(pr_url), "factory PR URL invalid")
        sf.record_pr(work_id, pr_number=pr_number, pr_url=pr_url, head_sha=commit_sha, now=now)
        work = sf.get(work_id)
        req(work["state"] == "PR_OPEN", "factory work did not enter PR_OPEN")
        req(sf.event_chain_valid(), "factory event chain invalid")

        receipt = {
            "schema_version": "1.0.0",
            "status": "PR_OPEN",
            "factory_work_id": work_id,
            "request_id": request["request_id"],
            "fingerprint": request["fingerprint"],
            "base_sha": request["base_sha"],
            "branch_name": work["branch_name"],
            "candidate_commit_sha": commit_sha,
            "changed_paths": changed_paths,
            "diff_hash": diff_hash,
            "test_receipt_hash": test_receipt_hash,
            "factory_verification_id": verification_id,
            "pr_number": pr_number,
            "pr_url": pr_url,
            "foundation_success": False,
            "hosted_independent_success": False,
            "technical_candidate_tested": True,
            "market_verified": False,
            "revenue_verified": False,
            "merge_authority_granted": False,
            "deployment_authority_granted": False,
            "default_branch_write_authority_granted": False,
        }
        receipt["receipt_hash"] = hashv(receipt)
        return receipt
    finally:
        sf.close()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Route scheduler REPAIR through the governed software factory")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("start")
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--attempt-id", required=True)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("finalize")
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--validation", type=Path, required=True)
    p.add_argument("--test-log", type=Path, required=True)
    p.add_argument("--candidate-root", type=Path, default=Path("."))
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--attempt-id", required=True)
    p.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    token = os.environ.get("PORTFOLIO_FACTORY_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if args.command == "start":
        receipt = start_factory_repair(
            _load(args.request),
            db_path=args.db,
            attempt_id=args.attempt_id,
            token=token,
        )
    else:
        receipt = finalize_factory_repair(
            _load(args.request),
            _load(args.validation),
            test_log=args.test_log.read_bytes(),
            candidate_root=args.candidate_root.resolve(),
            db_path=args.db,
            attempt_id=args.attempt_id,
            token=token,
        )
    _write(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
