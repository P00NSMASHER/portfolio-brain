"""Capture immutable transitions using production validation and heartbeat replay."""
from __future__ import annotations

import io
import zipfile
from copy import deepcopy
from itertools import groupby

from agents.heartbeat_state import heartbeat
from dashboard.history_state import history_observation, replay_history_observation
from state_journal.contracts import (
    DOMAINS, PRODUCERS, REPOSITORY, SCHEMA, EVENT_SCHEMA_ATTEMPT, MAX_BYTES,
    Conflict, JournalError, canonical, digest, event_hash, event_identity,
    fields, require, validate_domain,
)


def replay_heartbeat_batch(state: dict, batch: dict) -> dict:
    fields(batch, {"at", "activity_kind", "source_workflow", "source_run_id", "work_ids_by_agent"}, "Heartbeat batch")
    require(isinstance(batch["work_ids_by_agent"], dict) and batch["work_ids_by_agent"], "Empty heartbeat batch")
    return heartbeat(state, agent_ids=sorted(batch["work_ids_by_agent"]),
                     work_ids_by_agent=batch["work_ids_by_agent"], at=batch["at"],
                     activity_kind=batch["activity_kind"], source_workflow=batch["source_workflow"],
                     source_run_id=batch["source_run_id"])


def heartbeat_batches(before: dict, after: dict) -> list[dict] | None:
    """Infer only batches that reproduce the full after-state exactly; otherwise CAS."""
    known = {row["event_id"] for row in before["recent_events"]}
    added = [row for row in after["recent_events"] if row["event_id"] not in known]
    keys = ("at", "activity_kind", "source_workflow", "source_run_id")
    groups = []
    for key, rows in groupby(added, key=lambda row: tuple(row[k] for k in keys)):
        rows = list(rows)
        if len({r["agent_id"] for r in rows}) != len(rows):
            return None
        groups.append(dict(zip(keys, key), work_ids_by_agent={r["agent_id"]: r["work_ids"] for r in rows}))
    try:
        rebuilt = deepcopy(before)
        for group in groups:
            rebuilt = replay_heartbeat_batch(rebuilt, group)
    except (ValueError, TypeError):
        return None
    return groups if groups and rebuilt == after else None


def make_change(domain: str, before: dict, after: dict, *, proofs: dict | None = None) -> dict:
    validate_domain(domain, before); validate_domain(domain, after)
    require(before["state_id"] == after["state_id"], "Domain identity changed")
    require(after["sequence"] >= before["sequence"], "Domain sequence rollback")
    require(after["sequence"] > before["sequence"] or after == before, "Different state at unchanged sequence")
    if domain == "history":
        observation = history_observation(before, after)
        if observation is not None:
            result = {"domain": domain, "before_hash": digest(before), "after_hash": digest(after),
                      "operation": "HISTORY_OBSERVATION", "observation": observation,
                      "proofs": deepcopy(proofs or {})}
            validate_change(result)
            return result
    batches = heartbeat_batches(before, after) if domain == "heartbeat" else None
    result = {"domain": domain, "before": deepcopy(before), "after": deepcopy(after),
              "before_hash": digest(before), "after_hash": digest(after),
              "operation": "HEARTBEAT_BATCHES" if batches else "COMPARE_AND_SWAP", "batches": batches or [], "proofs": deepcopy(proofs or {})}
    validate_change(result)
    return result


def validate_change(change: dict) -> None:
    if isinstance(change, dict) and change.get("operation") == "HISTORY_OBSERVATION":
        fields(change, {"domain", "before_hash", "after_hash", "operation", "observation", "proofs"},
               "History observation transition")
        require(change["domain"] == "history", "History observation operation used by another domain")
        require(all(isinstance(change[key], str) and change[key].startswith("sha256:")
                    for key in ("before_hash", "after_hash")), "History transition hashes invalid")
        require(change["proofs"] == {}, "Unexpected companion proofs")
        replay_history_observation(
            {"schema_version": "1.0.0", "state_id": "portfolio-command-center-history",
             "sequence": 0, "updated_at": None, "points": []},
            change["observation"],
        )
        return
    fields(change, {"domain", "before", "after", "before_hash", "after_hash", "operation", "batches", "proofs"}, "Transition")
    domain = change["domain"]
    validate_domain(domain, change["before"]); validate_domain(domain, change["after"])
    require(change["before_hash"] == digest(change["before"]), "Before-state hash mismatch")
    require(change["after_hash"] == digest(change["after"]), "After-state hash mismatch")
    require(change["after"]["state_id"] == change["before"]["state_id"], "Domain identity changed")
    require(change["after"]["sequence"] >= change["before"]["sequence"], "Domain sequence rollback")
    require(change["after"]["sequence"] > change["before"]["sequence"] or change["after"] == change["before"], "Unadvanced changed state")
    if domain == "runtime":
        fields(change["proofs"], {"cycle_receipt"}, "Runtime companion proofs")
        from runtime.artifact_state import validate_runtime_artifact_bundle
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("runtime_state.json", canonical(change["after"]))
            z.writestr("cycle_receipt.json", canonical(change["proofs"]["cycle_receipt"]))
        try:
            validate_runtime_artifact_bundle(archive.getvalue(), max_archive_bytes=MAX_BYTES, max_member_bytes=MAX_BYTES)
        except Exception as exc:
            raise JournalError("Runtime companion receipt does not bind after-state") from exc
    else:
        require(change["proofs"] == {}, "Unexpected companion proofs")
    require(change["operation"] in {"COMPARE_AND_SWAP", "HEARTBEAT_BATCHES"}, "Unknown transition operation")
    if change["operation"] == "COMPARE_AND_SWAP":
        require(change["batches"] == [], "CAS transition cannot carry hidden operations")
    else:
        require(domain == "heartbeat" and isinstance(change["batches"], list) and 0 < len(change["batches"]) <= 200,
                "Heartbeat operations not valid for domain")
        rebuilt = deepcopy(change["before"])
        try:
            for batch in change["batches"]:
                rebuilt = replay_heartbeat_batch(rebuilt, batch)
        except Exception as exc:
            raise JournalError("Heartbeat transition cannot be reproduced") from exc
        require(rebuilt == change["after"], "Heartbeat operations do not reproduce after-state")


def make_event(producer: str, run_id: str, source_sha: str, changes: list[dict],
               *, run_attempt: int | None = None) -> dict:
    require(producer in PRODUCERS, "Producer is not enrolled")
    kind = PRODUCERS[producer][0]
    schema = EVENT_SCHEMA_ATTEMPT if run_attempt is not None else SCHEMA
    event = {"schema_version": schema, "repository": REPOSITORY, "producer": producer,
             "run_id": run_id, "source_sha": source_sha, "event_type": kind,
             "event_id": event_identity(run_id, kind, source_sha, run_attempt),
             "changes": sorted(deepcopy(changes), key=lambda c: c["domain"])}
    if run_attempt is not None:
        require(type(run_attempt) is int and run_attempt > 0, "Provider run attempt required")
        event["run_attempt"] = run_attempt
    event["event_hash"] = event_hash(event)
    validate_event(event)
    return event


def upgrade_legacy_event_attempt(event: dict, run_attempt: int) -> dict:
    """Normalize an already-validated v1 provider event without mutating its archive."""
    validate_event(event)
    require(event["schema_version"] == SCHEMA and "run_attempt" not in event,
            "Only legacy events can be attempt-normalized")
    require(type(run_attempt) is int and run_attempt > 0, "Provider run attempt required")
    upgraded = deepcopy(event)
    upgraded["schema_version"] = EVENT_SCHEMA_ATTEMPT
    upgraded["run_attempt"] = run_attempt
    upgraded["event_id"] = event_identity(
        upgraded["run_id"], upgraded["event_type"], upgraded["source_sha"], run_attempt
    )
    upgraded["event_hash"] = event_hash(upgraded)
    validate_event(upgraded)
    return upgraded


def validate_event(event: dict) -> None:
    legacy_fields = {"schema_version", "repository", "producer", "run_id", "source_sha", "event_type", "event_id", "changes", "event_hash"}
    attempt_fields = legacy_fields | {"run_attempt"}
    if event.get("schema_version") == SCHEMA:
        fields(event, legacy_fields, "Event")
        run_attempt = None
    elif event.get("schema_version") == EVENT_SCHEMA_ATTEMPT:
        fields(event, attempt_fields, "Event")
        require(type(event["run_attempt"]) is int and event["run_attempt"] > 0, "Provider run attempt required")
        run_attempt = event["run_attempt"]
    else:
        require(False, "Event schema version unsupported")
    require(event["repository"] == REPOSITORY, "Event namespace mismatch")
    producer = event["producer"]
    require(producer in PRODUCERS, "Unknown producer")
    require(event["event_type"] == PRODUCERS[producer][0], "Producer/event type mismatch")
    require(event["event_id"] == event_identity(event["run_id"], event["event_type"], event["source_sha"], run_attempt), "Event identity mismatch")
    require(event["event_hash"] == event_hash(event), "Event hash mismatch")
    require(isinstance(event["changes"], list) and 0 < len(event["changes"]) <= len(DOMAINS), "Invalid transition count")
    domains = [c.get("domain") for c in event["changes"] if isinstance(c, dict)]
    require(len(domains) == len(event["changes"]) and len(set(domains)) == len(domains), "Duplicate/malformed domain transition")
    require(set(domains) <= PRODUCERS[producer][1], "Producer cannot write this domain")
    require(domains == sorted(domains), "Noncanonical transition order")
    for change in event["changes"]:
        validate_change(change)
        if change["operation"] == "HEARTBEAT_BATCHES":
            require(all(b["source_run_id"] == event["run_id"] and b["source_workflow"] == producer for b in change["batches"]),
                    "Heartbeat provenance does not match producer run")
    require(len(canonical(event)) <= MAX_BYTES, "Event exceeds byte budget")
