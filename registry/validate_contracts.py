#!/usr/bin/env python3
"""Deterministic validators for Step 2 autonomy, objective, and metric records."""
from __future__ import annotations
import re
from typing import Any

ID = {
    "project": re.compile(r"^PRJ-[0-9]{3,}$"),
    "autonomy": re.compile(r"^AUT-[0-9]{3,}$"),
    "objective": re.compile(r"^OBJ-[0-9]{3,}$"),
    "metric": re.compile(r"^MET-[0-9]{3,}$"),
}
SHA = re.compile(r"^[0-9a-f]{40}$")
AUTONOMY_DECISIONS = {"ALLOWED","BOUNDED","ISOLATED_BRANCH_ONLY","HUMAN_APPROVAL_REQUIRED","PROHIBITED"}
AUTONOMY_CLASSES = {"OBSERVE","EXPERIMENT","MODIFY","ACT"}
HUMAN_GATES = {
    "PRODUCTION_DEPLOYMENT_MEANINGFUL_RISK","CUSTOMER_COMMUNICATION",
    "CLAIM_OR_DISPUTE_SUBMISSION","LEGAL_OR_REGULATORY_COMMUNICATION",
    "PAYMENT_OR_PURCHASE","BILLING_CHANGE","MOVE_MONEY",
    "DESTRUCTIVE_DATA_DELETION","PRIVATE_INFORMATION_DISCLOSURE",
    "CONSEQUENTIAL_CHILD_FACING_CHANGE","LIVE_MARKET_TRADING",
    "BROKERAGE_ORDER","AUTONOMOUS_INVESTMENT_POSITION",
}
OBJECTIVE_STATUS = {"PROPOSED","ACTIVE","PAUSED","ACHIEVED","RETIRED"}
PRIORITY = {"LOW","MEDIUM","HIGH","CRITICAL"}
METRIC_KIND = {"OUTCOME","QUALITY","COST","LATENCY","RELIABILITY","SAFETY","LEARNING"}
METRIC_DIRECTION = {"HIGHER_IS_BETTER","LOWER_IS_BETTER","TARGET_RANGE","DESCRIPTIVE_ONLY"}
METRIC_SOURCE = {"EVENT","EVIDENCE_RECEIPT","DETERMINISTIC_AGGREGATE","EXTERNAL_VERIFIED_OUTCOME"}
AGGREGATION = {"NONE","SUM","COUNT","MEAN","MEDIAN","RATE","LATEST","CUSTOM_DETERMINISTIC"}

class ContractValidationError(ValueError):
    pass

def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ContractValidationError(message)

def _unique_strings(value: Any, field: str, *, min_items: int = 0) -> None:
    _require(isinstance(value, list), f"{field} must be a list")
    _require(len(value) >= min_items, f"{field} requires at least {min_items} item(s)")
    _require(all(isinstance(x, str) and x.strip() for x in value), f"{field} entries must be non-empty strings")
    _require(len(value) == len(set(value)), f"{field} entries must be unique")

def validate_autonomy_profile(record: dict[str, Any]) -> None:
    required={"schema_version","autonomy_profile_id","project_id","default_policy","runtime_enabled","permissions","human_approval_required_for","hard_prohibitions","separation_of_duties"}
    _require(isinstance(record, dict), "autonomy profile must be an object")
    _require(set(record)==required, "autonomy profile fields must exactly match contract")
    _require(record["schema_version"]=="1.0.0", "invalid autonomy schema_version")
    _require(ID["autonomy"].fullmatch(record["autonomy_profile_id"]) is not None, "invalid autonomy_profile_id")
    _require(ID["project"].fullmatch(record["project_id"]) is not None, "invalid project_id")
    _require(record["default_policy"]=="DENY", "default_policy must be DENY")
    _require(record["runtime_enabled"] is False, "Step 2 runtime_enabled must remain false")
    perms=record["permissions"]
    _require(isinstance(perms,dict) and set(perms)==AUTONOMY_CLASSES, "permissions must define exactly four autonomy classes")
    for cls,p in perms.items():
        _require(isinstance(p,dict) and set(p)=={"decision","conditions"}, f"invalid {cls} permission object")
        _require(p["decision"] in AUTONOMY_DECISIONS, f"invalid {cls} decision")
        _unique_strings(p["conditions"], f"{cls}.conditions")
    gates=record["human_approval_required_for"]
    _unique_strings(gates, "human_approval_required_for")
    _require(set(gates)<=HUMAN_GATES, "unknown human approval gate")
    _unique_strings(record["hard_prohibitions"], "hard_prohibitions")
    sod=record["separation_of_duties"]
    _require(sod=={"builder_may_self_approve":False,"independent_verifier_required_for_promotion":True}, "separation of duties must remain fail-closed")
    _require(perms["ACT"]["decision"] in {"HUMAN_APPROVAL_REQUIRED","PROHIBITED"}, "ACT cannot be autonomously enabled in Step 2")

def validate_objective(record: dict[str, Any]) -> None:
    required={"schema_version","objective_id","project_id","title","statement","status","priority","success_conditions","constraints","evidence_requirements","provenance"}
    _require(isinstance(record,dict) and set(record)==required, "objective fields must exactly match contract")
    _require(record["schema_version"]=="1.0.0", "invalid objective schema_version")
    _require(ID["objective"].fullmatch(record["objective_id"]) is not None, "invalid objective_id")
    _require(ID["project"].fullmatch(record["project_id"]) is not None, "invalid project_id")
    _require(isinstance(record["title"],str) and 1<=len(record["title"])<=160, "invalid title")
    _require(isinstance(record["statement"],str) and 1<=len(record["statement"])<=1000, "invalid statement")
    _require(record["status"] in OBJECTIVE_STATUS, "invalid objective status")
    _require(record["priority"] in PRIORITY, "invalid objective priority")
    _unique_strings(record["success_conditions"], "success_conditions", min_items=1)
    _unique_strings(record["constraints"], "constraints")
    _unique_strings(record["evidence_requirements"], "evidence_requirements", min_items=1)
    p=record["provenance"]
    _require(isinstance(p,dict) and {"source_type","source_ref"}<=set(p)<= {"source_type","source_ref","source_revision"}, "invalid provenance fields")
    _require(p["source_type"] in {"OWNER_DECLARATION","REPOSITORY_EVIDENCE","MIGRATED_REGISTRY"}, "invalid provenance source_type")
    _require(isinstance(p["source_ref"],str) and p["source_ref"], "missing provenance source_ref")
    rev=p.get("source_revision")
    _require(rev is None or SHA.fullmatch(rev) is not None, "invalid provenance source_revision")

def validate_metric(record: dict[str, Any]) -> None:
    required={"schema_version","metric_id","project_id","name","description","kind","unit","direction","source","verification_requirement","aggregation","status"}
    _require(isinstance(record,dict) and set(record)==required, "metric fields must exactly match contract")
    _require(record["schema_version"]=="1.0.0", "invalid metric schema_version")
    _require(ID["metric"].fullmatch(record["metric_id"]) is not None, "invalid metric_id")
    _require(ID["project"].fullmatch(record["project_id"]) is not None, "invalid project_id")
    _require(isinstance(record["name"],str) and 1<=len(record["name"])<=160, "invalid metric name")
    _require(isinstance(record["description"],str) and record["description"], "invalid metric description")
    _require(record["kind"] in METRIC_KIND, "invalid metric kind")
    _require(isinstance(record["unit"],str) and record["unit"], "invalid metric unit")
    _require(record["direction"] in METRIC_DIRECTION, "invalid metric direction")
    source=record["source"]
    _require(isinstance(source,dict) and set(source)=={"source_type","source_ref"}, "invalid metric source")
    _require(source["source_type"] in METRIC_SOURCE, "invalid metric source_type")
    _require(isinstance(source["source_ref"],str) and source["source_ref"], "missing metric source_ref")
    _require(record["verification_requirement"] in {"OBSERVED","VERIFIED"}, "invalid verification_requirement")
    _require(record["aggregation"] in AGGREGATION, "invalid aggregation")
    _require(record["status"] in {"PROPOSED","ACTIVE","PAUSED","RETIRED"}, "invalid metric status")
