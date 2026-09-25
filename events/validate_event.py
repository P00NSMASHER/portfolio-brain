#!/usr/bin/env python3
"""Deterministic Step 3 evidence and event validation.

This module deliberately uses only the standard library. Hashes are computed over
canonical JSON with the receipt hash field omitted. Model output is evidence only
at its declared state; it cannot certify itself as VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_STATES = {
    "OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"
}
EVIDENCE_TYPES = {
    "SOURCE_ARTIFACT","SYSTEM_OBSERVATION","TEST_RECEIPT","HUMAN_ATTESTATION",
    "EXTERNAL_OUTCOME","MODEL_OUTPUT","DETERMINISTIC_DERIVATION"
}
SOURCE_KINDS = {
    "GITHUB","FILE","API","WEB","DATABASE","HUMAN","SYSTEM","MODEL","EXTERNAL_SERVICE"
}
ACTOR_TYPES = {"HUMAN","SYSTEM","MODEL","EXTERNAL"}
VERIFICATION_METHODS = {
    "NONE","DIRECT_SOURCE","DETERMINISTIC_TEST","INDEPENDENT_VERIFIER",
    "HUMAN_CONFIRMATION","MODEL_INFERENCE","DETERMINISTIC_DERIVATION"
}
AUTHORITY_CLASSES = {"NONE","OBSERVE","EXPERIMENT","MODIFY","ACT"}
DATA_CLASSIFICATIONS = {"PUBLIC","SANITIZED","PRIVATE_REFERENCE_ONLY"}

EVD_ID = re.compile(r"^EVD-[A-Z0-9-]{8,}$")
EVT_ID = re.compile(r"^EVT-[A-Z0-9-]{8,}$")
PRJ_ID = re.compile(r"^PRJ-[0-9]{3,}$")
MET_ID = re.compile(r"^MET-[0-9]{3,}$")
EVENT_TYPE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[A-Za-z0-9._:/@+-]{1,300}$")

class EventValidationError(ValueError):
    pass

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EventValidationError(message)

def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

def _hash_record(record: dict[str, Any], omitted_field: str) -> str:
    body = {k: v for k, v in record.items() if k != omitted_field}
    return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()

def compute_evidence_hash(record: dict[str, Any]) -> str:
    return _hash_record(record, "evidence_hash")

def compute_event_hash(record: dict[str, Any]) -> str:
    return _hash_record(record, "event_hash")

def compute_idempotency_key(record: dict[str, Any]) -> str:
    stable_identity = {
        "schema_version": record["schema_version"],
        "event_type": record["event_type"],
        "occurred_at": record["occurred_at"],
        "project_id": record["project_id"],
        "source": record["source"],
        "subject_refs": sorted(record["subject_refs"]),
    }
    return "sha256:" + hashlib.sha256(_canonical_bytes(stable_identity)).hexdigest()

def _parse_time(value: Any, field: str) -> datetime:
    _require(isinstance(value, str) and value, f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    _require(parsed.tzinfo is not None, f"{field} must include timezone")
    return parsed

def _unique_strings(values: Any, field: str, *, min_items: int = 0, pattern=None) -> None:
    _require(isinstance(values, list), f"{field} must be a list")
    _require(len(values) >= min_items, f"{field} requires at least {min_items} item(s)")
    _require(all(isinstance(x, str) and x for x in values), f"{field} entries must be non-empty strings")
    _require(len(values) == len(set(values)), f"{field} entries must be unique")
    if pattern is not None:
        _require(all(pattern.fullmatch(x) is not None for x in values), f"{field} contains an invalid identifier")

def validate_evidence(record: dict[str, Any]) -> None:
    required = {
        "schema_version","evidence_id","project_id","evidence_type","evidence_state",
        "subject_refs","source","actor","observed_at","verification","supports_refs",
        "contradicts_refs","evidence_hash"
    }
    _require(isinstance(record, dict) and set(record) == required, "evidence fields must exactly match contract")
    _require(record["schema_version"] == "1.0.0", "invalid evidence schema_version")
    _require(EVD_ID.fullmatch(record["evidence_id"]) is not None, "invalid evidence_id")
    _require(PRJ_ID.fullmatch(record["project_id"]) is not None, "invalid evidence project_id")
    _require(record["evidence_type"] in EVIDENCE_TYPES, "invalid evidence_type")
    state = record["evidence_state"]
    _require(state in EVIDENCE_STATES, "invalid evidence_state")
    _unique_strings(record["subject_refs"], "subject_refs", min_items=1)

    source = record["source"]
    _require(isinstance(source, dict) and set(source) == {
        "source_kind","source_ref","source_revision","retrieved_at","content_hash"
    }, "invalid source fields")
    _require(source["source_kind"] in SOURCE_KINDS, "invalid source_kind")
    _require(isinstance(source["source_ref"], str) and source["source_ref"], "source_ref required")
    revision = source["source_revision"]
    _require(revision is None or REVISION.fullmatch(revision) is not None, "invalid source_revision")
    _parse_time(source["retrieved_at"], "source.retrieved_at")
    _require(isinstance(source["content_hash"], str) and SHA256.fullmatch(source["content_hash"]) is not None, "source.content_hash is required and must be sha256")

    actor = record["actor"]
    _require(isinstance(actor, dict) and set(actor) == {"actor_type","actor_id"}, "invalid actor fields")
    _require(actor["actor_type"] in ACTOR_TYPES, "invalid actor_type")
    _require(isinstance(actor["actor_id"], str) and actor["actor_id"], "actor_id required")
    _parse_time(record["observed_at"], "observed_at")

    verification = record["verification"]
    _require(isinstance(verification, dict) and set(verification) == {
        "method","verifier_actor_id","verified_at","basis_evidence_ids","reason"
    }, "invalid verification fields")
    method = verification["method"]
    _require(method in VERIFICATION_METHODS, "invalid verification method")
    verifier = verification["verifier_actor_id"]
    _require(verifier is None or (isinstance(verifier, str) and verifier), "invalid verifier_actor_id")
    verified_at = verification["verified_at"]
    if verified_at is not None:
        _parse_time(verified_at, "verification.verified_at")
    _unique_strings(verification["basis_evidence_ids"], "verification.basis_evidence_ids", pattern=EVD_ID)
    _require(record["evidence_id"] not in verification["basis_evidence_ids"], "evidence cannot depend on itself")
    reason = verification["reason"]
    _require(reason is None or (isinstance(reason, str) and reason), "invalid verification reason")

    _unique_strings(record["supports_refs"], "supports_refs")
    _unique_strings(record["contradicts_refs"], "contradicts_refs")

    if state == "VERIFIED":
        _require(method in {
            "DIRECT_SOURCE","DETERMINISTIC_TEST","INDEPENDENT_VERIFIER","HUMAN_CONFIRMATION"
        }, "VERIFIED evidence requires non-model verification")
        _require(verifier is not None and verified_at is not None, "VERIFIED evidence requires verifier and verified_at")
        if record["evidence_type"] == "MODEL_OUTPUT":
            _require(verifier != actor["actor_id"], "model output cannot verify itself")
    elif state == "INFERRED":
        _require(method in {"MODEL_INFERENCE","DETERMINISTIC_DERIVATION"}, "INFERRED evidence requires inference/derivation method")
        _require(len(verification["basis_evidence_ids"]) >= 1, "INFERRED evidence requires basis evidence")
    elif state == "UNKNOWN":
        _require(method == "NONE", "UNKNOWN evidence must use NONE verification method")
        _require(reason is not None, "UNKNOWN evidence requires reason")
    elif state == "CONTRADICTED":
        _require(len(record["contradicts_refs"]) >= 1, "CONTRADICTED evidence requires contradicted refs")
        _require(reason is not None, "CONTRADICTED evidence requires reason")
    elif state in {"STALE","INVALID"}:
        _require(reason is not None, f"{state} evidence requires reason")

    _require(record["evidence_hash"] == compute_evidence_hash(record), "evidence_hash mismatch")

def validate_event(record: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]] | None = None) -> None:
    required = {
        "schema_version","event_id","event_type","occurred_at","recorded_at","project_id",
        "source","actor","authority_class","subject_refs","evidence_ids",
        "verification_status","dependency_event_ids","causal_event_ids","metrics",
        "data_classification","payload","idempotency_key","event_hash"
    }
    _require(isinstance(record, dict) and set(record) == required, "event fields must exactly match contract")
    _require(record["schema_version"] == "1.0.0", "invalid event schema_version")
    _require(EVT_ID.fullmatch(record["event_id"]) is not None, "invalid event_id")
    _require(EVENT_TYPE.fullmatch(record["event_type"]) is not None, "invalid event_type")
    occurred = _parse_time(record["occurred_at"], "occurred_at")
    recorded = _parse_time(record["recorded_at"], "recorded_at")
    _require(recorded >= occurred, "recorded_at cannot precede occurred_at")
    _require(PRJ_ID.fullmatch(record["project_id"]) is not None, "invalid event project_id")

    source = record["source"]
    _require(isinstance(source, dict) and set(source) == {"system","source_ref","source_revision"}, "invalid event source fields")
    _require(isinstance(source["system"], str) and source["system"], "event source.system required")
    _require(isinstance(source["source_ref"], str) and source["source_ref"], "event source_ref required")
    revision = source["source_revision"]
    _require(revision is None or REVISION.fullmatch(revision) is not None, "invalid event source_revision")

    actor = record["actor"]
    _require(isinstance(actor, dict) and set(actor) == {"actor_type","actor_id"}, "invalid event actor fields")
    _require(actor["actor_type"] in ACTOR_TYPES, "invalid event actor_type")
    _require(isinstance(actor["actor_id"], str) and actor["actor_id"], "event actor_id required")
    _require(record["authority_class"] in AUTHORITY_CLASSES, "invalid authority_class")
    _unique_strings(record["subject_refs"], "event.subject_refs", min_items=1)
    _unique_strings(record["evidence_ids"], "event.evidence_ids", min_items=1, pattern=EVD_ID)
    status = record["verification_status"]
    _require(status in EVIDENCE_STATES, "invalid verification_status")
    _unique_strings(record["dependency_event_ids"], "dependency_event_ids", pattern=EVT_ID)
    _unique_strings(record["causal_event_ids"], "causal_event_ids", pattern=EVT_ID)
    _require(record["event_id"] not in record["dependency_event_ids"], "event cannot depend on itself")
    _require(record["event_id"] not in record["causal_event_ids"], "event cannot cause itself")

    metrics = record["metrics"]
    _require(isinstance(metrics, list), "metrics must be a list")
    metric_ids = []
    for item in metrics:
        _require(isinstance(item, dict) and set(item) == {"metric_id","value","unit"}, "invalid metric observation")
        _require(MET_ID.fullmatch(item["metric_id"]) is not None, "invalid metric_id")
        _require(isinstance(item["value"], (int,float,str,bool)) and not isinstance(item["value"], type(None)), "invalid metric value")
        _require(isinstance(item["unit"], str) and item["unit"], "metric unit required")
        metric_ids.append(item["metric_id"])
    _require(len(metric_ids) == len(set(metric_ids)), "metric observations must be unique by metric_id")

    classification = record["data_classification"]
    _require(classification in DATA_CLASSIFICATIONS, "invalid data_classification")
    _require(isinstance(record["payload"], dict), "payload must be an object")
    if classification == "PRIVATE_REFERENCE_ONLY":
        _require(set(record["payload"]) <= {"reference","summary","redacted"}, "private-reference payload cannot contain raw fields")
        _require(record["payload"].get("redacted") is True, "private-reference payload must be marked redacted")
        _require(isinstance(record["payload"].get("reference"), str) and record["payload"]["reference"], "private-reference payload requires reference")

    _require(record["idempotency_key"] == compute_idempotency_key(record), "idempotency_key mismatch")
    _require(record["event_hash"] == compute_event_hash(record), "event_hash mismatch")

    if evidence_by_id is not None:
        linked = []
        for evidence_id in record["evidence_ids"]:
            _require(evidence_id in evidence_by_id, f"missing linked evidence: {evidence_id}")
            evidence = evidence_by_id[evidence_id]
            validate_evidence(evidence)
            _require(evidence["project_id"] == record["project_id"], f"cross-project evidence link not allowed without explicit future bridge: {evidence_id}")
            linked.append(evidence)

        states = {e["evidence_state"] for e in linked}
        if status == "VERIFIED":
            _require("VERIFIED" in states, "VERIFIED event requires linked VERIFIED evidence")
        elif status == "INFERRED":
            _require(bool(states & {"VERIFIED","OBSERVED","INFERRED"}), "INFERRED event requires non-unknown basis")
        elif status == "CONTRADICTED":
            _require("CONTRADICTED" in states, "CONTRADICTED event requires linked contradicted evidence")
        elif status == "STALE":
            _require("STALE" in states, "STALE event requires linked stale evidence")
        elif status == "INVALID":
            _require("INVALID" in states, "INVALID event requires linked invalid evidence")

def validate_bundle(events: Iterable[dict[str, Any]], evidence: Iterable[dict[str, Any]]) -> dict[str, int]:
    evidence_list = list(evidence)
    event_list = list(events)
    evidence_by_id: dict[str, dict[str, Any]] = {}
    hashes = set()
    for item in evidence_list:
        validate_evidence(item)
        eid = item["evidence_id"]
        _require(eid not in evidence_by_id, f"duplicate evidence_id: {eid}")
        _require(item["evidence_hash"] not in hashes, f"duplicate evidence_hash: {item['evidence_hash']}")
        evidence_by_id[eid] = item
        hashes.add(item["evidence_hash"])

    event_by_id: dict[str, dict[str, Any]] = {}
    idempotency = set()
    event_hashes = set()
    for item in event_list:
        validate_event(item, evidence_by_id)
        eid = item["event_id"]
        _require(eid not in event_by_id, f"duplicate event_id: {eid}")
        _require(item["idempotency_key"] not in idempotency, f"duplicate source event idempotency_key: {item['idempotency_key']}")
        _require(item["event_hash"] not in event_hashes, f"duplicate event_hash: {item['event_hash']}")
        event_by_id[eid] = item
        idempotency.add(item["idempotency_key"])
        event_hashes.add(item["event_hash"])

    for item in event_list:
        for dependency in item["dependency_event_ids"]:
            _require(dependency in event_by_id, f"missing dependency event: {dependency}")
        for causal in item["causal_event_ids"]:
            _require(causal in event_by_id, f"missing causal event: {causal}")

    return {"events": len(event_list), "evidence": len(evidence_list)}

def load_event_type_catalog() -> set[str]:
    data = json.loads((ROOT / "events" / "EVENT_TYPE_CATALOG.json").read_text(encoding="utf-8"))
    _require(data.get("schema_version") == "1.0.0", "event type catalog schema_version mismatch")
    values = data.get("event_types")
    _unique_strings(values, "event_types")
    _require(all(EVENT_TYPE.fullmatch(x) is not None for x in values), "event type catalog contains invalid name")
    return set(values)
