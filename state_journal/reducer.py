"""One deterministic reducer; no write occurs until every transition is verified.

The checkpoint is explicit, never manufactured from whichever artifact arrived
last. Events are retained unchanged. Unprovable forks and missing predecessors
raise before publishing any new projection. Nonconflicting heartbeat events are
replayed using the real production mutation function.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from runtime.artifact_restore import _atomic_write
from state_journal.contracts import (
    SCHEMA, MAX_SNAPSHOT_BYTES, MAX_EVENTS, Conflict, MissingPredecessor, canonical, digest,
    fields, require, validate_domain, validate_source_evidence,
)
from state_journal.events import validate_event, replay_heartbeat_batch
from dashboard.history_state import history_observation, replay_history_observation

STATE_ID = "portfolio-state-journal-shadow-v1"


def checkpoint(states: dict, source_refs: dict) -> dict:
    require(isinstance(states, dict) and states, "Explicit nonempty checkpoint required")
    require(isinstance(source_refs, dict) and set(source_refs) == set(states), "Checkpoint provenance must cover every domain")
    for name, value in states.items():
        validate_domain(name, value)
        require(isinstance(source_refs[name], str) and 0 < len(source_refs[name]) <= 500, "Checkpoint source reference required")
    doc = {"schema_version": SCHEMA, "states": deepcopy(states), "source_refs": deepcopy(source_refs)}
    doc["checkpoint_hash"] = digest(doc)
    return doc


def validate_checkpoint(doc: dict) -> None:
    fields(doc, {"schema_version", "states", "source_refs", "checkpoint_hash"}, "Checkpoint")
    require(canonical(doc) == canonical(checkpoint(doc["states"], doc["source_refs"])), "Checkpoint integrity mismatch")


def _timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(dt.tzinfo is not None, "Heartbeat time requires timezone")
    return dt.astimezone(timezone.utc)


def _replay_heartbeat_merge(base_state: dict, batches: dict[str, dict]) -> dict:
    """Replay the accepted heartbeat union and return its exact synthetic state."""
    latest = {}
    for row in base_state["recent_events"]:
        latest[(row["agent_id"], _timestamp(row["at"]))] = digest({k: v for k, v in row.items() if k != "event_id"})
    for batch in batches.values():
        for agent in batch["work_ids_by_agent"]:
            slot = agent, _timestamp(batch["at"])
            core = {k: batch[k] for k in ("at", "activity_kind", "source_workflow", "source_run_id")}
            core.update(agent_id=agent, work_ids=batch["work_ids_by_agent"][agent])
            core_hash = digest(core)
            if slot in latest and latest[slot] != core_hash:
                raise Conflict("Ambiguous equal-time heartbeat updates for one agent")
            latest[slot] = core_hash
    merged = deepcopy(base_state)
    for key in sorted(batches, key=lambda k: (_timestamp(batches[k]["at"]), k)):
        merged = replay_heartbeat_batch(merged, batches[key])
    return merged


def _replay_history_merge(base_state: dict, accepted_history: dict) -> dict:
    """Replay the accepted history union and return its exact synthetic state."""
    observations = {}
    slots = {}
    for point in accepted_history.values():
        point_hash = digest(point)
        slot = _timestamp(point["observed_at"])
        prior = slots.get(slot)
        if prior is not None and prior != point_hash:
            raise Conflict("Ambiguous equal-time history observations")
        slots[slot] = point_hash
        observations[point_hash] = point
    merged = deepcopy(base_state)
    for key in sorted(observations, key=lambda k: (_timestamp(observations[k]["observed_at"]), k)):
        try:
            merged = replay_history_observation(merged, observations[key])
        except ValueError as exc:
            raise Conflict("History observations do not form a monotonic exact replay") from exc
    return merged


def replay(base: dict, events: list[dict]) -> dict:
    validate_checkpoint(base)
    require(isinstance(events, list) and len(events) <= MAX_EVENTS, "Event capacity exceeded; archive required, never truncate")
    by_id = {}
    for event in events:
        validate_event(event)
        old = by_id.get(event["event_id"])
        if old is not None and old != event:
            raise Conflict("Same immutable event identity has different contents")
        by_id[event["event_id"]] = event
    ordered = [by_id[k] for k in sorted(by_id)]
    states = deepcopy(base["states"])
    all_changes = [c for e in ordered for c in e["changes"]]
    require(all(c["domain"] in states for c in all_changes), "Event domain missing from explicit checkpoint")

    merge_heartbeat = all(c["operation"] == "HEARTBEAT_BATCHES" for c in all_changes if c["domain"] == "heartbeat")
    history_changes = [c for c in all_changes if c["domain"] == "history"]
    history_ops = {}
    merge_history = bool(history_changes)
    for change in history_changes:
        point = history_observation(change["before"], change["after"]) if change["operation"] == "COMPARE_AND_SWAP" else None
        if point is None:
            merge_history = False
            history_ops = {}
            break
        history_ops[(change["before_hash"], change["after_hash"])] = point

    # Detect branches BEFORE order selection. Sorting event IDs is not authority
    # to choose between two different noncommuting updates to the same state.
    # Heartbeat batches and exact history observations are the only enrolled
    # domain-native operations that can be replayed losslessly across a fork.
    successors = {}
    for c in all_changes:
        if (
            (c["domain"] == "heartbeat" and merge_heartbeat)
            or (c["domain"] == "history" and merge_history)
            or c["before_hash"] == c["after_hash"]
        ):
            continue
        key = c["domain"], c["before_hash"]
        old = successors.get(key)
        if old is not None and old != c["after_hash"]:
            raise Conflict(f"Conflicting {c['domain']} transitions from the same predecessor")
        successors[key] = c["after_hash"]

    known_heartbeat = {digest(states["heartbeat"])} if "heartbeat" in states else set()
    known_history = {digest(states["history"])} if "history" in states else set()
    remaining = ordered[:]
    applied = []
    consumed = set()
    known = {name: {digest(value)} for name, value in states.items()}
    batches = {}
    accepted_history = {}
    while remaining:
        advanced = False
        for event in remaining[:]:
            def ready(c):
                if c["domain"] == "heartbeat" and merge_heartbeat:
                    return c["before_hash"] in known_heartbeat
                if c["domain"] == "history" and merge_history:
                    return c["before_hash"] in known_history
                key = c["domain"], c["before_hash"], c["after_hash"]
                return key in consumed or digest(states[c["domain"]]) in {c["before_hash"], c["after_hash"]} or (
                    c["before_hash"] == c["after_hash"] and c["before_hash"] in known[c["domain"]])
            if not all(ready(c) for c in event["changes"]):
                continue
            for change in event["changes"]:
                if change["domain"] == "heartbeat" and merge_heartbeat:
                    known_heartbeat.add(change["after_hash"])
                    for batch in change["batches"]:
                        batches[digest(batch)] = batch
                    # A lossless fork union is a real canonical predecessor even
                    # when its synthetic hash is not any one branch's after_hash.
                    known_heartbeat.add(digest(_replay_heartbeat_merge(base["states"]["heartbeat"], batches)))
                elif change["domain"] == "history" and merge_history:
                    known_history.add(change["after_hash"])
                    key = change["before_hash"], change["after_hash"]
                    accepted_history[key] = history_ops[key]
                    known_history.add(digest(_replay_history_merge(base["states"]["history"], accepted_history)))
                else:
                    key = change["domain"], change["before_hash"], change["after_hash"]
                    if key not in consumed and change["before_hash"] != change["after_hash"]:
                        states[change["domain"]] = deepcopy(change["after"])
                    consumed.add(key)
                    known[change["domain"]].add(change["after_hash"])
            applied.append(event["event_id"])
            remaining.remove(event); advanced = True
        if not advanced:
            raise MissingPredecessor("Unresolved predecessors: " + ",".join(e["event_id"] for e in remaining))

    if batches:
        states["heartbeat"] = _replay_heartbeat_merge(base["states"]["heartbeat"], batches)

    if accepted_history:
        states["history"] = _replay_history_merge(base["states"]["history"], accepted_history)

    for domain, state in states.items():
        validate_domain(domain, state)
    return {"states": states, "event_ids": sorted(by_id), "projection_hash": digest(states)}


def make_snapshot(base: dict, events: list[dict], *, sequence: int, evidence: dict,
                  mode: str = "SHADOW", production_authority: bool = False) -> dict:
    require(type(sequence) is int and sequence >= 0, "Invalid canonical sequence")
    require(mode in {"SHADOW", "CANONICAL"}, "Invalid canonical mode")
    require(type(production_authority) is bool, "Invalid production authority flag")
    require(not production_authority or mode == "CANONICAL", "Production authority requires CANONICAL mode")
    projected = replay(base, events)
    unique = {e["event_id"]: deepcopy(e) for e in events}
    require(isinstance(evidence, dict) and set(evidence) == set(unique), "Every event needs source evidence")
    # Evidence is provider-validated in transport, never inferred from PASS text.
    for key, refs in evidence.items():
        require(isinstance(refs, list) and refs and all(isinstance(r, dict) for r in refs), "Missing provider evidence")
        require(len({digest(r) for r in refs}) == len(refs), "Duplicated source evidence")
        for source in refs:
            validate_source_evidence(source, unique[key])
    state = {"schema_version": SCHEMA, "state_id": STATE_ID, "sequence": sequence,
             "mode": mode, "production_authority": production_authority,
             "checkpoint": deepcopy(base), "events": [unique[k] for k in sorted(unique)],
             "evidence": deepcopy(evidence), "projection": projected,
             "event_count": len(unique)}
    state["state_hash"] = digest(state)
    require(len(canonical(state)) <= MAX_SNAPSHOT_BYTES, "Journal capacity exceeded; do not drop evidence")
    return state


def validate_snapshot(state: dict) -> None:
    fields(state, {"schema_version", "state_id", "sequence", "mode", "production_authority", "checkpoint", "events", "evidence", "projection", "event_count", "state_hash"}, "Snapshot")
    require(canonical(state) == canonical(make_snapshot(
        state["checkpoint"], state["events"], sequence=state["sequence"], evidence=state["evidence"],
        mode=state["mode"], production_authority=state["production_authority"],
    )), "Snapshot does not match immutable replay")


def advance(state: dict, incoming: list[tuple[dict, dict]]) -> dict:
    validate_snapshot(state)
    events = {e["event_id"]: deepcopy(e) for e in state["events"]}
    evidence = deepcopy(state["evidence"])
    changed = False
    for event, source in incoming:
        validate_event(event)
        key = event["event_id"]
        if key in events and events[key] != event:
            raise Conflict("Immutable event identity collision; preserve both source artifacts")
        if key not in events:
            events[key] = deepcopy(event); evidence[key] = []; changed = True
        if source not in evidence[key]:
            evidence[key].append(deepcopy(source))
            evidence[key].sort(key=digest); changed = True
    if not changed:
        return deepcopy(state)
    return make_snapshot(
        state["checkpoint"], list(events.values()), sequence=state["sequence"] + 1, evidence=evidence,
        mode=state["mode"], production_authority=state["production_authority"],
    )


def set_authority(state: dict, *, mode: str, production_authority: bool) -> dict:
    validate_snapshot(state)
    return make_snapshot(
        state["checkpoint"], state["events"], sequence=state["sequence"], evidence=state["evidence"],
        mode=mode, production_authority=production_authority,
    )


def commit_file(output: Path, state: dict, incoming: list[tuple[dict, dict]]) -> dict:
    """Atomic all-or-nothing publication; caller must hold the reducer mutex."""
    candidate = advance(state, incoming)
    validate_snapshot(candidate)
    _atomic_write(output, canonical(candidate) + b"\n")
    return candidate