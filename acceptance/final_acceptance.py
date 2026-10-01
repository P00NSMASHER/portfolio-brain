#!/usr/bin/env python3
"""Fail-closed validators for Portfolio Brain final acceptance evidence.

These validators do not perform or claim Steps 21-25. They define the minimum
machine-readable evidence that a later live acceptance run must produce.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "acceptance" / "FINAL_ACCEPTANCE_POLICY.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256P = re.compile(r"^sha256:[0-9a-f]{64}$")


class FinalAcceptanceError(ValueError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise FinalAcceptanceError(message)


def _load_policy() -> dict[str, Any]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    _require(policy.get("schema_version") == "1.0.0", "final acceptance policy schema drifted")
    _require(policy.get("policy_id") == "portfolio-final-acceptance-v1", "final acceptance policy identity drifted")
    _require(policy.get("hosted_verifier_app_id") == 5121826, "hosted verifier trust anchor drifted")
    _require(policy.get("foundation_app_id") == 15368, "Foundation trust anchor drifted")
    _require(policy.get("foundation_check_name") == "validate", "Foundation check name drifted")
    _require(policy.get("hosted_verifier_check_name") == "portfolio-phase1-gate",
             "hosted verifier check name drifted")
    return policy


def _load_security_contract() -> dict[str, Any]:
    path = ROOT / "verification" / "STEP24_SECURITY_CONTRACT.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    _require(contract.get("schema_version") == "1.0.0", "Step 24 security contract schema drifted")
    _require(contract.get("review_id") == "portfolio-step24-least-privilege-v1",
             "Step 24 security contract identity drifted")
    domains = contract.get("required_domains")
    _require(isinstance(domains, list) and domains and len(domains) == len(set(domains)),
             "Step 24 required security domains invalid")
    return contract


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def bind_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    return body | {"receipt_hash": canonical_hash(body)}


def _validate_receipt_hash(receipt: dict[str, Any]) -> None:
    _require(isinstance(receipt, dict), "acceptance receipt must be an object")
    observed = receipt.get("receipt_hash")
    _require(isinstance(observed, str) and SHA256P.fullmatch(observed) is not None, "acceptance receipt hash invalid")
    body = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    _require(observed == canonical_hash(body), "acceptance receipt hash mismatch")


def _validate_sha40(value: Any, field: str) -> None:
    _require(isinstance(value, str) and SHA40.fullmatch(value) is not None, f"{field} must be a 40-hex commit SHA")


def _validate_sha256(value: Any, field: str) -> None:
    _require(isinstance(value, str) and SHA256P.fullmatch(value) is not None, f"{field} must be sha256:<64 hex>")


def _validate_trusted_check(check: Any, *, field: str, expected_name: str,
                            expected_app_id: int, expected_head_sha: str) -> int:
    _require(isinstance(check, dict), f"{field} evidence missing")
    run_id = check.get("check_run_id")
    _require(type(run_id) is int and run_id > 0, f"{field} check_run_id invalid")
    _require(check.get("name") == expected_name, f"{field} check name mismatch")
    _require(check.get("app_id") == expected_app_id, f"{field} App identity mismatch")
    _validate_sha40(check.get("head_sha"), f"{field}.head_sha")
    _require(check["head_sha"] == expected_head_sha, f"{field} is not bound to exact head")
    _require(check.get("conclusion") == "success", f"{field} did not succeed")
    return run_id


def _timestamp(value: Any, field: str) -> datetime:
    _require(isinstance(value, str) and value, f"{field} timestamp missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinalAcceptanceError(f"{field} timestamp invalid") from exc
    _require(parsed.tzinfo is not None, f"{field} timestamp requires timezone")
    return parsed


def _positive_int_list(values: Any, field: str) -> list[int]:
    _require(isinstance(values, list), f"{field} must be a list")
    _require(all(type(v) is int and v > 0 for v in values), f"{field} contains invalid identifier")
    _require(len(values) == len(set(values)), f"{field} contains duplicates")
    return values


def _hash_list(values: Any, field: str) -> list[str]:
    _require(isinstance(values, list), f"{field} must be a list")
    for value in values:
        _validate_sha256(value, field)
    _require(len(values) == len(set(values)), f"{field} contains duplicates")
    return values


def _sha_list(values: Any, field: str) -> list[str]:
    _require(isinstance(values, list), f"{field} must be a list")
    for value in values:
        _validate_sha40(value, field)
    _require(len(values) == len(set(values)), f"{field} contains duplicates")
    return values


def _validate_stage(stage: dict[str, Any], expected_id: str) -> None:
    _require(isinstance(stage, dict), f"{expected_id} stage must be an object")
    _require(stage.get("stage_id") == expected_id, f"stage order/identity mismatch: expected {expected_id}")
    _require(stage.get("status") == "PASS", f"{expected_id} is not PASS")
    _timestamp(stage.get("occurred_at"), f"{expected_id}.occurred_at")
    run_ids = _positive_int_list(stage.get("run_ids"), f"{expected_id}.run_ids")
    pr_numbers = _positive_int_list(stage.get("pr_numbers"), f"{expected_id}.pr_numbers")
    check_ids = _positive_int_list(stage.get("check_run_ids"), f"{expected_id}.check_run_ids")
    artifact_hashes = _hash_list(stage.get("artifact_hashes"), f"{expected_id}.artifact_hashes")
    state_hashes = _hash_list(stage.get("state_hashes"), f"{expected_id}.state_hashes")
    source_shas = _sha_list(stage.get("source_shas"), f"{expected_id}.source_shas")
    total = sum(map(len, [run_ids, pr_numbers, check_ids, artifact_hashes, state_hashes, source_shas]))
    _require(total > 0, f"{expected_id} has no bound evidence")


def _validate_stages(receipt: dict[str, Any], expected: list[str]) -> dict[str, dict[str, Any]]:
    stages = receipt.get("stages")
    _require(isinstance(stages, list) and len(stages) == len(expected), "acceptance stage count mismatch")
    observed = [row.get("stage_id") if isinstance(row, dict) else None for row in stages]
    _require(observed == expected, "acceptance stage order changed")
    by_id = {}
    previous_at = None
    for stage_id, stage in zip(expected, stages):
        _validate_stage(stage, stage_id)
        occurred_at = _timestamp(stage["occurred_at"], f"{stage_id}.occurred_at")
        if previous_at is not None:
            _require(occurred_at >= previous_at, f"{stage_id} occurred before its predecessor")
        previous_at = occurred_at
        by_id[stage_id] = stage
    return by_id


def _common(receipt: dict[str, Any], *, step: int) -> None:
    _validate_receipt_hash(receipt)
    _require(receipt.get("schema_version") == "1.0.0", f"Step {step} receipt schema drifted")
    _require(receipt.get("step") == step, f"Step {step} receipt step mismatch")
    _require(receipt.get("status") == "PASS", f"Step {step} cannot complete without PASS")
    _validate_sha40(receipt.get("exact_main_sha"), f"Step {step}.exact_main_sha")


def validate_step21(receipt: dict[str, Any]) -> None:
    policy = _load_policy()
    _common(receipt, step=21)
    _require(receipt.get("fixture_kind") == "HARMLESS_BOUNDED", "Step 21 fixture is not harmless/bounded")
    _require(receipt.get("bounded_authority") is True, "Step 21 authority is not bounded")
    _require(receipt.get("protected_promotion") is True, "Step 21 promotion was not protected")
    _require(receipt.get("hosted_verifier_app_id") == policy["hosted_verifier_app_id"], "Step 21 verifier App mismatch")
    _require(isinstance(receipt.get("canary_id"), str) and receipt["canary_id"], "Step 21 canary identity missing")
    candidate_pr = receipt.get("candidate_pr_number")
    _require(type(candidate_pr) is int and candidate_pr > 0, "Step 21 candidate PR invalid")
    _validate_sha40(receipt.get("candidate_head_sha"), "Step 21.candidate_head_sha")
    _validate_sha40(receipt.get("promotion_merge_sha"), "Step 21.promotion_merge_sha")
    _require(receipt["promotion_merge_sha"] == receipt["exact_main_sha"], "Step 21 promotion merge SHA is not exact main")
    stages = _validate_stages(receipt, policy["step21_stages"])
    foundation_check_id = _validate_trusted_check(
        receipt.get("foundation_check"),
        field="Step 21 Foundation",
        expected_name=policy["foundation_check_name"],
        expected_app_id=policy["foundation_app_id"],
        expected_head_sha=receipt["candidate_head_sha"],
    )
    verifier_check_id = _validate_trusted_check(
        receipt.get("hosted_verifier_check"),
        field="Step 21 hosted verifier",
        expected_name=policy["hosted_verifier_check_name"],
        expected_app_id=policy["hosted_verifier_app_id"],
        expected_head_sha=receipt["candidate_head_sha"],
    )
    _require(foundation_check_id in stages["tests"]["check_run_ids"],
             "Step 21 Foundation check is not bound to tests stage")
    _require(verifier_check_id in stages["independent_verifier"]["check_run_ids"],
             "Step 21 hosted verifier check is not bound to verifier stage")
    _require(stages["independent_verifier"]["check_run_ids"], "Step 21 independent verifier check missing")
    _require(candidate_pr in stages["protected_promotion"]["pr_numbers"], "Step 21 promotion PR does not match candidate")
    _require(receipt["candidate_head_sha"] in stages["tests"]["source_shas"], "Step 21 tests are not bound to candidate head")
    _require(receipt["candidate_head_sha"] in stages["independent_verifier"]["source_shas"], "Step 21 verifier is not bound to candidate head")
    _require(receipt["exact_main_sha"] in stages["protected_promotion"]["source_shas"], "Step 21 protected promotion is not bound to merged main")
    _require(stages["verified_outcome"]["state_hashes"], "Step 21 verified outcome state hash missing")
    _require(stages["feedback_learning"]["state_hashes"], "Step 21 feedback/learning state hash missing")
    _require(stages["next_scheduling_cycle"]["run_ids"], "Step 21 next scheduling cycle run missing")


STEP22_MAINTENANCE_EXACT_PATHS = {
    "state_journal/ARCHIVE_MANIFEST.json",
    "state_journal/CHECKPOINT.json.gz",
    "state_journal/POLICY.json",
}
STEP22_MAINTENANCE_PREFIXES = ("state_journal/archive/",)


def _validate_step22_maintenance(receipt: dict[str, Any], policy: dict[str, Any]) -> None:
    repair_merge = receipt["repair_merge_sha"]
    exact_main = receipt["exact_main_sha"]
    lineage = receipt.get("maintenance_lineage")
    _require(isinstance(lineage, list), "Step 22 maintenance lineage must be a list")
    if repair_merge == exact_main:
        _require(lineage == [], "Step 22 maintenance lineage present without a main transition")
        return

    _require(len(lineage) == 1, "Step 22 permits exactly one bounded checkpoint/archive maintenance merge")
    row = lineage[0]
    _require(isinstance(row, dict), "Step 22 maintenance row invalid")
    _require(row.get("kind") == "CHECKPOINT_ARCHIVE_MAINTENANCE",
             "Step 22 intervening merge is not checkpoint/archive maintenance")
    _validate_sha40(row.get("base_sha"), "Step 22 maintenance.base_sha")
    _validate_sha40(row.get("head_sha"), "Step 22 maintenance.head_sha")
    _validate_sha40(row.get("merge_sha"), "Step 22 maintenance.merge_sha")
    _require(row["base_sha"] == repair_merge, "Step 22 maintenance does not start at repair merge")
    _require(row["merge_sha"] == exact_main, "Step 22 maintenance does not end at exact continuation main")
    pr_number = row.get("pr_number")
    run_id = row.get("workflow_run_id")
    _require(type(pr_number) is int and pr_number > 0, "Step 22 maintenance PR invalid")
    _require(type(run_id) is int and run_id > 0, "Step 22 maintenance workflow run invalid")
    _require(row.get("actor_login") == "github-actions[bot]",
             "Step 22 maintenance PR was not bot-created")
    branch = row.get("branch")
    _require(isinstance(branch, str) and branch.startswith("checkpoint/archive-"),
             "Step 22 maintenance branch is not checkpoint/archive isolated")
    _require(row.get("protected_merge") is True, "Step 22 maintenance merge was not protected")
    _require(row.get("authority_granted") is False and row.get("evidence_upgraded") is False,
             "Step 22 maintenance widened authority/evidence")

    paths = row.get("changed_paths")
    _require(isinstance(paths, list) and paths and len(paths) == len(set(paths)),
             "Step 22 maintenance changed paths invalid")
    for changed in paths:
        _require(
            changed in STEP22_MAINTENANCE_EXACT_PATHS
            or any(changed.startswith(prefix) for prefix in STEP22_MAINTENANCE_PREFIXES),
            f"Step 22 maintenance touched non-archive path: {changed}",
        )
    _require(STEP22_MAINTENANCE_EXACT_PATHS.issubset(set(paths)),
             "Step 22 maintenance omitted required checkpoint/archive control files")
    _require(any(path.startswith("state_journal/archive/") for path in paths),
             "Step 22 maintenance contains no immutable archive path")

    _validate_trusted_check(
        row.get("foundation_check"),
        field="Step 22 maintenance Foundation",
        expected_name=policy["foundation_check_name"],
        expected_app_id=policy["foundation_app_id"],
        expected_head_sha=row["head_sha"],
    )
    _validate_trusted_check(
        row.get("hosted_verifier_check"),
        field="Step 22 maintenance hosted verifier",
        expected_name=policy["hosted_verifier_check_name"],
        expected_app_id=policy["hosted_verifier_app_id"],
        expected_head_sha=row["head_sha"],
    )
    archive_id = row.get("archive_id")
    checkpoint_sequence = row.get("checkpoint_sequence")
    _require(isinstance(archive_id, str) and archive_id.startswith("canonical-archive-seq-"),
             "Step 22 maintenance archive identity invalid")
    _require(type(checkpoint_sequence) is int and checkpoint_sequence > 0,
             "Step 22 maintenance checkpoint sequence invalid")


def validate_step22(receipt: dict[str, Any]) -> None:
    policy = _load_policy()
    _common(receipt, step=22)
    _require(receipt.get("fault_mechanism") == "CONTROLLED_REPRODUCIBLE_FIXTURE", "Step 22 fault mechanism is not controlled")
    _require(receipt.get("production_main_damaged") is False, "Step 22 damaged production main")
    _require(receipt.get("fault_reversible") is True, "Step 22 fault is not reversible")
    _require(receipt.get("new_regression_added") is True, "Step 22 repair lacks a NEW regression")
    _require(receipt.get("full_test_suite_passed") is True, "Step 22 full test suite did not pass")
    _require(receipt.get("repair_branch_prefix") == "factory/auto-repair-", "Step 22 repair was not isolated")
    _require(receipt.get("hosted_verifier_app_id") == policy["hosted_verifier_app_id"], "Step 22 verifier App mismatch")
    _require(receipt.get("human_verifier_required") is False, "Step 22 still requires a human verifier")
    _require(receipt.get("laptop_verifier_required") is False, "Step 22 still requires a laptop verifier")
    _require(receipt.get("repair_pr_actor_kind") == "BOT", "Step 22 repair PR was not bot-created")
    _require(receipt.get("repair_pr_actor_login") == "github-actions[bot]",
             "Step 22 repair PR actor is not the governed automation bot")
    repair_pr = receipt.get("repair_pr_number")
    _require(type(repair_pr) is int and repair_pr > 0, "Step 22 repair PR invalid")
    _validate_sha40(receipt.get("repair_head_sha"), "Step 22.repair_head_sha")
    _validate_sha40(receipt.get("repair_merge_sha"), "Step 22.repair_merge_sha")
    _require(receipt.get("protected_merge") is True, "Step 22 merge was not protected")
    _validate_step22_maintenance(receipt, policy)
    stages = _validate_stages(receipt, policy["step22_stages"])
    _require(stages["new_regression_added"]["artifact_hashes"] or stages["new_regression_added"]["source_shas"],
             "Step 22 regression evidence missing")
    foundation_check_id = _validate_trusted_check(
        receipt.get("foundation_check"),
        field="Step 22 Foundation",
        expected_name=policy["foundation_check_name"],
        expected_app_id=policy["foundation_app_id"],
        expected_head_sha=receipt["repair_head_sha"],
    )
    verifier_check_id = _validate_trusted_check(
        receipt.get("hosted_verifier_check"),
        field="Step 22 hosted verifier",
        expected_name=policy["hosted_verifier_check_name"],
        expected_app_id=policy["hosted_verifier_app_id"],
        expected_head_sha=receipt["repair_head_sha"],
    )
    _require(foundation_check_id in stages["foundation_exact_head"]["check_run_ids"],
             "Step 22 Foundation evidence does not match exact-head stage")
    _require(verifier_check_id in stages["hosted_verifier_gate"]["check_run_ids"],
             "Step 22 hosted verifier evidence does not match gate stage")
    _require(stages["foundation_exact_head"]["check_run_ids"], "Step 22 exact-head Foundation check missing")
    _require(stages["hosted_verifier_gate"]["check_run_ids"], "Step 22 hosted verifier check missing")
    _require(repair_pr in stages["repair_pr_opened"]["pr_numbers"], "Step 22 repair PR stage does not match repair PR")
    _require(receipt["repair_head_sha"] in stages["foundation_exact_head"]["source_shas"], "Step 22 Foundation check is not bound to repair head")
    _require(receipt["repair_head_sha"] in stages["hosted_verifier_gate"]["source_shas"], "Step 22 hosted verifier is not bound to repair head")
    _require(receipt["repair_merge_sha"] in stages["protected_merge"]["source_shas"],
             "Step 22 protected merge is not bound to repair merge")
    for key in ("subsequent_runtime_cycle", "subsequent_reducer_cycle", "subsequent_scheduler_cycle"):
        _require(stages[key]["run_ids"], f"Step 22 {key} proof missing")
        _require(receipt["exact_main_sha"] in stages[key]["source_shas"], f"Step 22 {key} is not bound to repaired main")


def validate_step23(receipt: dict[str, Any]) -> None:
    policy = _load_policy()
    _common(receipt, step=23)
    cfg = policy["step23"]
    _require(receipt.get("run_classification_policy") == "EXPLICIT", "Step 23 run classification is not explicit")
    _require(receipt.get("hash_traceability_pass") is True, "Step 23 hash traceability failed")
    _require(receipt.get("dashboard_fresh") is True, "Step 23 dashboard is stale")

    runs = receipt.get("runs")
    _require(isinstance(runs, list) and runs, "Step 23 run evidence missing")
    successes = {name: 0 for name in cfg["required_workflows"]}
    successful_run_ids = {name: set() for name in cfg["required_workflows"]}
    seen_run_ids: set[int] = set()
    runs_by_id: dict[int, dict[str, Any]] = {}
    coalesced_rows: list[dict[str, Any]] = []
    for row in runs:
        _require(isinstance(row, dict), "Step 23 run row invalid")
        workflow = row.get("workflow")
        _require(workflow in successes, f"Step 23 unexpected workflow: {workflow}")
        _require(row.get("event") == "schedule", f"Step 23 {workflow} evidence is not scheduled")
        _require(row.get("classification") in {"SUCCESS", "CANCELLED_COALESCED", "FAILURE"},
                 f"Step 23 {workflow} classification invalid")
        classification = row["classification"]
        conclusion = row.get("conclusion")
        _require(conclusion in {
            "success", "cancelled", "failure", "timed_out", "action_required",
            "startup_failure", "stale", "neutral", "skipped",
        }, f"Step 23 {workflow} raw conclusion invalid")
        created_at = _timestamp(row.get("created_at"), f"Step 23 {workflow}.created_at")
        completed_at = _timestamp(row.get("completed_at"), f"Step 23 {workflow}.completed_at")
        _require(completed_at >= created_at, f"Step 23 {workflow} completed before it was created")
        _require(type(row.get("run_id")) is int and row["run_id"] > 0, f"Step 23 {workflow} run_id invalid")
        _require(row["run_id"] not in seen_run_ids, f"Step 23 duplicate workflow run id: {row['run_id']}")
        seen_run_ids.add(row["run_id"])
        runs_by_id[row["run_id"]] = row
        _validate_sha40(row.get("head_sha"), f"Step 23 {workflow}.head_sha")
        _require(row["head_sha"] == receipt["exact_main_sha"],
                 f"Step 23 {workflow} run is not bound to exact soak main")
        _require(isinstance(row.get("classification_reason"), str) and row["classification_reason"], f"Step 23 {workflow} classification reason missing")
        if classification == "FAILURE":
            _require(conclusion not in {"success", "cancelled"},
                     f"Step 23 {workflow} failure classification contradicts raw conclusion")
            raise FinalAcceptanceError(f"Step 23 soak window contains failure: {workflow} run {row['run_id']}")
        if classification == "CANCELLED_COALESCED":
            _require(conclusion == "cancelled",
                     f"Step 23 {workflow} coalesced run raw conclusion is not cancelled")
            superseding = row.get("superseding_run_id")
            _require(type(superseding) is int and superseding > 0 and superseding != row["run_id"],
                     f"Step 23 {workflow} coalesced run lacks superseding run")
            coalesced_rows.append(row)
        if classification == "SUCCESS":
            _require(conclusion == "success",
                     f"Step 23 {workflow} success classification contradicts raw conclusion")
            _require(row.get("superseding_run_id") is None, f"Step 23 successful {workflow} run has superseding run")
            successes[workflow] += 1
            successful_run_ids[workflow].add(row["run_id"])
            _validate_sha256(row.get("artifact_hash"), f"Step 23 {workflow}.artifact_hash")

    for row in coalesced_rows:
        successor = runs_by_id.get(row["superseding_run_id"])
        _require(successor is not None,
                 f"Step 23 coalesced run {row['run_id']} points outside soak evidence")
        _require(successor["workflow"] == row["workflow"],
                 f"Step 23 coalesced run {row['run_id']} points to another workflow")
        _require(successor["classification"] == "SUCCESS",
                 f"Step 23 coalesced run {row['run_id']} successor is not successful")
        _require(successor["run_id"] > row["run_id"],
                 f"Step 23 coalesced run {row['run_id']} successor run id is not later")
        _require(
            _timestamp(successor.get("created_at"), f"Step 23 successor {successor['run_id']}.created_at")
            > _timestamp(row.get("created_at"), f"Step 23 coalesced {row['run_id']}.created_at"),
            f"Step 23 coalesced run {row['run_id']} successor is not later by timestamp",
        )

    minimum = cfg["min_successful_scheduled_cycles_per_workflow"]
    for workflow, count in successes.items():
        _require(count >= minimum, f"Step 23 {workflow} has only {count} successful scheduled cycles")

    samples = receipt.get("canonical_samples")
    _require(isinstance(samples, list) and len(samples) >= minimum, "Step 23 canonical samples insufficient")
    previous = -1
    sample_run_ids: set[int] = set()
    reducer_success_ids = successful_run_ids["portfolio-state-reducer"]
    for sample in samples:
        _require(type(sample.get("run_id")) is int and sample["run_id"] > 0, "Step 23 canonical sample run_id invalid")
        _require(sample["run_id"] in reducer_success_ids, "Step 23 canonical sample is not bound to a successful reducer cycle")
        _require(sample["run_id"] not in sample_run_ids, "Step 23 canonical sample duplicated a reducer cycle")
        sample_run_ids.add(sample["run_id"])
        _timestamp(sample.get("observed_at"), "Step 23 canonical observed_at")
        _require(type(sample.get("sequence")) is int and sample["sequence"] >= 0, "Step 23 canonical sequence invalid")
        _require(sample["sequence"] >= previous, "Step 23 canonical sequence regressed")
        previous = sample["sequence"]
        _validate_sha256(sample.get("state_hash"), "Step 23 canonical state_hash")
        _validate_sha40(sample.get("source_sha"), "Step 23 canonical source_sha")
        _require(sample["source_sha"] == receipt["exact_main_sha"],
                 "Step 23 canonical sample is not bound to exact soak main")

    _require(type(receipt.get("pending_events_start")) is int and receipt["pending_events_start"] >= 0,
             "Step 23 pending_events_start invalid")
    _require(receipt.get("pending_events_final") == 0, "Step 23 pending events did not drain")
    handler_counts = receipt.get("handler_execution_counts")
    _require(isinstance(handler_counts, dict), "Step 23 handler execution counts missing")
    handler_evidence = receipt.get("handler_execution_evidence")
    _require(isinstance(handler_evidence, list) and handler_evidence,
             "Step 23 handler execution evidence missing")
    required_handler_types = set(cfg["required_handler_types"])
    scheduler_success_ids = successful_run_ids["portfolio-autonomous-scheduler"]
    bound_handler_counts = {kind: 0 for kind in required_handler_types}
    seen_handler_executions: set[tuple[str, str]] = set()
    for row in handler_evidence:
        _require(isinstance(row, dict), "Step 23 handler execution evidence row invalid")
        kind = row.get("kind")
        _require(kind in required_handler_types, f"Step 23 unexpected handler type: {kind}")
        _require(row.get("status") == "COMPLETED", f"Step 23 {kind} handler evidence is not completed")
        run_id = row.get("run_id")
        _require(type(run_id) is int and run_id in scheduler_success_ids,
                 f"Step 23 {kind} handler is not bound to a successful scheduler cycle")
        execution_id = row.get("execution_id")
        _require(isinstance(execution_id, str) and execution_id,
                 f"Step 23 {kind} handler execution id missing")
        identity = (kind, execution_id)
        _require(identity not in seen_handler_executions,
                 f"Step 23 duplicate {kind} handler execution evidence")
        seen_handler_executions.add(identity)
        _validate_sha40(row.get("head_sha"), f"Step 23 {kind}.head_sha")
        _require(row["head_sha"] == receipt["exact_main_sha"],
                 f"Step 23 {kind} handler evidence is not bound to exact soak main")
        _validate_sha256(row.get("artifact_hash"), f"Step 23 {kind}.artifact_hash")
        bound_handler_counts[kind] += 1
    for kind in cfg["required_handler_types"]:
        _require(bound_handler_counts[kind] >= 1, f"Step 23 {kind} handler did not execute")
        _require(type(handler_counts.get(kind)) is int and handler_counts[kind] == bound_handler_counts[kind],
                 f"Step 23 {kind} handler count is not backed by execution evidence")

    hunter_count = receipt.get("hunter_substantive_work_count")
    hunter_evidence = receipt.get("hunter_substantive_work_evidence")
    _require(isinstance(hunter_evidence, list) and hunter_evidence,
             "Step 23 Hunter substantive-work evidence missing")
    hunter_success_ids = successful_run_ids["hunter-autonomous-cycle"]
    seen_hunter_work: set[str] = set()
    for row in hunter_evidence:
        _require(isinstance(row, dict), "Step 23 Hunter substantive-work row invalid")
        _require(row.get("substantive") is True and row.get("heartbeat_only") is False,
                 "Step 23 Hunter evidence is heartbeat-only/non-substantive")
        run_id = row.get("run_id")
        _require(type(run_id) is int and run_id in hunter_success_ids,
                 "Step 23 Hunter substantive work is not bound to a successful Hunter cycle")
        work_id = row.get("work_id")
        _require(isinstance(work_id, str) and work_id, "Step 23 Hunter work id missing")
        _require(work_id not in seen_hunter_work, "Step 23 duplicate Hunter substantive-work evidence")
        seen_hunter_work.add(work_id)
        _validate_sha40(row.get("head_sha"), "Step 23 Hunter.head_sha")
        _require(row["head_sha"] == receipt["exact_main_sha"],
                 "Step 23 Hunter evidence is not bound to exact soak main")
        _validate_sha256(row.get("artifact_hash"), "Step 23 Hunter.artifact_hash")
    _require(type(hunter_count) is int and hunter_count == len(hunter_evidence) and hunter_count >= 1,
             "Step 23 Hunter substantive work count is not backed by evidence")
    _validate_sha256(receipt.get("dashboard_hash"), "Step 23 dashboard_hash")


def validate_step24(receipt: dict[str, Any]) -> None:
    policy = _load_policy()
    security_contract = _load_security_contract()
    _common(receipt, step=24)
    _require(receipt.get("independent_review") is True, "Step 24 review is not independent")
    reviewer_group = receipt.get("reviewer_independence_group")
    implementation_group = receipt.get("implementation_independence_group")
    _require(isinstance(reviewer_group, str) and reviewer_group, "Step 24 reviewer independence group missing")
    _require(isinstance(implementation_group, str) and implementation_group, "Step 24 implementation independence group missing")
    _require(reviewer_group != implementation_group, "Step 24 reviewer is not independent from implementation")
    _require(receipt.get("security_review_id") == policy["step24_security_review_id"],
             "Step 24 security review contract identity drifted")
    _require(receipt.get("security_review_status") == "READY_FOR_INDEPENDENT_SIGNOFF",
             "Step 24 security review is not ready for independent signoff")
    _validate_sha256(receipt.get("security_review_hash"), "Step 24.security_review_hash")
    _validate_sha40(receipt.get("security_review_exact_main_sha"), "Step 24.security_review_exact_main_sha")
    _require(receipt.get("security_review_exact_main_sha") == receipt.get("exact_main_sha"),
             "Step 24 security review is not bound to exact main")

    security_report = receipt.get("security_review_report")
    _require(isinstance(security_report, dict), "Step 24 security review report missing")
    report_hash = security_report.get("review_hash")
    _validate_sha256(report_hash, "Step 24 security review report hash")
    report_body = {k: v for k, v in security_report.items() if k != "review_hash"}
    _require(report_hash == canonical_hash(report_body), "Step 24 security review report hash mismatch")
    _require(receipt["security_review_hash"] == report_hash,
             "Step 24 receipt security review hash does not match embedded report")
    _require(security_report.get("schema_version") == "1.0.0",
             "Step 24 embedded security review schema drifted")
    _require(security_report.get("review_id") == policy["step24_security_review_id"],
             "Step 24 embedded security review identity drifted")
    _require(security_report.get("status") == "READY_FOR_INDEPENDENT_SIGNOFF",
             "Step 24 embedded security review is not ready for independent signoff")
    _require(security_report.get("step24_complete") is False,
             "Step 24 security harness may not self-certify completion")
    _require(security_report.get("live_evidence_present") is True,
             "Step 24 embedded security review lacks live evidence")
    _require(security_report.get("authority_granted") is False
             and security_report.get("evidence_upgraded") is False,
             "Step 24 security review widened authority/evidence")
    counts = security_report.get("finding_counts")
    _require(isinstance(counts, dict)
             and counts.get("CRITICAL") == 0
             and counts.get("HIGH") == 0
             and counts.get("UNKNOWN") == 0,
             "Step 24 embedded security review has blocking findings")
    report_live = security_report.get("observed", {}).get("live", {})
    _require(isinstance(report_live, dict)
             and report_live.get("exact_main_identity") is True
             and report_live.get("expected_main_sha") == receipt["exact_main_sha"]
             and report_live.get("observed_main_sha") == receipt["exact_main_sha"],
             "Step 24 embedded security review is not bound to exact main")
    required_domains = security_contract["required_domains"]
    covered_domains = security_report.get("covered_domains")
    _require(isinstance(covered_domains, list)
             and len(covered_domains) == len(set(covered_domains))
             and set(covered_domains) == set(required_domains),
             "Step 24 embedded security review does not cover every required domain")
    report_coverage = security_report.get("observed", {}).get("required_domain_coverage")
    _require(isinstance(report_coverage, dict)
             and report_coverage.get("required") == required_domains
             and set(report_coverage.get("covered", [])) == set(required_domains)
             and report_coverage.get("missing") == [],
             "Step 24 required-domain coverage receipt is incomplete")
    controls = receipt.get("controls")
    _require(isinstance(controls, list), "Step 24 controls missing")
    observed = [row.get("control_id") if isinstance(row, dict) else None for row in controls]
    _require(observed == policy["step24_controls"], "Step 24 control coverage/order changed")
    for row in controls:
        _require(row.get("status") == "PASS", f"Step 24 control not PASS: {row.get('control_id')}")
        _timestamp(row.get("observed_at"), f"Step 24 {row.get('control_id')}.observed_at")
        refs = row.get("evidence_refs")
        _require(isinstance(refs, list) and refs and all(isinstance(x, str) and x for x in refs),
                 f"Step 24 control evidence missing: {row.get('control_id')}")
    findings = receipt.get("findings")
    _require(isinstance(findings, list), "Step 24 findings missing")
    for finding in findings:
        _require(finding.get("severity") in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"},
                 "Step 24 finding severity invalid")
        _require(finding.get("status") in {"OPEN", "RESOLVED", "RISK_ACCEPTED"},
                 "Step 24 finding status invalid")
        if finding["severity"] in {"CRITICAL", "HIGH"}:
            _require(finding["status"] == "RESOLVED",
                     f"Step 24 has unresolved {finding['severity'].lower()} finding")


def validate_step25(receipt: dict[str, Any]) -> None:
    policy = _load_policy()
    _common(receipt, step=25)
    prerequisites = receipt.get("prerequisites")
    _require(prerequisites == {"21": "COMPLETE", "22": "COMPLETE", "23": "COMPLETE", "24": "COMPLETE"},
             "Step 25 started before acceptance/security completion")
    _require(receipt.get("canonical_history_preserved") is True, "Step 25 did not preserve canonical history")
    _require(receipt.get("historical_evidence_preserved") is True, "Step 25 did not preserve historical evidence")
    _validate_sha256(receipt.get("canonical_checkpoint_hash"), "Step 25.canonical_checkpoint_hash")
    _validate_sha256(receipt.get("archive_manifest_hash"), "Step 25.archive_manifest_hash")
    active_archive_path = receipt.get("active_archive_path")
    _require(isinstance(active_archive_path, str)
             and active_archive_path.startswith("state_journal/archive/")
             and active_archive_path.endswith(".json.gz"),
             "Step 25 active archive path invalid")
    _validate_sha256(receipt.get("active_archive_hash"), "Step 25.active_archive_hash")
    protected_evidence = policy.get("step25_protected_evidence_paths")
    _require(isinstance(protected_evidence, list) and protected_evidence
             and all(isinstance(x, str) and x for x in protected_evidence)
             and len(protected_evidence) == len(set(protected_evidence)),
             "Step 25 protected evidence policy invalid")
    preserved_evidence_hashes = receipt.get("preserved_evidence_hashes")
    _require(isinstance(preserved_evidence_hashes, dict)
             and set(preserved_evidence_hashes) == set(protected_evidence),
             "Step 25 preserved evidence hashes incomplete")
    for evidence_path, evidence_hash in preserved_evidence_hashes.items():
        _validate_sha256(evidence_hash, f"Step 25 preserved evidence {evidence_path}")
    _require(receipt.get("regression_suite_passed") is True, "Step 25 regression coverage failed")
    cleanup_pr = receipt.get("cleanup_pr_number")
    _require(type(cleanup_pr) is int and cleanup_pr > 0, "Step 25 cleanup PR invalid")
    _validate_sha40(receipt.get("cleanup_head_sha"), "Step 25.cleanup_head_sha")
    _validate_sha40(receipt.get("cleanup_merge_sha"), "Step 25.cleanup_merge_sha")
    _require(receipt.get("protected_merge") is True, "Step 25 cleanup merge was not protected")
    _require(receipt["cleanup_merge_sha"] == receipt["exact_main_sha"],
             "Step 25 cleanup merge SHA is not exact main")
    foundation_check_id = _validate_trusted_check(
        receipt.get("foundation_check"),
        field="Step 25 Foundation",
        expected_name=policy["foundation_check_name"],
        expected_app_id=policy["foundation_app_id"],
        expected_head_sha=receipt["cleanup_head_sha"],
    )
    verifier_check_id = _validate_trusted_check(
        receipt.get("hosted_verifier_check"),
        field="Step 25 hosted verifier",
        expected_name=policy["hosted_verifier_check_name"],
        expected_app_id=policy["hosted_verifier_app_id"],
        expected_head_sha=receipt["cleanup_head_sha"],
    )
    coverage_check_ids = _positive_int_list(receipt.get("coverage_check_run_ids"),
                                            "Step 25.coverage_check_run_ids")
    _require(set(coverage_check_ids) == {foundation_check_id, verifier_check_id},
             "Step 25 regression coverage checks do not match trusted exact-head checks")
    prerequisite_hashes = receipt.get("prerequisite_receipt_hashes")
    _require(isinstance(prerequisite_hashes, dict) and set(prerequisite_hashes) == {"21", "22", "23", "24"},
             "Step 25 prerequisite receipt hashes missing")
    for key, value in prerequisite_hashes.items():
        _validate_sha256(value, f"Step 25 prerequisite {key} receipt hash")
    removed = receipt.get("removed_paths")
    closed = receipt.get("closed_superseded_prs")
    _require(isinstance(removed, list) and all(isinstance(x, str) and x for x in removed), "Step 25 removed_paths invalid")
    _positive_int_list(closed, "Step 25.closed_superseded_prs")
    _require(removed or closed, "Step 25 cleanup receipt contains no cleanup")
    for path in removed:
        normalized_path = path.rstrip("/")
        for protected in policy["step25_protected_history_paths"]:
            normalized_protected = protected.rstrip("/")
            _require(not (
                normalized_path == normalized_protected
                or normalized_path.startswith(normalized_protected + "/")
            ), f"Step 25 attempted to remove protected canonical history: {path}")
        for protected in protected_evidence:
            normalized_protected = protected.rstrip("/")
            _require(not (
                normalized_path == normalized_protected
                or normalized_path.startswith(normalized_protected + "/")
            ), f"Step 25 attempted to remove protected audit/evidence: {path}")
    refs = receipt.get("coverage_evidence_refs")
    _require(isinstance(refs, list) and refs and all(isinstance(x, str) and x for x in refs),
             "Step 25 safe-removal regression evidence missing")


VALIDATORS = {
    "step21": validate_step21,
    "step22": validate_step22,
    "step23": validate_step23,
    "step24": validate_step24,
    "step25": validate_step25,
}


def validate_bundle(bundle: dict[str, Any]) -> dict[str, str]:
    _require(isinstance(bundle, dict), "acceptance bundle must be an object")
    _require(bundle.get("schema_version") == "1.0.0", "acceptance bundle schema drifted")
    _require(bundle.get("bundle_id") == "portfolio-final-acceptance-evidence-v1", "acceptance bundle identity drifted")
    statuses: dict[str, str] = {}
    for key, validator in VALIDATORS.items():
        receipt = bundle.get(key)
        if receipt is None:
            statuses[key] = "MISSING"
            continue
        validator(receipt)
        statuses[key] = "COMPLETE"

    step25_receipt = bundle.get("step25")
    if step25_receipt is not None:
        prerequisite_hashes = step25_receipt["prerequisite_receipt_hashes"]
        for number in ("21", "22", "23", "24"):
            prior = bundle.get("step" + number)
            _require(prior is not None, f"Step 25 prerequisite Step {number} receipt missing from bundle")
            _require(prerequisite_hashes[number] == prior.get("receipt_hash"),
                     f"Step 25 prerequisite Step {number} receipt hash mismatch")
    return statuses
