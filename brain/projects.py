"""Cross-project improvement contracts.

This module turns verified Brain evidence into explicit project measurement work.
It never mutates a downstream repository, executes discovered code, invents a
baseline, or upgrades a technical candidate into a measured business outcome.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from brain.adapters import policy
from brain.core import require
from brain.intelligence import REPO

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "brain" / "PROJECTS.json"

# Operator review-only experiments. These are not approvals or completed results.
FOCUS = {
    "retally": {
        "priority": 1,
        "workstream": "FIRST_CUSTOMER_READINESS",
        "next_test": ("On labeled synthetic invoices, compare incorrect recovery "
                      "suggestions per 100 and reviewer minutes before/after "
                      "deduplication; separately test restricted-role staging access."),
        "required_evidence": ("Exact fixture/source digests, independent labeling, "
                              "before/after timings, and staging security checks."),
        "activation_gate": ("HOLD: actual customer authorization, restricted runtime "
                            "security and identity/contracts; defer registration "
                            "until an actual first customer. Never auto-activate "
                            "customer billing or recovery."),
    },
    "product-factory": {
        "priority": 2,
        "workstream": "VERIFIED_BUILDS_TO_BUYER_VALUE",
        "next_test": ("Pin each unmerged candidate SHA, re-run native mobile/desktop "
                      "operator/reviewer flows, restart persistence and package "
                      "integrity; validate buyer pilots independently."),
        "required_evidence": ("Exact-source native browser/restart/package receipts "
                              "plus separately consented buyer pilot completions."),
        "activation_gate": ("HOLD: passing app builds are not buyer demand; "
                            "no unsolicited outreach, live users, launch, charge "
                            "or procurement without reviewed authorization."),
    },
}


def _check_evidence(source):
    if source is None:
        return "SOURCE_UNOBSERVED"
    checks = source.get("checks")
    if type(checks) is not list or any(type(row) is not dict for row in checks):
        return "CHECK_EVIDENCE_UNVERIFIED"
    if not checks:
        return "NO_CHECK_RUNS_OBSERVED"
    if any(row.get("conclusion") in {
        "failure", "cancelled", "timed_out", "action_required", "startup_failure"
    } for row in checks):
        return "ADVERSE_CHECKS_OBSERVED"
    if any(row.get("status") != "completed" or row.get("conclusion") not in {
        "success", "neutral"
    } for row in checks):
        return "INCOMPLETE_OR_INCONCLUSIVE_CHECKS_OBSERVED"
    return "NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL"



def _text(value, label, maximum=300):
    require(type(value) is str and 0 < len(value.strip()) <= maximum, label + " invalid")
    return value.strip()


def load_project_registry():
    document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    require(
        set(document) == {"schema_version", "scope", "extended_observation_bound", "projects"}
        and document["schema_version"] == 1,
        "PROJECT_REGISTRY_SCHEMA",
    )
    require(
        document["scope"] == "ACTIVE_REPO_BACKED_PROJECTS_WITH_EXPLICIT_MEASUREMENT_CONTRACTS",
        "PROJECT_REGISTRY_SCOPE",
    )
    bound = document["extended_observation_bound"]
    require(type(bound) is int and 0 <= bound <= 5, "PROJECT_EXTENSION_BOUND")
    projects = document["projects"]
    require(type(projects) is list and 1 <= len(projects) <= 16, "PROJECT_REGISTRY_SIZE")
    ids = set()
    approved_targets = {row["project"] for row in policy()["research_targets"]}
    for row in projects:
        require(
            set(row) == {
                "id", "name", "repository", "research_target", "improvement_focus",
                "success_metric", "direction",
            },
            "PROJECT_REGISTRY_FIELDS",
        )
        project_id = _text(row["id"], "project id", 80)
        require(project_id not in ids, "PROJECT_REGISTRY_DUPLICATE_ID")
        ids.add(project_id)
        _text(row["name"], "project name", 120)
        require(REPO.fullmatch(row["repository"]) is not None, "PROJECT_REPOSITORY_INVALID")
        require(row["research_target"] in approved_targets, "PROJECT_RESEARCH_TARGET_UNAPPROVED")
        _text(row["improvement_focus"], "improvement focus")
        _text(row["success_metric"], "success metric")
        require(row["direction"] in {"UP", "DOWN"}, "PROJECT_METRIC_DIRECTION")
    core = tuple(policy()["repositories"])
    registered = tuple(dict.fromkeys(row["repository"] for row in projects))
    require(set(core) <= set(registered), "PROJECT_REGISTRY_MISSING_CORE_REPOSITORY")
    extended = tuple(repo for repo in registered if repo not in core)
    require(len(extended) <= bound, "PROJECT_EXTENSION_BOUND_EXCEEDED")
    return document


def extended_repositories():
    document = load_project_registry()
    core = set(policy()["repositories"])
    repositories = tuple(dict.fromkeys(
        row["repository"] for row in document["projects"] if row["repository"] not in core
    ))
    # Protect the actual App Factory source from starvation under the fixed
    # 24-GET observation budget; retain all other registration order.
    factory = "P00NSMASHER/x402-product-factory"
    return tuple(sorted(repositories, key=lambda r: (r != factory, repositories.index(r))))


def build_project_portfolio(canonical_report, extended_snapshots, *, source_sha, priority_prs=None):
    """Build one honest improvement queue from canonical + ephemeral source evidence."""
    require(
        type(canonical_report) is dict
        and canonical_report.get("source_sha") == source_sha
        and canonical_report.get("status") == "PASS"
        and canonical_report.get("pending_events") == 0,
        "PROJECT_CANONICAL_REPORT_NOT_CURRENT_PASS",
    )
    document = load_project_registry()
    require(priority_prs is None or
            (type(priority_prs) is dict and set(priority_prs) <= set(FOCUS)
             and all(type(x) is dict for x in priority_prs.values())),
            "PROJECT_FOCUSED_PR_INPUT_INVALID")
    priority_prs = priority_prs or {}
    for name, evidence in priority_prs.items():
        require(type(evidence.get("checks")) is dict
                and evidence.get("status") in {
                    "SOURCE_UNOBSERVED", "GET_ADAPTER_UNAVAILABLE",
                    "REQUEST_BUDGET_UNAVAILABLE", "PR_PAGE_UNVERIFIED",
                    "NO_MATCHING_PR_IN_BOUNDED_SAMPLE",
                    "PR_OBSERVED_CHECKS_UNVERIFIED", "PR_AND_CHECKS_OBSERVED",
                }, "PROJECT_FOCUSED_PR_STATUS_INVALID")
        if evidence.get("pr_number") is not None:
            expected_repo = next(row["repository"] for row in document["projects"]
                                 if row["id"] == name)
            number = evidence["pr_number"]
            sha = evidence.get("head_sha")
            require(type(number) is int and 0 < number < 100000000
                    and type(sha) is str
                    and re.fullmatch("[0-9a-f]{40}", sha)
                    and evidence.get("pr_url") ==
                    f"https://github.com/{expected_repo}/pull/{number}"
                    and evidence.get("production_merge_authority") is False
                    and evidence.get("buyer_value_verified") is False
                    and evidence.get("payment_or_external_contact_authority") is False,
                    "PROJECT_FOCUSED_PR_PROVENANCE_INVALID")
            if evidence["checks"].get("complete_single_page") is True:
                require(evidence["checks"].get("checked_head_sha") == sha
                        and evidence.get("status") == "PR_AND_CHECKS_OBSERVED",
                        "PROJECT_FOCUSED_CHECK_HEAD_INVALID")
        require(evidence.get("release_approved") is not True
                and evidence.get("measured_revenue") is None,
                "PROJECT_FOCUSED_FALSE_VALUE_CLAIM")
    repositories = {}
    for row in canonical_report.get("repositories", []):
        require(type(row) is dict and REPO.fullmatch(row.get("repository", "")), "PROJECT_CORE_SOURCE_INVALID")
        repositories[row["repository"]] = row
    require(type(extended_snapshots) is list, "PROJECT_EXTENDED_SOURCE_INVALID")
    allowed_extended = set(extended_repositories())
    for row in extended_snapshots:
        require(type(row) is dict and REPO.fullmatch(row.get("repository", "")), "PROJECT_EXTENDED_SOURCE_INVALID")
        require(row["repository"] in allowed_extended, "PROJECT_EXTENDED_SOURCE_OUT_OF_SCOPE")
        require(row["repository"] not in repositories, "PROJECT_SOURCE_DUPLICATED")
        repositories[row["repository"]] = row

    candidates = [
        row for row in canonical_report.get("reuse_candidates", [])
        if row.get("freshness") == "CURRENT"
    ]
    feedback = canonical_report.get("learning", {}).get("outcomes", [])
    feedback_by_key = {
        row["candidate_key"]: row for row in feedback
        if type(row) is dict and type(row.get("candidate_key")) is str
    }

    projects = []
    missing = []
    for item in document["projects"]:
        source = repositories.get(item["repository"])
        if source is None:
            missing.append(item["repository"])
        matched = [
            row for row in candidates
            if row.get("target") == item["research_target"]
        ]
        measured = [
            feedback_by_key[row["key"]] for row in matched
            if row.get("key") in feedback_by_key
        ]
        if source is None:
            status = "SOURCE_UNOBSERVED"
            next_action = "Restore exact-revision source observation before selecting project work."
        elif measured:
            status = "OPERATOR_FEEDBACK_RECORDED"
            next_action = "Operator feedback is not a measured result; capture project-specific before/after evidence."
        elif matched:
            status = "CANDIDATE_NEEDS_PROJECT_TEST"
            next_action = "Run a project-specific before/after correctness test before proposing adoption."
        else:
            status = "BASELINE_REQUIRED"
            next_action = "Measure the named success metric before changing the project."

        focus = FOCUS.get(item["id"])
        focused_review = (priority_prs.get(item["id"], {
            "status": "PR_EVIDENCE_NOT_COLLECTED",
            "checks": {"status": "NOT_VERIFIED", "complete_single_page": False},
        }) if source is not None else {
            "status": "SOURCE_UNOBSERVED",
            "checks": {"status": "NOT_VERIFIED", "complete_single_page": False},
        })
        if focus and source is not None:
            next_action = focus["next_test"]
        projects.append({
            "id": item["id"],
            "name": item["name"],
            "repository": item["repository"],
            "repository_revision": source.get("head_sha") if source else None,
            "repository_source_ref": source.get("source_ref") if source else None,
            "research_target": item["research_target"],
            "improvement_focus": item["improvement_focus"],
            "success_metric": item["success_metric"],
            "direction": item["direction"],
            "status": status,
            "source_check_state": _check_evidence(source),
            "focus_priority": focus["priority"] if focus else None,
            "active_pr_review": focused_review if focus else None,
            "focus_workstream": focus["workstream"] if focus else None,
            "focus_next_test": focus["next_test"] if focus else None,
            "focus_required_evidence": focus["required_evidence"] if focus else None,
            "activation_gate": focus["activation_gate"] if focus else None,
            "real_customer_activation_authority": False,
            "current_candidate_count": len(matched),
            "operator_outcome_count": len(measured),
            "baseline_value": None,
            "measured_result": None,
            "next_action": next_action,
            "downstream_write_authority": False,
            "production_merge_authority": False,
            "customer_or_external_message_authority": False,
        })

    result = {
        "schema_version": 1,
        "status": "PASS" if not missing else "BLOCKED",
        "scope": "READ_ONLY_CROSS_PROJECT_IMPROVEMENT_QUEUE",
        "source_sha": source_sha,
        "canonical_state_sequence": canonical_report.get("state_sequence"),
        "canonical_pending_events": canonical_report.get("pending_events"),
        "projects": projects,
        "priority_improvements": [
            {
                "project_id": row["id"],
                "priority": row["focus_priority"],
                "workstream": row["focus_workstream"],
                "repository": row["repository"],
                "observed_source_sha": row["repository_revision"],
                "source_check_state": row["source_check_state"],
                "active_pr_review": row["active_pr_review"],
                "queue_status": row["status"],
                "next_test": row["focus_next_test"],
                "required_evidence": row["focus_required_evidence"],
                "activation_gate": row["activation_gate"],
                "baseline_value": None,
                "measured_result": None,
                "real_customer_activation_authority": False,
            }
            for row in sorted(
                (x for x in projects if x["focus_priority"] is not None),
                key=lambda x: x["focus_priority"],
            )
        ],
        "repositories": [repositories[name] for name in sorted(repositories)],
        "repository_count": len(repositories),
        "logical_project_count": len(projects),
        "missing_repositories": sorted(set(missing)),
        "priority_review_coverage": (
            "SOURCE_PINNED_CHECK_PAGES_OBSERVED_NOT_RELEASE_PROOF"
            if all(priority_prs.get(k, {}).get("status") == "PR_AND_CHECKS_OBSERVED"
                   for k in FOCUS)
            else "INCOMPLETE_OR_UNVERIFIED"
        ),
        "measurement_rule": "NO_IMPROVEMENT_CLAIM_WITHOUT_EXPLICIT_BEFORE_AFTER_EVIDENCE",
        "verified_revenue": None,
        "autonomous_downstream_writes": False,
        "trading_authority": False,
    }
    from brain.value_actions import build_action_packets
    result["evidence_to_action_packets"] = build_action_packets(
        result["priority_improvements"]
    )
    result["technical_review_packet_count"] = sum(
        len(row["actionable_review_packets"])
        for row in result["evidence_to_action_packets"]
    )
    from brain.repair_autonomy import repair_batch
    result["autonomous_repair_queue"] = repair_batch(result)
    result["autonomous_repair_action_count"] = (
        result["autonomous_repair_queue"]["selected_count"]
    )
    result["measured_project_outcomes"] = 0
    result["real_buyer_confirmed_outcomes"] = None
    return result
