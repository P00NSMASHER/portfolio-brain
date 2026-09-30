#!/usr/bin/env python3
"""Proof-carrying executor for already-authorized scheduler work.

The scheduler decides *what* may run. This module performs bounded work with
proof-carrying handlers. Repair work is handed to the isolated GitHub-hosted
repair workflow; TEST and VERIFICATION resolve against exact repair-PR checks.
Scheduler state advances only after the relevant handler succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from adapters.github_readonly import GitHubReadOnlyClient, observe_repository
from experiments.experiment_engine import build_experiment_portfolio
from hunting.autonomous_hunter import (
    GitHubPublicProvider,
    load_seed_state as hunter_seed_state,
    run_cycle as run_hunter_cycle,
    validate_state as validate_hunter_state,
)
from hunting.proposal_state import (
    build_proposal_state,
    load_seed_state as hunter_proposal_seed_state,
    validate_state as validate_hunter_proposal_state,
)
from repair.autonomous_repair import (
    AutonomousRepairError,
    find_repair_evidence,
    request_from_scheduler_work,
)
from repair.repair_engine import build_repair_state
from scheduler.autonomous_scheduler import (
    claim_work,
    complete_work,
    load_state as load_scheduler_state,
    now_iso,
    policy as scheduler_policy,
    requeue_work,
    validate_state as validate_scheduler_state,
)
from transfer.cross_project_transfer import build_transfer_state
from uncertainty.highest_value_uncertainty import build_snapshot as build_uncertainty_snapshot

ROOT = Path(__file__).resolve().parents[1]


class WorkExecutionError(RuntimeError):
    pass


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hashv(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def load_json(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return json.loads(p.read_text(encoding="utf-8"))


def _timestamp(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _execution_id(work: dict[str, Any], at: str) -> str:
    seed = {"work_id": work["scheduler_work_id"], "fingerprint": work["fingerprint"], "at": at}
    return "WEXEC-" + hashlib.sha256(canon(seed).encode("utf-8")).hexdigest()[:20].upper()


def _project_adapter(project_ids: list[str]) -> dict[str, Any] | None:
    doc = load_json("adapters/ADAPTER_REGISTRY.json")
    candidates = [
        row
        for row in doc["adapters"]
        if row.get("enabled") is True and set(row.get("project_ids") or []).intersection(project_ids)
    ]
    candidates.sort(key=lambda row: row["adapter_id"])
    return candidates[0] if candidates else None


def _runtime_cursor(runtime_state: dict[str, Any], adapter: dict[str, Any]) -> dict[str, Any] | None:
    repo = runtime_state.get("repositories", {}).get(adapter["repository_id"])
    if not repo:
        return None
    return {"source_ref": repo["source_ref"], "cursor_sha": repo["cursor_sha"], "status": repo["status"]}


def _hunter_proposal_review_handler(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    state=ctx["hunter_proposal_state"]
    validate_hunter_proposal_state(state)
    proposals=[row for row in state["proposals"] if row["proposal_id"]==work["source_ref"]]
    if len(proposals)!=1:
        return {
            "status":"DEFERRED",
            "result_kind":"HUNTER_PROPOSAL_SOURCE_NOT_CURRENT",
            "evidence_refs":[f"hunter-proposal:{work['source_ref']}"],
            "result":{"proposal_id":work["source_ref"]},
        }
    proposal=proposals[0]
    findings=[row for row in state["findings"] if row["proposal_id"]==proposal["proposal_id"]]
    if len(findings)!=1:
        raise WorkExecutionError("Hunter proposal finding missing/duplicate")
    finding=findings[0]
    provider=ctx.get("hunter_provider") or GitHubPublicProvider(os.environ.get("PORTFOLIO_GITHUB_TOKEN"))
    metadata=provider.repository_metadata(finding["repository_full_name"])
    if metadata.get("private") is not False or int(metadata.get("id",0))!=finding["repository_id"]:
        return {
            "status":"DEFERRED",
            "result_kind":"HUNTER_PROPOSAL_REPOSITORY_IDENTITY_DRIFT",
            "evidence_refs":[f"hunter-proposal:{proposal['proposal_id']}",f"repository:{finding['repository_full_name']}"],
            "result":{"proposal_id":proposal["proposal_id"],"repository_full_name":finding["repository_full_name"]},
        }
    exact=provider.inspect_revision(
        {
          "id":finding["repository_id"],
          "full_name":finding["repository_full_name"],
          "default_branch":metadata.get("default_branch") or "main",
          "private":False,
        },
        finding["revision"],
    )
    if exact["tree_sha"]!=finding["inspection"]["tree_sha"]:
        return {
            "status":"DEFERRED",
            "result_kind":"HUNTER_PROPOSAL_EXACT_REVISION_TREE_DRIFT",
            "evidence_refs":[f"hunter-proposal:{proposal['proposal_id']}",f"github:{finding['repository_full_name']}@{finding['revision']}"],
            "result":{"proposal_id":proposal["proposal_id"],"expected_tree_sha":finding["inspection"]["tree_sha"],"observed_tree_sha":exact["tree_sha"]},
        }
    license_meta=metadata.get("license") if isinstance(metadata.get("license"),dict) else {}
    spdx=license_meta.get("spdx_id") if isinstance(license_meta.get("spdx_id"),str) else None
    license_name=license_meta.get("name") if isinstance(license_meta.get("name"),str) else None
    usable_spdx=spdx if spdx not in {None,"","NOASSERTION","OTHER"} else None
    license_state="LICENSE_METADATA_PRESENT_INFORMATIONAL" if usable_spdx else "NO_LICENSE_METADATA_INFORMATIONAL"
    return {
        "status":"SUCCESS",
        "result_kind":"HUNTER_PROPOSAL_PUBLIC_EVIDENCE_REVIEW",
        "evidence_refs":[
          f"hunter-proposal:{proposal['proposal_id']}",
          f"hunter-finding:{finding['finding_id']}",
          f"hunter-cycle:{state['cycle_id']}",
          f"github:{finding['repository_full_name']}@{finding['revision']}",
          f"git-tree:{exact['tree_sha']}",
          f"license-metadata:{usable_spdx or 'NONE'}",
        ],
        "result":{
          "proposal_id":proposal["proposal_id"],
          "finding_id":finding["finding_id"],
          "repository_full_name":finding["repository_full_name"],
          "repository_id":finding["repository_id"],
          "revision":finding["revision"],
          "tree_sha":exact["tree_sha"],
          "rank_score":proposal["candidate_rank_score"],
          "rank_band":proposal["candidate_rank_band"],
          "capability_key":finding["capability_key"],
          "license_spdx_id":usable_spdx,
          "license_name":license_name,
          "license_state":license_state,
          "rights_state":"OPERATOR_ASSUMED",
          "reuse_authorized":False,
          "implementation_authorized":False,
          "code_execution_performed":False,
          "downstream_mutation_performed":False,
        },
    }


def _research_handler(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    if work["source_ref"].startswith("HEXP-"):
        return _hunter_proposal_review_handler(work,ctx)
    adapter = _project_adapter(work["project_ids"])
    if adapter is None:
        return {
            "status": "DEFERRED",
            "result_kind": "NO_ENABLED_REPOSITORY_ADAPTER",
            "evidence_refs": ["adapters/ADAPTER_REGISTRY.json"],
            "result": {"project_ids": work["project_ids"]},
        }
    runtime_state = ctx["runtime_state"]
    cursor = _runtime_cursor(runtime_state, adapter)
    client = ctx.get("github_read_client") or GitHubReadOnlyClient(os.environ.get("PORTFOLIO_GITHUB_TOKEN"))
    receipt = observe_repository(
        adapter,
        cursor,
        fetch_json=client.get_json,
        observed_at=ctx["at"],
    )
    if receipt["status"] == "BLOCKED":
        return {
            "status": "DEFERRED",
            "result_kind": "REPOSITORY_OBSERVATION_BLOCKED",
            "evidence_refs": [f"adapter:{adapter['adapter_id']}", f"blocker:{receipt['blocked_by']}"],
            "result": {
                "repository_id": adapter["repository_id"],
                "repository_full_name": adapter["repository_full_name"],
                "observation_status": receipt["status"],
            },
        }
    refs = [
        f"adapter:{adapter['adapter_id']}",
        f"repository:{adapter['repository_id']}",
        f"observation:{receipt['receipt_hash']}",
    ]
    if receipt.get("current_sha"):
        refs.append(f"github:{adapter['repository_full_name']}@{receipt['current_sha']}")
    return {
        "status": "SUCCESS",
        "result_kind": "REPOSITORY_OBSERVATION",
        "evidence_refs": refs,
        "result": {
            "repository_id": adapter["repository_id"],
            "repository_full_name": adapter["repository_full_name"],
            "observation_status": receipt["status"],
            "prior_sha": receipt.get("prior_sha"),
            "current_sha": receipt.get("current_sha"),
            "network_reads": receipt["network_reads"],
            "changed_files": 0 if receipt.get("compare") is None else len(receipt["compare"]["files"]),
            "receipt_hash": receipt["receipt_hash"],
        },
    }


def _run_shared_hunter(ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    cached = ctx.get("hunter_cache")
    if cached is not None:
        return cached
    state = ctx["hunter_state"]
    provider = ctx.get("hunter_provider") or GitHubPublicProvider(os.environ.get("PORTFOLIO_GITHUB_TOKEN"))
    updated, receipt = run_hunter_cycle(state, provider, at=ctx["at"])
    validate_hunter_state(updated)
    ctx["hunter_state"] = updated
    ctx["hunter_receipt"] = receipt
    ctx["hunter_cache"] = (updated, receipt)
    return updated, receipt


def _hunt_handler(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    _, cycle = _run_shared_hunter(ctx)
    pids = set(work["project_ids"])
    objectives = [row["objective_id"] for row in cycle["objectives"] if pids.intersection(row["project_ids"])]
    findings = [
        row for row in cycle["findings"]
        if pids.intersection(row["project_ids"]) and row["disposition"] == "RETAIN"
    ]
    proposals = [
        row["proposal_id"] for row in cycle["experiment_proposals"]
        if pids.intersection(row["project_ids"])
    ]
    return {
        "status": "SUCCESS",
        "result_kind": "HUNTER_CYCLE",
        "evidence_refs": [
            f"hunter-cycle:{cycle['cycle_id']}",
            f"hunter-receipt:{cycle['receipt_hash']}",
            *[f"hunter-objective:{oid}" for oid in objectives],
        ],
        "result": {
            "cycle_id": cycle["cycle_id"],
            "objective_count": len(objectives),
            "retained_finding_count": len(findings),
            "experiment_proposal_count": len(proposals),
            "inspected_candidates": cycle["inspected_candidates"],
            "api_requests": cycle["api_requests"],
            "disposition": "EXECUTED" if objectives else "NO_ELIGIBLE_OBJECTIVE_THIS_CYCLE",
        },
    }


def _integration_handler(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    state = ctx.get("transfer_state")
    if state is None:
        state = build_transfer_state()
        ctx["transfer_state"] = state
    matches = [p for p in state["proposals"] if p["transfer_id"] == work["source_ref"]]
    if len(matches) != 1:
        return {
            "status": "DEFERRED",
            "result_kind": "TRANSFER_SOURCE_NOT_CURRENT",
            "evidence_refs": [f"transfer:{work['source_ref']}"],
            "result": {"transfer_id": work["source_ref"]},
        }
    proposal = matches[0]
    if proposal["state"] != "ASSESSMENT_READY":
        return {
            "status": "DEFERRED",
            "result_kind": "TRANSFER_NOT_ASSESSMENT_READY",
            "evidence_refs": [f"transfer:{proposal['transfer_id']}", *proposal["provenance_refs"]],
            "result": {"transfer_id": proposal["transfer_id"], "state": proposal["state"]},
        }
    return {
        "status": "SUCCESS",
        "result_kind": "TRANSFER_ASSESSMENT",
        "evidence_refs": [
            f"transfer:{proposal['transfer_id']}",
            f"transfer-proposal:{proposal['proposal_hash']}",
            *proposal["provenance_refs"],
        ],
        "result": {
            "transfer_id": proposal["transfer_id"],
            "source_project_id": proposal["source_project_id"],
            "target_project_id": proposal["target_project_id"],
            "source_capability_key": proposal["source_capability_key"],
            "state": proposal["state"],
            "implementation_allowed": proposal["implementation_allowed"],
            "rights_review_required": proposal["rights_review_required"],
            "hard_blockers": proposal["hard_blockers"],
        },
    }


def _experiment_handler(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    portfolio = ctx.get("experiment_portfolio")
    if portfolio is None:
        portfolio = build_experiment_portfolio(build_uncertainty_snapshot())
        ctx["experiment_portfolio"] = portfolio
    matches = [p for p in portfolio["plans"] if p["experiment_id"] == work["source_ref"]]
    if len(matches) != 1:
        return {
            "status": "DEFERRED",
            "result_kind": "EXPERIMENT_SOURCE_NOT_CURRENT",
            "evidence_refs": [f"experiment:{work['source_ref']}"],
            "result": {"experiment_id": work["source_ref"]},
        }
    plan = matches[0]
    action_ledger = load_json("action_engine/GMAIL_GATEWAY_LEDGER.json")
    outcome_ledger = load_json("experiments/EXPERIMENT_OUTCOME_LEDGER.json")
    project_ids = set(work["project_ids"])
    actions = [
        row for row in action_ledger.get("executions", [])
        if row.get("project_id") in project_ids
    ]
    outcomes = [
        row for row in outcome_ledger.get("outcomes", [])
        if row.get("experiment_id") == plan["experiment_id"]
    ]
    return {
        "status": "SUCCESS",
        "result_kind": "EXPERIMENT_EVIDENCE_ANALYSIS",
        "evidence_refs": [
            f"experiment:{plan['experiment_id']}",
            f"experiment-hash:{plan['experiment_hash']}",
            "action-ledger:action_engine/GMAIL_GATEWAY_LEDGER.json",
            "outcome-ledger:experiments/EXPERIMENT_OUTCOME_LEDGER.json",
            *[f"action:{row['action_id']}" for row in actions],
            *[f"experiment-outcome:{row['outcome_id']}" for row in outcomes],
        ],
        "result": {
            "experiment_id": plan["experiment_id"],
            "plan_status": plan["status"],
            "execution_mode": plan["execution_mode"],
            "autonomous_execution_allowed": plan["autonomous_execution_allowed"],
            "sent_action_receipt_count": sum(1 for row in actions if row.get("status") == "SENT"),
            "recorded_outcome_count": len(outcomes),
            "evidence_disposition": "OUTCOME_RECORDED" if outcomes else "AWAITING_VERIFIED_OUTCOME",
        },
    }


def _repair_handler(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a repair idempotently, but COMPLETE only after a candidate PR exists.

    Preparing or dispatching a request is not completion. The queued scheduler
    item is deliberately released until an exact request-fingerprint candidate
    PR is observable. TEST and VERIFICATION own later check-gate completion.
    """
    repair_state = ctx.get("repair_state")
    if repair_state is None:
        repair_state = build_repair_state()
        ctx["repair_state"] = repair_state
    base_sha = ctx.get("main_sha") or os.environ.get("GITHUB_SHA", "")
    try:
        request = request_from_scheduler_work(work, repair_state, base_sha=base_sha)
    except AutonomousRepairError:
        return {
            "status": "DEFERRED",
            "result_kind": "REPAIR_TASK_NOT_DISPATCHABLE",
            "evidence_refs": [f"repair:{work['source_ref']}", f"scheduler-work:{work['scheduler_work_id']}"],
            "result": {"source_ref": work["source_ref"]},
        }

    evidence = _repair_evidence(work, ctx)
    if (
        evidence.get("status") == "REPAIR_PR_FOUND"
        and evidence.get("repair_fingerprint") == request["fingerprint"]
        and evidence.get("pr_number")
        and evidence.get("head_sha")
    ):
        return {
            "status": "SUCCESS",
            "result_kind": "REPAIR_CANDIDATE_PR_CREATED",
            "evidence_refs": [
                *request["evidence_refs"],
                f"repair-request:{request['request_id']}",
                f"repair-pr:{evidence['pr_number']}",
                f"commit:{evidence['head_sha']}",
                f"repair-fingerprint:{request['fingerprint']}",
            ],
            "result": {
                "request_id": request["request_id"],
                "fingerprint": request["fingerprint"],
                "source_ref": request["source_ref"],
                "pr_number": evidence["pr_number"],
                "head_sha": evidence["head_sha"],
                "factory_work_id": evidence.get("factory_work_id"),
                "factory_preflight_receipt": evidence.get("factory_preflight_receipt"),
                "merge_authority_granted": False,
                "deployment_authority_granted": False,
            },
        }

    dispatches = ctx.setdefault("repair_dispatch_requests", [])
    if not any(row["fingerprint"] == request["fingerprint"] for row in dispatches):
        dispatches.append(request)
    return {
        "status": "DEFERRED",
        "result_kind": "AUTONOMOUS_REPAIR_DISPATCH_REQUESTED",
        "evidence_refs": [*request["evidence_refs"], f"repair-request:{request['request_id']}"],
        "result": {
            "request_id": request["request_id"],
            "fingerprint": request["fingerprint"],
            "source_ref": request["source_ref"],
            "target_path_count": len(request["target_paths"]),
            "candidate_pr_observed": False,
            "merge_authority_granted": False,
            "deployment_authority_granted": False,
        },
    }


def _repair_evidence(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    provider = ctx.get("repair_evidence_provider")
    if provider is not None:
        return provider(work["source_ref"])
    return find_repair_evidence(
        work["source_ref"],
        token=os.environ.get("PORTFOLIO_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN"),
    )


def _test_handler(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    evidence = _repair_evidence(work, ctx)
    refs = [f"repair:{work['source_ref']}"]
    if evidence.get("pr_number"):
        refs.extend([f"repair-pr:{evidence['pr_number']}", f"commit:{evidence['head_sha']}"])
    if evidence.get("foundation_success") is not True:
        return {
            "status": "DEFERRED",
            "result_kind": "REPAIR_FOUNDATION_TEST_PENDING",
            "evidence_refs": refs,
            "result": {
                "source_ref": work["source_ref"],
                "pr_number": evidence.get("pr_number"),
                "foundation_success": False,
            },
        }
    return {
        "status": "SUCCESS",
        "result_kind": "REPAIR_FOUNDATION_TEST_VERIFIED",
        "evidence_refs": refs,
        "result": {
            "source_ref": work["source_ref"],
            "pr_number": evidence["pr_number"],
            "head_sha": evidence["head_sha"],
            "foundation_success": True,
        },
    }


def _verification_handler(work: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    evidence = _repair_evidence(work, ctx)
    refs = [f"repair:{work['source_ref']}"]
    if evidence.get("pr_number"):
        refs.extend([f"repair-pr:{evidence['pr_number']}", f"commit:{evidence['head_sha']}"])
    if evidence.get("foundation_success") is not True or evidence.get("independent_success") is not True:
        return {
            "status": "DEFERRED",
            "result_kind": "REPAIR_INDEPENDENT_VERIFICATION_PENDING",
            "evidence_refs": refs,
            "result": {
                "source_ref": work["source_ref"],
                "pr_number": evidence.get("pr_number"),
                "foundation_success": bool(evidence.get("foundation_success")),
                "independent_success": bool(evidence.get("independent_success")),
            },
        }
    return {
        "status": "SUCCESS",
        "result_kind": "REPAIR_INDEPENDENTLY_VERIFIED",
        "evidence_refs": refs,
        "result": {
            "source_ref": work["source_ref"],
            "pr_number": evidence["pr_number"],
            "head_sha": evidence["head_sha"],
            "foundation_success": True,
            "independent_success": True,
        },
    }


DEFAULT_HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "HUNT": _hunt_handler,
    "EXPERIMENT": _experiment_handler,
    "REPAIR": _repair_handler,
    "TEST": _test_handler,
    "RESEARCH": _research_handler,
    "INTEGRATION": _integration_handler,
    "VERIFICATION": _verification_handler,
}


def _sanitize_handler_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise WorkExecutionError("handler result must be an object")
    required = {"status", "result_kind", "evidence_refs", "result"}
    if set(result) != required:
        raise WorkExecutionError("handler result fields changed")
    if result["status"] not in {"SUCCESS", "DEFERRED"}:
        raise WorkExecutionError("handler result status invalid")
    if not isinstance(result["result_kind"], str) or not result["result_kind"]:
        raise WorkExecutionError("handler result kind invalid")
    if not isinstance(result["evidence_refs"], list) or not all(isinstance(x, str) and x for x in result["evidence_refs"]):
        raise WorkExecutionError("handler evidence refs invalid")
    if not isinstance(result["result"], dict):
        raise WorkExecutionError("handler result payload invalid")
    return result


def execute_cycle(
    state: dict[str, Any],
    *,
    runtime_state: dict[str, Any],
    hunter_state: dict[str, Any] | None = None,
    handlers: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] | None = None,
    max_items: int = 8,
    worker_instance_id: str = "scheduler-work-executor",
    at: str | None = None,
    context_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Execute a bounded set of queued items.

    SUCCESS is the only path to COMPLETE.  DEFERRED and exceptions release the
    lease back to QUEUED and are visible in the execution receipt.
    """
    validate_scheduler_state(state)
    if not isinstance(max_items, int) or not (0 <= max_items <= scheduler_policy()["max_new_work_per_cycle"]):
        raise WorkExecutionError("max_items exceeds bounded scheduler execution limit")
    at = _timestamp(at)
    active_handlers = dict(DEFAULT_HANDLERS if handlers is None else handlers)
    proposal_path=ROOT/"hunting"/"live"/"hunter_proposal_state.json"
    proposal_state=load_json(proposal_path) if proposal_path.exists() else hunter_proposal_seed_state()
    validate_hunter_proposal_state(proposal_state)
    ctx: dict[str, Any] = {
        "at": at,
        "runtime_state": runtime_state,
        "hunter_state": hunter_state if hunter_state is not None else hunter_seed_state(),
        "hunter_proposal_state": proposal_state,
    }
    if context_overrides:
        ctx.update(context_overrides)

    precedence = scheduler_policy()["gate_precedence"]
    queued = [row for row in state["work_items"] if row["state"] == "QUEUED"]
    queued.sort(
        key=lambda row: (
            0 if row["work_type"] in active_handlers else 1,
            precedence.get(row["work_type"], 99),
            row.get("created_at") or "",
            row["scheduler_work_id"],
        )
    )

    out = json.loads(json.dumps(state))
    receipts: list[dict[str, Any]] = []
    executed_work: list[dict[str, Any]] = []
    for work in queued[:max_items]:
        fingerprint = work["fingerprint"]
        started = at
        handler = active_handlers.get(work["work_type"])
        if handler is None:
            result = {
                "status": "DEFERRED",
                "result_kind": "NO_EXECUTION_HANDLER",
                "evidence_refs": [f"scheduler-work:{work['scheduler_work_id']}"],
                "result": {"work_type": work["work_type"]},
            }
            receipts.append(_receipt(work, result, started, at))
            continue

        out = claim_work(
            out,
            fingerprint,
            lease_owner=worker_instance_id,
            lease_seconds=300,
            at=at,
        )
        try:
            result = _sanitize_handler_result(handler(work, ctx))
        except Exception as exc:
            out = requeue_work(out, fingerprint, at=at)
            error_result = {
                "status": "DEFERRED",
                "result_kind": "EXECUTION_ERROR",
                "evidence_refs": [f"scheduler-work:{work['scheduler_work_id']}"],
                "result": {"error_class": type(exc).__name__},
            }
            receipts.append(_receipt(work, error_result, started, at))
            continue

        if result["status"] == "SUCCESS":
            out = complete_work(out, fingerprint, at=at)
            executed_work.append({
                "scheduler_work_id": work["scheduler_work_id"],
                "source_ref": work["source_ref"],
                "fingerprint": work["fingerprint"],
                "assigned_agent_id": work["assigned_agent_id"],
                "project_ids": work["project_ids"],
                "work_type": work["work_type"],
            })
        else:
            out = requeue_work(out, fingerprint, at=at)
        receipts.append(_receipt(work, result, started, at))

    validate_scheduler_state(out)
    summary = {
        "schema_version": "1.0.0",
        "cycle_id": "wexec-" + hashlib.sha256(canon([r["execution_id"] for r in receipts]).encode("utf-8")).hexdigest()[:24],
        "finished_at": at,
        "attempted_count": len(receipts),
        "completed_count": sum(1 for r in receipts if r["status"] == "SUCCESS"),
        "deferred_count": sum(1 for r in receipts if r["status"] == "DEFERRED"),
        "remaining_queued_count": sum(1 for row in out["work_items"] if row["state"] == "QUEUED"),
        "authority_granted": False,
    }
    summary["receipt_hash"] = hashv(summary)
    return out, receipts, executed_work, {"context": ctx, "summary": summary}


def _receipt(work: dict[str, Any], result: dict[str, Any], started_at: str, finished_at: str) -> dict[str, Any]:
    body = {
        "schema_version": "1.0.0",
        "execution_id": _execution_id(work, started_at),
        "scheduler_work_id": work["scheduler_work_id"],
        "fingerprint": work["fingerprint"],
        "work_type": work["work_type"],
        "assigned_agent_id": work["assigned_agent_id"],
        "project_ids": work["project_ids"],
        "started_at": started_at,
        "finished_at": finished_at,
        "status": result["status"],
        "result_kind": result["result_kind"],
        "result": result["result"],
        "evidence_refs": list(dict.fromkeys(result["evidence_refs"])),
        "authority_granted": False,
    }
    return {**body, "receipt_hash": hashv(body)}


def write_outputs(
    *,
    scheduler_state: dict[str, Any],
    receipts: list[dict[str, Any]],
    executed_work: list[dict[str, Any]],
    meta: dict[str, Any],
    output_dir: Path,
    hunter_output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "scheduler_state.json").write_text(json.dumps(scheduler_state, indent=2) + "\n", encoding="utf-8")
    (output_dir / "execution_receipts.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")
    (output_dir / "executed_work.json").write_text(json.dumps(executed_work, indent=2) + "\n", encoding="utf-8")
    (output_dir / "execution_cycle_receipt.json").write_text(json.dumps(meta["summary"], indent=2) + "\n", encoding="utf-8")

    ctx = meta["context"]
    repair_dispatches = ctx.get("repair_dispatch_requests") or []
    if repair_dispatches:
        (output_dir / "repair_dispatch_requests.json").write_text(
            json.dumps(repair_dispatches, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if ctx.get("hunter_receipt") is not None:
        hunter_output_dir.mkdir(parents=True, exist_ok=True)
        state = ctx["hunter_state"]
        cycle = ctx["hunter_receipt"]
        (hunter_output_dir / "hunter_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        (hunter_output_dir / "hunt_cycle_receipt.json").write_text(json.dumps(cycle, indent=2) + "\n", encoding="utf-8")
        (hunter_output_dir / "hunt_objectives.json").write_text(json.dumps(cycle["objectives"], indent=2) + "\n", encoding="utf-8")
        (hunter_output_dir / "hunt_findings.json").write_text(json.dumps(cycle["findings"], indent=2) + "\n", encoding="utf-8")
        (hunter_output_dir / "experiment_proposals.json").write_text(json.dumps(cycle["experiment_proposals"], indent=2) + "\n", encoding="utf-8")
        proposal_state=build_proposal_state(
            state,
            cycle,
            prior_state=ctx.get("hunter_proposal_state"),
        )
        (hunter_output_dir / "hunter_proposal_state.json").write_text(json.dumps(proposal_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute bounded queued Portfolio Brain work")
    parser.add_argument("--state", default="scheduler/out/scheduler_state.json")
    parser.add_argument("--runtime-state", default="runtime/live/runtime_state.json")
    parser.add_argument("--hunter-state", default="hunting/live/hunter_state.json")
    parser.add_argument("--output-dir", default="scheduler/out")
    parser.add_argument("--hunter-output-dir", default="hunting/out")
    parser.add_argument("--max-items", type=int, default=8)
    parser.add_argument("--worker-instance-id", default=None)
    parser.add_argument("--at", default=None)
    args = parser.parse_args()

    state = load_scheduler_state(args.state)
    runtime_state = load_json(args.runtime_state)
    hunter_path = Path(args.hunter_state)
    hunter_state = load_json(hunter_path) if hunter_path.exists() else hunter_seed_state()
    run_id = os.environ.get("GITHUB_RUN_ID") or "local"
    worker_id = args.worker_instance_id or f"portfolio-scheduler:{run_id}"
    updated, receipts, executed, meta = execute_cycle(
        state,
        runtime_state=runtime_state,
        hunter_state=hunter_state,
        max_items=args.max_items,
        worker_instance_id=worker_id,
        at=args.at or now_iso(),
    )
    write_outputs(
        scheduler_state=updated,
        receipts=receipts,
        executed_work=executed,
        meta=meta,
        output_dir=Path(args.output_dir),
        hunter_output_dir=Path(args.hunter_output_dir),
    )
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"executed_count={len(executed)}\n")
            fh.write(f"attempted_count={len(receipts)}\n")
            fh.write(f"remaining_queued={meta['summary']['remaining_queued_count']}\n")
    print(json.dumps(meta["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
