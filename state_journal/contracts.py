"""Closed, bounded event contracts. Hashes prove identity, not source authority."""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "P00NSMASHER/portfolio-brain"
SCHEMA = "1.0.0"
EVENT_SCHEMA_ATTEMPT = "1.1.0"
MAX_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 2000
# (production validation module, continuation input, produced output, seed)
DOMAINS = {
    "runtime": ("runtime.state", "runtime/live/runtime_state.json", "runtime/out/runtime_state.json", None),
    "heartbeat": ("agents.heartbeat_state", "agents/live/agent_heartbeat_state.json", "agents/out/agent_heartbeat_state.json", "agents/AGENT_HEARTBEAT_STATE_SEED.json"),
    "hunter": ("hunting.autonomous_hunter", "hunting/live/hunter_state.json", "hunting/out/hunter_state.json", "hunting/HUNTER_STATE_SEED.json"),
    "proposals": ("hunting.proposal_state", "hunting/live/hunter_proposal_state.json", "hunting/out/hunter_proposal_state.json", "hunting/HUNTER_PROPOSAL_STATE_SEED.json"),
    "reviews": ("hunting.proposal_review_state", "hunting/live/hunter_proposal_review_state.json", "hunting/out/hunter_proposal_review_state.json", "hunting/HUNTER_PROPOSAL_REVIEW_STATE_SEED.json"),
    "scheduler": ("scheduler.autonomous_scheduler", "scheduler/live/scheduler_state.json", "scheduler/out/scheduler_state.json", "scheduler/SCHEDULER_STATE_SEED.json"),
    "cost": ("cost_governor.cost_governor", "cost_governor/live/cost_state.json", "cost_governor/out/cost_state.json", "cost_governor/COST_STATE_SEED.json"),
    "model_feedback": ("model_router.feedback_state", "model_router/live/model_feedback_state.json", "value_proof/out/model_feedback_state.json", "model_router/MODEL_FEEDBACK_STATE_SEED.json"),
    "learning": ("learning.live_observations", "learning/live/learning_observation_state.json", "value_proof/out/learning_observation_state.json", "learning/LIVE_OBSERVATION_STATE_SEED.json"),
    "notifications": ("notifications.notification_engine", "notifications/live/notification_state.json", "notifications/out/notification_state.json", "notifications/NOTIFICATION_STATE_SEED.json"),
    "history": ("dashboard.history_state", "dashboard/live/history_state.json", "dashboard/out/history_state.json", "dashboard/HISTORY_STATE_SEED.json"),
}
# Source allowlists limit domain mutation independently of event self-description.
PRODUCERS = {
    "hunter-autonomous-cycle": ("HUNTER_CYCLE", {"hunter", "proposals", "heartbeat"}),
    "portfolio-autonomous-scheduler": ("SCHEDULER_CYCLE", {"scheduler", "hunter", "proposals", "reviews", "heartbeat"}),
    "runtime-worker": ("RUNTIME_CYCLE", {"runtime", "heartbeat", "cost"}),
    "agent-heartbeat-sweep": ("HEARTBEAT_CYCLE", {"heartbeat"}),
    "continuous-learning-bootstrap": ("LEARNING_BOOTSTRAP", {"hunter", "model_feedback", "learning"}),
    "verified-feedback-bootstrap": ("FEEDBACK_BOOTSTRAP", {"hunter", "model_feedback", "learning"}),
    "model-value-proof": ("MODEL_VALUE_CYCLE", {"hunter", "model_feedback", "learning", "cost"}),
    "software-factory-candidate": ("FACTORY_CYCLE", {"heartbeat"}),
    "portfolio-notification-cycle": ("NOTIFICATION_CYCLE", {"notifications"}),
    "command-center-pages": ("HISTORY_CYCLE", {"history"}),
    "operator-console": ("OPERATOR_CYCLE", {"scheduler"}),
}
RUNTIME_CALLERS = {"runtime-hourly-sync", "runtime-event-observe", "runtime-daily-learning", "runtime-weekly-synthesis", "provider-usability-acceptance"}
# Factory is reusable; external callers must be enrolled explicitly before ingestion.
WORKFLOW_PRODUCERS = {name: name for name in PRODUCERS if name not in {"runtime-worker", "software-factory-candidate"}}
WORKFLOW_PRODUCERS.update({name: "runtime-worker" for name in RUNTIME_CALLERS})


class JournalError(ValueError):
    pass


class Conflict(JournalError):
    pass


class MissingPredecessor(JournalError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise JournalError(message)


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise JournalError("Not finite canonical JSON") from exc


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def strict_load(raw: bytes) -> dict:
    require(len(raw) <= MAX_BYTES, "JSON byte limit exceeded")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda x: (_ for _ in ()).throw(JournalError("Nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise JournalError("Invalid JSON") from exc
    require(isinstance(value, dict), "Expected JSON object")
    canonical(value)
    return value


def fields(value: Any, keys: set[str], label: str) -> None:
    require(isinstance(value, dict) and set(value) == keys, f"{label} has unexpected fields")


def sha(value: Any) -> None:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None, "Exact source SHA required")


def positive_id(value: Any) -> None:
    require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None, "Provider run ID required")


def validate_domain(domain: str, state: dict) -> None:
    require(domain in DOMAINS, "Unknown state domain")
    require(isinstance(state, dict), "Domain state must be an object")
    require(type(state.get("sequence")) is int and state["sequence"] >= 0, "Invalid domain sequence")
    try:
        importlib.import_module(DOMAINS[domain][0]).validate_state(state)
    except Exception as exc:
        raise JournalError(f"{domain} production validator rejected state") from exc
    canonical(state)


def event_identity(run_id: str, event_type: str, source_sha: str, run_attempt: int | None = None) -> str:
    positive_id(run_id); sha(source_sha)
    require(event_type in {value[0] for value in PRODUCERS.values()}, "Unknown event type")
    identity = [REPOSITORY, run_id, event_type, source_sha]
    if run_attempt is not None:
        require(type(run_attempt) is int and run_attempt > 0, "Provider run attempt required")
        identity.append(run_attempt)
    return "PSE-" + digest(identity).split(":", 1)[1]


def event_hash(event: dict) -> str:
    return digest({key: value for key, value in event.items() if key != "event_hash"})


def validate_source_evidence(source: dict, event: dict) -> None:
    require(isinstance(source, dict), "Source evidence must be an object")
    require(source.get("event_hash") == event["event_hash"], "Source evidence event binding mismatch")
    if source.get("kind") == "FIXTURE":
        fields(source, {"kind", "event_hash", "fixture_id"}, "Fixture evidence")
        require(isinstance(source["fixture_id"], str) and re.fullmatch(r"fixture:[a-z0-9-]{1,80}", source["fixture_id"]) is not None,
                "Fixture evidence is explicitly isolated, never production authorization")
        return
    fields(source, {"kind", "repository", "artifact_id", "archive_digest", "source_run_id", "source_run_attempt",
                    "source_sha", "workflow_id", "workflow_path", "source_conclusion", "event_hash", "job_id"}, "Provider evidence")
    require(source["kind"] == "GITHUB_ACTIONS" and source["repository"] == REPOSITORY, "Untrusted evidence namespace")
    for key in ("artifact_id", "source_run_id", "source_run_attempt", "workflow_id", "job_id"):
        require(type(source[key]) is int and source[key] > 0, "Invalid provider evidence identity")
    require(str(source["source_run_id"]) == event["run_id"] and source["source_sha"] == event["source_sha"], "Provider evidence run/SHA mismatch")
    if event.get("schema_version") == EVENT_SCHEMA_ATTEMPT:
        require(source["source_run_attempt"] == event.get("run_attempt"), "Provider evidence attempt mismatch")
    require(isinstance(source["archive_digest"], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", source["archive_digest"]) is not None,
            "Archive digest required")
    name = source["workflow_path"]
    require(isinstance(name, str) and re.fullmatch(r"\.github/workflows/[a-z0-9-]+\.yml", name) is not None, "Unsafe workflow reference")
    require(WORKFLOW_PRODUCERS.get(Path(name).stem) == event["producer"], "Evidence producer authorization mismatch")
    require(source["source_conclusion"] in {"success", "failure", "cancelled", "timed_out"}, "Source outcome unknown")
