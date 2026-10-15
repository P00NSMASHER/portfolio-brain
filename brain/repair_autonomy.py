"""Fail-closed repair execution handoffs for existing scheduled project owners.

This compiles observed exact-PR work into concrete, de-duplicated owner actions.
It never reads issue text as commands, runs code from providers, sends messages,
writes downstream repositories, overrides approvals or declares a draft live.
Existing project-owner tasks may execute the scoped technical steps through
their own source-specific GitHub permissions and independent QA.
"""
from __future__ import annotations

import re

from brain.core import digest, require

FOCUS = {
    "retally": ("P00NSMASHER/github-value-hunt-ledger",
                "Freight Recovery Product Director",
                "independent Freight/commerce/privacy release gate"),
    "product-factory": ("P00NSMASHER/x402-product-factory",
                        "Autonomous App Factory",
                        "independent browser/manufacturing/security CI"),
}
SHA = re.compile(r"[0-9a-f]{40}")
ALLOWED_THEMES = {
    "retally": frozenset({
        "FIRST_CUSTOMER_CONTROLS", "RECOVERY_ACCURACY",
        "SECURITY_CONTINUITY", "MARKETING_EVIDENCE", "UNCATEGORIZED_RETALLY",
    }),
    "product-factory": frozenset({
        "IDEA_TO_DEPLOYMENT", "BUYER_VALIDATION", "DEPLOYMENT_READINESS",
        "IDEA_QUALITY", "AUTOMATION_RELIABILITY",
        "APPLICATION_DEPTH", "UNCATEGORIZED_FACTORY",
    }),
}
ADVERSE = {"ADVERSE_CHECKS_OBSERVED"}
INCOMPLETE = {
    "INCOMPLETE_CHECKS_OBSERVED", "SKIPPED_CHECKS_NOT_ACCEPTANCE",
    "NO_CHECK_RUNS_OBSERVED", "NOT_CHECKED_IN_PRIORITY_SAMPLE",
    "CHECK_PAGE_UNVERIFIED", "REQUEST_BUDGET_UNAVAILABLE", "NOT_VERIFIED",
}
GREEN = "CHECKS_GREEN_NOT_RELEASE_OR_BUSINESS_ACCEPTANCE"
LIMIT = 5


def _candidate(work, project):
    require(type(work) is dict, "REPAIR_WORK_RECORD_NOT_OBJECT")
    name = project["project_id"]
    repo, _, _ = FOCUS[name]
    number = work.get("source_pr_number")
    source_sha = work.get("source_head_sha")
    theme = work.get("theme")
    require(type(number) is int and 0 < number < 1_000_000_000
            and type(source_sha) is str and SHA.fullmatch(source_sha)
            and work.get("source_repository") == repo
            and work.get("source_pr_url") ==
                f"https://github.com/{repo}/pull/{number}"
            and theme in ALLOWED_THEMES[name],
            "REPAIR_CANDIDATE_SOURCE_PROVENANCE_INVALID")
    require(work.get("relevance_not_verified_value") is True
            and work.get("buyer_value_verified") is False
            and work.get("production_release_approved") is False
            and work.get("downstream_mutation_authority") is False
            and work.get("external_message_or_payment_authority") is False,
            "REPAIR_CANDIDATE_MUST_HAVE_NO_GRANT_OF_AUTHORITY")
    require(type(work.get("heuristic_relevance")) is int
            and 0 <= work["heuristic_relevance"] <= 100
            and type(work.get("candidate_draft")) is bool
            and type(work.get("source_ci_status")) is str,
            "REPAIR_CANDIDATE_CLASSIFICATION_INVALID")
    for attr in ("before_value", "after_value", "measured_improvement"):
        require(work.get(attr) is None,
                "REPAIR_CANDIDATE_MUST_NOT_PRECERTIFY_VALUE")
    require(type(work.get("verification_steps")) is list
            and 1 <= len(work["verification_steps"]) <= 8
            and all(type(step) is str and 5 <= len(step) <= 500
                    for step in work["verification_steps"]),
            "REPAIR_VERIFICATION_PLAN_INVALID")
    require(type(work.get("required_release_gate")) is str
            and 10 <= len(work["required_release_gate"]) <= 1000,
            "REPAIR_RELEASE_HOLD_MISSING")
    ci = work["source_ci_status"]
    require(ci in ADVERSE | INCOMPLETE | {GREEN},
            "REPAIR_UNKNOWN_CI_CLASSIFICATION")
    dedupe = digest({
        "project": name, "repository": repo, "pr": number, "theme": theme,
    })
    evidence = digest({
        "dedupe": dedupe, "head_sha": source_sha, "ci": ci,
    })
    return dict(work, dedupe=dedupe, evidence=evidence)


def _action(case):
    """A deterministic technical next step; not an autonomous merge permit."""
    ci = case["source_ci_status"]
    if ci in ADVERSE:
        return (
            "REPAIR_EXACT_SOURCE_CI", 100,
            "Inspect the original exact-head failing check/job and reproduce "
            "the failing assertion; patch the actual source, add a negative "
            "regression, and run all exact-head checks.",
        )
    if ci in INCOMPLETE:
        return (
            "ESTABLISH_EXACT_SOURCE_CI", 82,
            "Find all required checks for this exact PR commit. Reproduce "
            "missing/skip/incomplete coverage; run or restore the existing "
            "source-specific gate without suppressing errors.",
        )
    if case.get("base_branch") != "main":
        return (
            "RECONCILE_STACK_AND_INDEPENDENT_TEST", 69,
            "Independently verify stacked parent ancestry and tests; "
            "reconcile against the real current parent, then rerun the "
            "changed exact-head CI and all mandatory negative controls.",
        )
    return (
        "VERIFY_INDEPENDENT_SOURCE_AND_DELIVERY", 58,
        "Verify the real test artifact and separate independent release "
        "gate, then use the existing approved SHA-guarded delivery path "
        "only when all actual security and owner-specific gates permit.",
    )


def repair_batch(project_report, *, previous_evidence=None, max_batch=LIMIT,
                 cycle_index=0, outcome_episodes=None):
    """Compile up to five independent owner actions with stable dedupe IDs.

    previous_evidence holds exact PR/head/CI fingerprints already acted on
    by a distinct task. Suppressing repeats does NOT close an unfinished fix:
    progress is re-enabled when exact source/CI changes or the task explicitly
    provides a new unobserved fingerprint.
    """
    require(type(max_batch) is int and 1 <= max_batch <= LIMIT,
            "REPAIR_BATCH_BOUND_INVALID")
    require(type(cycle_index) is int and 0 <= cycle_index < 2**63,
            "REPAIR_CYCLE_ROTATION_INVALID")
    require(type(project_report) is dict
            and project_report.get("scope") ==
                "READ_ONLY_CROSS_PROJECT_IMPROVEMENT_QUEUE"
            and project_report.get("verified_revenue") is None
            and project_report.get("autonomous_downstream_writes") is False,
            "REPAIR_REPORT_TRUST_BOUNDARY_INVALID")
    projects = project_report.get("evidence_to_action_packets")
    require(type(projects) is list and len(projects) == len(FOCUS)
            and {p.get("project_id") for p in projects} == set(FOCUS),
            "REPAIR_FOCUS_IDENTITY_INVALID")
    if previous_evidence is None:
        previous_evidence = []
    require(type(previous_evidence) is list and len(previous_evidence) <= 250
            and all(type(x) is str and re.fullmatch(r"[0-9a-f]{64}", x)
                    for x in previous_evidence),
            "REPAIR_PRIOR_EVIDENCE_INVALID")
    seen_before = set(previous_evidence)
    learned = None
    if outcome_episodes is not None:
        from brain.repair_outcome_learning import learn_from_repairs
        learned = learn_from_repairs(outcome_episodes)
    actions, suppressed, missing, identities = [], [], [], set()
    for project in projects:
        name = project["project_id"]
        repo, owner, verifier = FOCUS[name]
        require(project.get("repository") == repo
                and project.get("verified_revenue") is None
                and project.get("measurement_claim") == "NONE_ESTABLISHED",
                "REPAIR_OWNER_OR_ECONOMIC_PROOF_INVALID")
        candidates = project.get("actionable_review_packets")
        require(type(candidates) is list and 0 <= len(candidates) <= 3,
                "REPAIR_OWNER_WORKLIST_INVALID")
        if not candidates:
            missing.append({
                "project_id": name,
                "status": "SOURCE_PINNED_REMEDIATION_CANDIDATE_MISSING",
            })
        for work in candidates:
            case = _candidate(work, project)
            require(case["dedupe"] not in identities,
                    "REPAIR_DUPLICATE_PR_THEME")
            identities.add(case["dedupe"])
            if case["evidence"] in seen_before:
                suppressed.append(case["dedupe"])
                continue
            stage, urgency, instruction = _action(case)
            delta = 0
            if learned is not None:
                scoped = learned["projects"][repo]
                if (scoped["priority_adjustment_enabled"]
                        and case["theme"] == scoped["relevant_theme"]
                        and stage != "REPAIR_EXACT_SOURCE_CI"):
                    delta = scoped["priority_adjustment"]
            urgency = min(100, max(0, urgency + delta))
            # This is only authority to recommend a code fix, NOT a grant of
            # GitHub mutation credentials, protected merge or customer actions.
            actions.append({
                "dedupe_key": case["dedupe"],
                "exact_evidence_key": case["evidence"],
                "project_id": name,
                "repository": repo,
                "owner_task": owner,
                "independent_gate_owner": verifier,
                "candidate_pr_number": case["source_pr_number"],
                "candidate_pr_url": case["source_pr_url"],
                "source_head_sha": case["source_head_sha"],
                "source_ci_status": case["source_ci_status"],
                "opportunity_theme": case["theme"],
                "heuristic_relevance": case["heuristic_relevance"],
                "urgency": urgency,
                "learned_technical_priority_delta": delta,
                "stage": stage,
                "first_action": instruction,
                "negative_and_acceptance_tests":
                    list(case["verification_steps"]),
                "proof_artifact": case.get("required_proof_artifact"),
                "required_release_gate": case["required_release_gate"],
                "code_fix_without_new_user_prompt": True,
                "requires_separate_independent_gate": True,
                "merged_to_main_verified": False,
                "production_delivered": False,
                "human_time_or_revenue_verified": False,
                "safe_automatic_merge_authority": False,
                "financial_or_external_contact_authority": False,
            })
    actions.sort(key=lambda x: (
        -x["urgency"], -x["heuristic_relevance"],
        x["project_id"], x["candidate_pr_number"],
    ))
    # Preserve the highest-priority N-1 actions while rotating the final
    # bounded slot through the remaining candidates. Without this, the 6th
    # source is permanently starved by a fixed top-five batch each run.
    rotated_slot = None
    if len(actions) > max_batch:
        rotated_slot = max_batch - 1 + (
            cycle_index % (len(actions) - max_batch + 1)
        )
        selected = actions[:max_batch-1] + [actions[rotated_slot]]
    else:
        selected = actions
    return {
        "schema_version": 1,
        "status": "ACTIONABLE_TECHNICAL_REPAIRS" if selected
                  else "NO_NEW_SOURCE_BOUND_TECHNICAL_ACTION",
        "scope": "OWNER_TASK_FIX_AND_VERIFY_NO_RELEASE_AUTHORITY",
        "max_actions_per_run": max_batch,
        "rotation_cycle_index": cycle_index,
        "rotated_overflow_index": rotated_slot,
        "rotation_rule": "HIGHEST_PRIORITY_N_MINUS_ONE_PLUS_ONE_FAIR_OVERFLOW_SLOT",
        "actionable_count": len(actions),
        "selected_count": len(selected),
        "deferred_due_to_batch_bound": len(actions) - len(selected),
        "suppressed_duplicate_count": len(suppressed),
        "missing": missing,
        "actions": selected,
        "replayed_repair_learning": learned,
        "repeat_handling": "EXACT_SOURCE_CI_CHANGE_REOPENS_ONLY",
        "independent_quality_gate_required": True,
        "autonomous_fix_proposal_only": True,
        "authority_to_merge_or_deploy": False,
        "real_buyer_outcomes_verified": False,
        "verified_revenue": None,
    }
