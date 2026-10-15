"""Durable source-bound repair continuation across existing owner task runs.

Prior repair claims are caller-supplied authenticated work history, NOT grants
of source, deployment, contact, payment, or reviewer privileges. A missing
open-PR observation must never silently close an unfinished repair.
"""
from __future__ import annotations

import re

from brain.core import digest, require
from brain.repair_autonomy import FOCUS

STATES = frozenset({
    "OBSERVED", "CLAIMED", "REPRODUCED", "PATCHED", "CI_RED", "CI_GREEN",
    "INDEPENDENT_GREEN", "DELIVERY_REQUESTED", "BLOCKED_EXTERNAL",
    "MAIN_TECHNICALLY_VERIFIED",
})
REQUIRED_MAIN_CHECKS = {
    "P00NSMASHER/github-value-hunt-ledger": frozenset({"release-gate", "freight"}),
    "P00NSMASHER/x402-product-factory": frozenset({"test", "browser", "manufacturing"}),
}
FOUNDATION_APP_ID = 15368
HEX64 = re.compile("[0-9a-f]{64}")
SHA = re.compile("[0-9a-f]{40}")
BATCH = 5
HISTORY_LIMIT = 100


def _prior(row, cycle):
    expected = {
        "dedupe_key", "exact_evidence_key", "repository", "owner_task",
        "pr_number", "head_sha", "state", "last_progress_cycle",
        "source_revision_attempts",
    }
    require(type(row) is dict and set(row) == expected,
            "FOLLOWTHROUGH_HISTORY_FIELDS_INVALID")
    require(all(type(row[k]) is str and HEX64.fullmatch(row[k])
                for k in ("dedupe_key", "exact_evidence_key"))
            and type(row["head_sha"]) is str and SHA.fullmatch(row["head_sha"])
            and row["repository"] in {x[0] for x in FOCUS.values()}
            and type(row["owner_task"]) is str
            and row["state"] in STATES
            and type(row["pr_number"]) is int and row["pr_number"] > 0
            and type(row["last_progress_cycle"]) is int
            and 0 <= row["last_progress_cycle"] <= cycle
            and type(row["source_revision_attempts"]) is int
            and 0 <= row["source_revision_attempts"] <= 2,
            "FOLLOWTHROUGH_HISTORY_IDENTITY_INVALID")
    owner = next(x[1] for x in FOCUS.values() if x[0] == row["repository"])
    require(row["owner_task"] == owner, "FOLLOWTHROUGH_HISTORY_OWNER_CHANGED")
    return row


def _provider(proof):
    required = {
        "repository", "pr_number", "source_head_sha", "pr_state", "merged",
        "merge_commit_sha", "current_main_sha", "main_checks",
    }
    require(type(proof) is dict and set(proof) == required
            and proof["repository"] in {x[0] for x in FOCUS.values()}
            and type(proof["pr_number"]) is int and proof["pr_number"] > 0
            and type(proof["source_head_sha"]) is str
            and SHA.fullmatch(proof["source_head_sha"])
            and proof["pr_state"] in {"open", "closed"}
            and type(proof["merged"]) is bool
            and (proof["merge_commit_sha"] is None or
                 (type(proof["merge_commit_sha"]) is str
                  and SHA.fullmatch(proof["merge_commit_sha"])))
            and (proof["current_main_sha"] is None or
                 (type(proof["current_main_sha"]) is str
                  and SHA.fullmatch(proof["current_main_sha"])))
            and type(proof["main_checks"]) is list
            and len(proof["main_checks"]) <= 100,
            "FOLLOWTHROUGH_PROVIDER_SOURCE_INVALID")
    unique = set()
    for check in proof["main_checks"]:
        require(type(check) is dict and set(check) == {
            "id", "head_sha", "status", "conclusion", "name", "app_id",
        } and type(check["id"]) is int and check["id"] > 0
                and check["id"] not in unique
                and type(check["name"]) is str
                and 1 <= len(check["name"]) <= 128
                and type(check["app_id"]) is int
                and check["app_id"] > 0
                and type(check["head_sha"]) is str
                and SHA.fullmatch(check["head_sha"])
                and check["status"] in {"completed", "queued", "in_progress"}
                and check["conclusion"] in {
                    "success", "neutral", "skipped", "failure",
                    "timed_out", "cancelled", None,
                }, "FOLLOWTHROUGH_PROVIDER_CHECK_IDENTITY_INVALID")
        unique.add(check["id"])
    require(not proof["merged"] or
            (proof["pr_state"] == "closed" and proof["merge_commit_sha"] is not None),
            "FOLLOWTHROUGH_PROVIDER_MERGE_INCONSISTENT")
    return proof


def _next(prior, work, cycle):
    if prior is None:
        return "CLAIM_AND_REPRODUCE"
    if prior["exact_evidence_key"] != work["exact_evidence_key"]:
        return "RECHECK_CHANGED_SOURCE_AND_CI"
    if prior["state"] == "MAIN_TECHNICALLY_VERIFIED":
        return "DO_NOT_DUPLICATE_COMPLETED_TECHNICAL_FIX"
    if prior["state"] == "BLOCKED_EXTERNAL":
        return "PRESERVE_EXTERNAL_HOLD_FIX_NEXT"
    if prior["state"] == "CI_RED" and prior["source_revision_attempts"] == 2:
        return "ESCALATE_REPRODUCIBLE_FAILURE_WITH_LOGS"
    if prior["state"] == "CI_RED":
        return "PATCH_EXACT_FAILED_REGRESSION"
    if prior["state"] == "PATCHED":
        return "VERIFY_PATCH_AT_NEW_EXACT_HEAD"
    if prior["state"] == "CI_GREEN":
        return "GET_SEPARATE_INDEPENDENT_GATE"
    if prior["state"] == "INDEPENDENT_GREEN":
        return "RECHECK_REAL_RELEASE_HOLDS_AND_MAIN"
    if prior["state"] == "DELIVERY_REQUESTED":
        return "VERIFY_PROTECTED_MERGE_AND_ACTUAL_MAIN"
    if cycle - prior["last_progress_cycle"] >= 2:
        return "RESUME_STALLED_OWNER_CHECK_PR_AND_LOGS"
    return "CONTINUE_EXISTING_OWNER_PR_NOT_ANOTHER_PR"


def _verified_main(work, proof):
    if proof is None:
        return "NO_PROVIDER_MERGE_PROOF", False
    require(proof["repository"] == work["repository"]
            and proof["pr_number"] == work["candidate_pr_number"]
            and proof["source_head_sha"] == work["source_head_sha"],
            "FOLLOWTHROUGH_CROSS_SOURCE_PROVIDER_PROOF")
    if not proof["merged"]:
        return "SOURCE_NOT_MERGED", False
    if proof["current_main_sha"] != proof["merge_commit_sha"]:
        return "MERGED_ANCESTRY_TO_LATEST_MAIN_NOT_VERIFIED", False
    checks = proof["main_checks"]
    if not checks:
        return "MERGED_MAIN_CHECKS_MISSING", False
    if any(row["head_sha"] != proof["merge_commit_sha"] for row in checks):
        return "CROSS_COMMIT_MAIN_CHECK_REJECTED", False
    if any(row["status"] != "completed" or row["conclusion"] not in
           {"success", "neutral", "skipped"} for row in checks):
        return "MAIN_CHECKS_UNVERIFIED_OR_ADVERSE", False
    trusted = {
        row["name"] for row in checks
        if row["app_id"] == FOUNDATION_APP_ID
        and row["status"] == "completed"
        and row["conclusion"] == "success"
    }
    if not REQUIRED_MAIN_CHECKS[work["repository"]] <= trusted:
        return "REQUIRED_MAIN_CHECKS_OR_APP_ID_MISSING", False
    return "MAIN_SHA_AND_REQUIRED_TECHNICAL_CHECKS_MATCH_NOT_PRODUCTION", True


def follow_through(queue, *, cycle, history=None, provider_receipts=None,
                   max_batch=BATCH):
    require(type(queue) is dict
            and queue.get("scope") == "OWNER_TASK_FIX_AND_VERIFY_NO_RELEASE_AUTHORITY"
            and queue.get("authority_to_merge_or_deploy") is False
            and queue.get("verified_revenue") is None
            and type(queue.get("actions")) is list
            and len(queue["actions"]) <= BATCH
            and type(cycle) is int and 0 <= cycle < 2**63
            and type(max_batch) is int and 1 <= max_batch <= BATCH,
            "FOLLOWTHROUGH_NO_EXTRA_AUTHORITY")
    history = [] if history is None else history
    provider_receipts = [] if provider_receipts is None else provider_receipts
    require(type(history) is list and len(history) <= HISTORY_LIMIT
            and type(provider_receipts) is list and len(provider_receipts) <= 15,
            "FOLLOWTHROUGH_INPUT_COUNT_LIMIT")
    known = {}
    for prior in history:
        row = _prior(prior, cycle)
        require(row["dedupe_key"] not in known,
                "FOLLOWTHROUGH_DUPLICATE_OWNER_CLAIM")
        known[row["dedupe_key"]] = row
    proof = {}
    for item in provider_receipts:
        row = _provider(item)
        key = (row["repository"], row["pr_number"])
        require(key not in proof, "FOLLOWTHROUGH_DUPLICATE_PROVIDER")
        proof[key] = row

    results, active = [], set()
    for work in queue["actions"]:
        require(type(work) is dict
                and type(work.get("dedupe_key")) is str
                and HEX64.fullmatch(work["dedupe_key"])
                and type(work.get("exact_evidence_key")) is str
                and HEX64.fullmatch(work["exact_evidence_key"])
                and work.get("repository") in {x[0] for x in FOCUS.values()}
                and work.get("project_id") in FOCUS
                and work.get("repository") == FOCUS[work["project_id"]][0]
                and work.get("owner_task") == FOCUS[work["project_id"]][1]
                and work.get("independent_gate_owner") == FOCUS[work["project_id"]][2]
                and type(work.get("candidate_pr_number")) is int
                and work["candidate_pr_number"] > 0
                and work.get("candidate_pr_url") ==
                    f'https://github.com/{work["repository"]}/pull/{work["candidate_pr_number"]}'
                and type(work.get("opportunity_theme")) is str
                and type(work.get("source_ci_status")) is str
                and type(work.get("source_head_sha")) is str
                and SHA.fullmatch(work["source_head_sha"])
                and work.get("code_fix_without_new_user_prompt") is True
                and work.get("safe_automatic_merge_authority") is False,
                "FOLLOWTHROUGH_UNTRUSTED_OWNER_TASK")
        key = work["dedupe_key"]
        require(key == digest({
                    "project": work["project_id"],
                    "repository": work["repository"],
                    "pr": work["candidate_pr_number"],
                    "theme": work["opportunity_theme"],
                }) and work["exact_evidence_key"] == digest({
                    "dedupe": key, "head_sha": work["source_head_sha"],
                    "ci": work["source_ci_status"],
                }), "FOLLOWTHROUGH_FORGED_FINGERPRINT")
        require(key not in active, "FOLLOWTHROUGH_DUPLICATE_SOURCE")
        active.add(key)
        prior = known.get(key)
        if prior:
            require(prior["repository"] == work["repository"]
                    and prior["owner_task"] == work["owner_task"]
                    and prior["pr_number"] == work["candidate_pr_number"],
                    "FOLLOWTHROUGH_REASSIGNMENT_DENIED")
        op = _next(prior, work, cycle)
        state, verified = _verified_main(
            work, proof.get((work["repository"], work["candidate_pr_number"])))
        if verified:
            op = "MAIN_TECHNICAL_SOURCE_VERIFIED_REVIEW_RUNTIME_SEPARATELY"
        results.append(dict(
            dedupe_key=key, evidence_key=work["exact_evidence_key"],
            project_id=work["project_id"],
            repository=work["repository"], owner_task=work["owner_task"],
            independent_gate_owner=work["independent_gate_owner"],
            source_pr=work["candidate_pr_number"],
            source_head_sha=work["source_head_sha"],
            next_operation=op, provider_status=state,
            technical_main_source_verified=verified,
            live_deployment_verified=False,
            financial_or_external_action_authorized=False,
        ))
    for key, prior in known.items():
        if key in active or prior["state"] == "MAIN_TECHNICALLY_VERIFIED":
            continue
        project = next(k for k,v in FOCUS.items() if v[0] == prior["repository"])
        status, verified = _verified_main(
            dict(repository=prior["repository"], candidate_pr_number=prior["pr_number"],
                 source_head_sha=prior["head_sha"]),
            proof.get((prior["repository"], prior["pr_number"])),
        )
        results.append(dict(
            dedupe_key=key, evidence_key=prior["exact_evidence_key"],
            project_id=project, repository=prior["repository"],
            owner_task=prior["owner_task"],
            independent_gate_owner=FOCUS[project][2],
            source_pr=prior["pr_number"], source_head_sha=prior["head_sha"],
            next_operation=("MAIN_TECHNICAL_SOURCE_VERIFIED_REVIEW_RUNTIME_SEPARATELY"
                            if verified else
                            "PRESERVE_EXTERNAL_HOLD_FIX_NEXT"
                            if prior["state"] == "BLOCKED_EXTERNAL" else
                            "REOBSERVE_UNFINISHED_PR_ABSENT_FROM_OPEN_SAMPLE"),
            provider_status=status,
            technical_main_source_verified=verified,
            live_deployment_verified=False,
            financial_or_external_action_authorized=False,
        ))
    results.sort(key=lambda row: (
        row["next_operation"] != "REOBSERVE_UNFINISHED_PR_ABSENT_FROM_OPEN_SAMPLE",
        row["next_operation"] not in {
            "PATCH_EXACT_FAILED_REGRESSION",
            "VERIFY_PROTECTED_MERGE_AND_ACTUAL_MAIN",
            "RESUME_STALLED_OWNER_CHECK_PR_AND_LOGS",
        },
        row["project_id"], row["source_pr"]))
    # Persist previous task state without inventing an implementation attempt.
    # Only a verified current-main source-check transitions to technical PASS.
    records = []
    for task in results:
        prior = known.get(task["dedupe_key"])
        changed = (prior is not None and
                   prior["exact_evidence_key"] != task["evidence_key"])
        if prior is None or changed:
            state, progress_cycle, attempts = "OBSERVED", cycle, 0
        else:
            state = prior["state"]
            progress_cycle = prior["last_progress_cycle"]
            attempts = prior["source_revision_attempts"]
        if task["technical_main_source_verified"]:
            state, progress_cycle = "MAIN_TECHNICALLY_VERIFIED", cycle
        records.append({
            "dedupe_key": task["dedupe_key"],
            "exact_evidence_key": task["evidence_key"],
            "repository": task["repository"],
            "owner_task": task["owner_task"],
            "pr_number": task["source_pr"],
            "head_sha": task["source_head_sha"],
            "state": state,
            "last_progress_cycle": progress_cycle,
            "source_revision_attempts": attempts,
        })
    archived = [
        dict(item) for key, item in known.items()
        if key not in {task["dedupe_key"] for task in results}
        and item["state"] == "MAIN_TECHNICALLY_VERIFIED"
    ]
    records.extend(archived)
    require(len(records) <= HISTORY_LIMIT, "FOLLOWTHROUGH_HISTORY_OUTPUT_BOUND")
    outstanding = sum(not x["technical_main_source_verified"] for x in results)
    return {
        "schema_version": 1,
        "status": ("UNFINISHED_REPAIRS_TO_CONTINUE" if outstanding
                   else "TECHNICAL_MAIN_SOURCE_CHECKS_OBSERVED" if results
                   else "NO_UNFINISHED_ACTION_OBSERVED"),
        "scope": "BOUNDED_EXISTING_OWNER_FOLLOWTHROUGH_ONLY",
        "cycle": cycle,
        "selected_count": len(results[:max_batch]),
        "total_open_or_pending": len(results),
        "deferred_count": len(results) - min(len(results), max_batch),
        "technical_main_verified_count": sum(
            1 for item in results if item["technical_main_source_verified"]
        ),
        "unfinished_count": outstanding,
        "carried_forward_count": sum(
            1 for item in results if item["dedupe_key"] in known
            and item["dedupe_key"] not in active
        ),
        "actions": results[:max_batch],
        "next_history": records,
        "archived_verified_count": len(archived),
        "history_replay_contract": "EXACT_SOURCE_CI_PROGRESS_ONLY_NO_IMPLICIT_CLOSURE",
        "merge_or_deployment_authority": False,
        "task_schedule_changed": False,
        "independent_gate_required": True,
        "real_buyer_or_revenue_verified": False,
    }
