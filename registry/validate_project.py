#!/usr/bin/env python3
"""Deterministic validator for Portfolio Brain project records.

No third-party package is required. This enforces the operational subset of
schemas/PROJECT_SCHEMA.json used by Step 2.
"""
from __future__ import annotations
import re
from typing import Any

PROJECT_ID = re.compile(r"^PRJ-[0-9]{3,}$")
REPO_ID = re.compile(r"^REPO-[0-9]{3,}$")
AUT_ID = re.compile(r"^AUT-[0-9]{3,}$")
OBJ_ID = re.compile(r"^OBJ-[0-9]{3,}$")
MET_ID = re.compile(r"^MET-[0-9]{3,}$")
BLK_ID = re.compile(r"^BLK-[0-9]{3,}$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATEGORY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
SHA = re.compile(r"^[0-9a-f]{40}$")

PROJECT_TYPES = {"BUSINESS","PRODUCT","RESEARCH","INFRASTRUCTURE","PORTFOLIO"}
LIFECYCLE = {"PLANNED","IN_DEVELOPMENT","ACTIVE","ACTIVE_RESEARCH_ONLY","PAUSED","RETIRED"}
REGISTRATION = {"PROPOSED","REGISTERED","SUSPENDED","RETIRED"}
INTEGRATION = {"DECLARED","OBSERVE_ALLOWED","BLOCKED","RETIRED"}
DATA_BOUNDARIES = {
    "SANITIZED_CODE_POLICY_AND_RECEIPTS_ONLY",
    "PUBLIC_OR_SANITIZED_EVIDENCE_ONLY",
    "PRIVATE_DATA_BY_REFERENCE_ONLY",
}
SOURCE_TYPES = {"OWNER_DECLARATION","REPOSITORY_EVIDENCE","MIGRATED_REGISTRY"}

REQUIRED = {
    "schema_version","project_id","slug","canonical_name","project_type",
    "lifecycle_status","parent_project_id","aliases","categories",
    "repository_bindings","autonomy_profile_id","objective_ids","metric_ids",
    "evidence_policy","data_boundary","registration_state",
}
OPTIONAL = {"hard_boundaries","provenance"}

class ProjectValidationError(ValueError):
    pass

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectValidationError(message)

def _unique_strings(values: Any, field: str, pattern=None) -> None:
    _require(isinstance(values, list), f"{field} must be a list")
    _require(all(isinstance(x, str) and x for x in values), f"{field} entries must be non-empty strings")
    _require(len(values) == len(set(values)), f"{field} entries must be unique")
    if pattern:
        _require(all(pattern.fullmatch(x) for x in values), f"{field} contains invalid identifier")

def validate_project_record(record: dict[str, Any]) -> None:
    _require(isinstance(record, dict), "project record must be an object")
    missing = REQUIRED - set(record)
    extra = set(record) - REQUIRED - OPTIONAL
    _require(not missing, f"missing required fields: {sorted(missing)}")
    _require(not extra, f"unknown fields: {sorted(extra)}")

    _require(record["schema_version"] == "1.0.0", "schema_version must be 1.0.0")
    _require(PROJECT_ID.fullmatch(record["project_id"]) is not None, "invalid project_id")
    _require(isinstance(record["slug"], str) and SLUG.fullmatch(record["slug"]) is not None, "invalid slug")
    _require(isinstance(record["canonical_name"], str) and 1 <= len(record["canonical_name"]) <= 160, "invalid canonical_name")
    _require(record["project_type"] in PROJECT_TYPES, "invalid project_type")
    _require(record["lifecycle_status"] in LIFECYCLE, "invalid lifecycle_status")
    parent = record["parent_project_id"]
    _require(parent is None or PROJECT_ID.fullmatch(parent) is not None, "invalid parent_project_id")
    _require(parent != record["project_id"], "project cannot parent itself")

    _unique_strings(record["aliases"], "aliases")
    _unique_strings(record["categories"], "categories", CATEGORY)
    _require(len(record["categories"]) >= 1, "categories cannot be empty")

    bindings = record["repository_bindings"]
    _require(isinstance(bindings, list), "repository_bindings must be a list")
    repo_ids = []
    for binding in bindings:
        _require(isinstance(binding, dict), "repository binding must be an object")
        _require(set(binding) <= {"repository_id","full_name","integration_status","blocker_id"}, "unknown repository binding field")
        _require({"repository_id","full_name","integration_status"} <= set(binding), "repository binding missing field")
        rid = binding["repository_id"]
        _require(REPO_ID.fullmatch(rid) is not None, "invalid repository_id")
        repo_ids.append(rid)
        full_name = binding["full_name"]
        _require(isinstance(full_name, str) and full_name.count("/") == 1 and not full_name.startswith("/") and not full_name.endswith("/"), "invalid repository full_name")
        _require(binding["integration_status"] in INTEGRATION, "invalid integration_status")
        blocker = binding.get("blocker_id")
        _require(blocker is None or BLK_ID.fullmatch(blocker) is not None, "invalid blocker_id")
        if binding["integration_status"] == "BLOCKED":
            _require(blocker is not None, "blocked repository binding requires blocker_id")
    _require(len(repo_ids) == len(set(repo_ids)), "repository bindings must be unique by repository_id")

    _require(AUT_ID.fullmatch(record["autonomy_profile_id"]) is not None, "invalid autonomy_profile_id")
    _unique_strings(record["objective_ids"], "objective_ids", OBJ_ID)
    _unique_strings(record["metric_ids"], "metric_ids", MET_ID)
    _require(record["evidence_policy"] == "PROVENANCE_REQUIRED", "evidence_policy must require provenance")
    _require(record["data_boundary"] in DATA_BOUNDARIES, "invalid data_boundary")
    _require(record["registration_state"] in REGISTRATION, "invalid registration_state")

    if "hard_boundaries" in record:
        _unique_strings(record["hard_boundaries"], "hard_boundaries")
        _require(all(re.fullmatch(r"^[A-Z0-9_]+$", x) for x in record["hard_boundaries"]), "invalid hard_boundary")

    if "provenance" in record:
        p = record["provenance"]
        _require(isinstance(p, dict), "provenance must be an object")
        _require(set(p) <= {"source_type","source_ref","source_revision"}, "unknown provenance field")
        _require({"source_type","source_ref"} <= set(p), "provenance missing field")
        _require(p["source_type"] in SOURCE_TYPES, "invalid provenance source_type")
        _require(isinstance(p["source_ref"], str) and 1 <= len(p["source_ref"]) <= 500, "invalid provenance source_ref")
        rev = p.get("source_revision")
        _require(rev is None or SHA.fullmatch(rev) is not None, "invalid provenance source_revision")
