"""Cross-project improvement contracts.

This module turns verified Brain evidence into explicit project measurement work.
It never mutates a downstream repository, executes discovered code, invents a
baseline, or upgrades a technical candidate into a measured business outcome.
"""
from __future__ import annotations

import json
from pathlib import Path

from brain.adapters import policy
from brain.core import require
from brain.intelligence import REPO

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "brain" / "PROJECTS.json"


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
    require(type(bound) is int and 0 <= bound <= 4, "PROJECT_EXTENSION_BOUND")
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
    return tuple(dict.fromkeys(
        row["repository"] for row in document["projects"] if row["repository"] not in core
    ))


def build_project_portfolio(canonical_report, extended_snapshots, *, source_sha):
    """Build one honest improvement queue from canonical + ephemeral source evidence."""
    require(
        type(canonical_report) is dict
        and canonical_report.get("source_sha") == source_sha
        and canonical_report.get("status") == "PASS"
        and canonical_report.get("pending_events") == 0,
        "PROJECT_CANONICAL_REPORT_NOT_CURRENT_PASS",
    )
    document = load_project_registry()
    repositories = {}
    for row in canonical_report.get("repositories", []):
        require(type(row) is dict and REPO.fullmatch(row.get("repository", "")), "PROJECT_CORE_SOURCE_INVALID")
        repositories[row["repository"]] = row
    require(type(extended_snapshots) is list, "PROJECT_EXTENDED_SOURCE_INVALID")
    for row in extended_snapshots:
        require(type(row) is dict and REPO.fullmatch(row.get("repository", "")), "PROJECT_EXTENDED_SOURCE_INVALID")
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
            status = "MEASURED_OUTCOME_RECORDED"
            next_action = "Use the recorded operator outcome to choose the next bounded project experiment."
        elif matched:
            status = "CANDIDATE_NEEDS_PROJECT_TEST"
            next_action = "Run a project-specific before/after correctness test before proposing adoption."
        else:
            status = "BASELINE_REQUIRED"
            next_action = "Measure the named success metric before changing the project."

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
            "current_candidate_count": len(matched),
            "operator_outcome_count": len(measured),
            "baseline_value": None,
            "measured_result": None,
            "next_action": next_action,
            "downstream_write_authority": False,
            "production_merge_authority": False,
            "customer_or_external_message_authority": False,
        })

    return {
        "schema_version": 1,
        "status": "PASS" if not missing else "BLOCKED",
        "scope": "READ_ONLY_CROSS_PROJECT_IMPROVEMENT_QUEUE",
        "source_sha": source_sha,
        "canonical_state_sequence": canonical_report.get("state_sequence"),
        "canonical_pending_events": canonical_report.get("pending_events"),
        "projects": projects,
        "repositories": [repositories[name] for name in sorted(repositories)],
        "repository_count": len(repositories),
        "logical_project_count": len(projects),
        "missing_repositories": sorted(set(missing)),
        "measurement_rule": "NO_IMPROVEMENT_CLAIM_WITHOUT_EXPLICIT_BEFORE_AFTER_EVIDENCE",
        "verified_revenue": None,
        "autonomous_downstream_writes": False,
        "trading_authority": False,
    }
