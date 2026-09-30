#!/usr/bin/env python3
"""Restore durable Portfolio Brain state for the read-only command center.

This bridge is intentionally OBSERVE-only. It restores sanitized GitHub Actions
artifacts into a temporary dashboard/live directory for rendering. If a valid
artifact is unavailable, it falls back to the checked-in seed and labels that
source explicitly. Stale artifacts are used but labeled STALE.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agents.artifact_state import restore as restore_agents
from cost_governor.artifact_state import restore as restore_cost
from hunting.artifact_state import restore as restore_hunter
from hunting.proposal_artifact_state import restore as restore_hunter_proposals
from hunting.proposal_review_artifact_state import restore as restore_hunter_proposal_reviews
from learning.artifact_state import restore as restore_learning
from notifications.artifact_state import restore as restore_notifications
from model_router.feedback_artifact_state import restore as restore_model_feedback
from runtime.artifact_state import restore as restore_runtime
from runtime.state import bootstrap_state, validate_state as validate_runtime_state
from scheduler.artifact_state import restore as restore_scheduler
from operations.liveness_artifact_state import restore as restore_liveness, load_verified
from operations.workflow_liveness import _hash_value

ROOT = Path(__file__).resolve().parents[1]

STALE_AFTER_MINUTES = {
    "runtime": 150,
    "scheduler": 150,
    "hunter": 450,
    "cost": 60,
    "notifications": 450,
    "provider": 1560,
    "agents": 180,
    "model_feedback": 10080,
    "learning": 10080,
    "hunter_proposals": 450,
    "hunter_proposal_reviews": 450,
}

SEEDS = {
    "scheduler": "scheduler/SCHEDULER_STATE_SEED.json",
    "hunter": "hunting/HUNTER_STATE_SEED.json",
    "cost": "cost_governor/COST_STATE_SEED.json",
    "notifications": "notifications/NOTIFICATION_STATE_SEED.json",
    "provider": "runtime/PROVIDER_HEALTH_SEED.json",
    "agents": "agents/AGENT_HEARTBEAT_STATE_SEED.json",
    "model_feedback": "model_router/MODEL_FEEDBACK_STATE_SEED.json",
    "learning": "learning/LIVE_OBSERVATION_STATE_SEED.json",
    "hunter_proposals": "hunting/HUNTER_PROPOSAL_STATE_SEED.json",
    "hunter_proposal_reviews": "hunting/HUNTER_PROPOSAL_REVIEW_STATE_SEED.json",
}

RESTORERS: dict[str, Callable[..., str]] = {
    "runtime": restore_runtime,
    "scheduler": restore_scheduler,
    "hunter": restore_hunter,
    "cost": restore_cost,
    "notifications": restore_notifications,
    "agents": restore_agents,
    "model_feedback": restore_model_feedback,
    "learning": restore_learning,
    "hunter_proposals": restore_hunter_proposals,
    "hunter_proposal_reviews": restore_hunter_proposal_reviews,
}

CORE_HEALTH_SOURCES = {"runtime","scheduler","hunter","cost","notifications"}
OPTIONAL_OBSERVABILITY_SOURCES = {"agents","provider","model_feedback","learning","hunter_proposals","hunter_proposal_reviews"}
EVIDENCE_SEMANTICS = {
    "heartbeat": "LIVENESS_CONNECTIVITY_ONLY",
    "notification": "ALERT_ONLY",
    "pages": "PUBLICATION_ONLY",
    "technical_verification_credit": False,
    "market_verification_credit": False,
    "revenue_verification_credit": False,
}


class LiveStateBridgeError(ValueError):
    pass


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise LiveStateBridgeError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def _now_iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _state_filename(name: str) -> str:
    return {
        "runtime": "runtime_state.json",
        "scheduler": "scheduler_state.json",
        "hunter": "hunter_state.json",
        "cost": "cost_state.json",
        "notifications": "notification_state.json",
        "provider": "provider_health.json",
        "agents": "agent_heartbeat_state.json",
        "model_feedback": "model_feedback_state.json",
        "learning": "learning_observation_state.json",
        "hunter_proposals": "hunter_proposal_state.json",
        "hunter_proposal_reviews": "hunter_proposal_review_state.json",
    }[name]


def _fallback(name: str, output: Path, *, now: datetime) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    if name == "runtime":
        state = bootstrap_state(now=_now_iso(now))
        validate_runtime_state(state)
        output.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return "adapters/cursors/repositories.json"
    seed = ROOT / SEEDS[name]
    shutil.copyfile(seed, output)
    return SEEDS[name]


def _fallback_status(restore_status: str | None, error_class: str | None) -> str:
    if error_class:
        return "BLOCKED"
    value=(restore_status or "").upper()
    if any(token in value for token in ("ERROR","FAILED","INVALID","BLOCKED","REJECTED","CORRUPT")):
        return "BLOCKED"
    return "FALLBACK"


def _classify(meta: dict[str, Any], *, now: datetime, stale_after_minutes: int) -> tuple[str, float | None]:
    created = meta.get("artifact_created_at")
    if not isinstance(created, str) or not created:
        return "FALLBACK", None
    age = max(0.0, (now - _time(created)).total_seconds() / 60.0)
    return ("STALE" if age > stale_after_minutes else "LIVE"), round(age, 1)


def apply_cost_verification(source:dict[str,Any], state:dict[str,Any], liveness:dict[str,Any]|None, *, now:datetime)->None:
    """Freshness of an actual unchanged-ledger check, never a ledger mutation."""
    if source.get("source_kind")!="GITHUB_ACTIONS_ARTIFACT" or source.get("status") in {"FALLBACK","BLOCKED"} or not liveness:
        return
    proof=liveness.get("cost_state_proof")
    if not isinstance(proof,dict):return
    try:
        age=(now-_time(proof["checked_at"])).total_seconds()/60
        valid=(proof.get("status")=="VERIFIED_UNCHANGED_STATE"
               and proof.get("state_mutated") is False
               and proof["checked_at"]==liveness["checked_at"]
               and 0<=age<=STALE_AFTER_MINUTES["cost"]
               and type(proof.get("state_sequence")) is int
               and proof["state_sequence"]==state["sequence"]
               and proof.get("state_hash")==_hash_value(state)
               and proof.get("state_updated_at")==state["updated_at"]
               and proof.get("source_artifact_id")==source.get("artifact_id")
               and proof.get("source_run_id")==source.get("source_run_id"))
    except (ValueError,KeyError,TypeError):return
    if valid:
        source.update(status="LIVE", freshness_basis="VERIFIED_UNCHANGED_LEDGER",
                      last_verified_at=proof["checked_at"],verification_age_minutes=round(age,1))

def build_live_state(
    *,
    output_dir: Path,
    receipt_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir = output_dir / ".restore-metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # Reuse the existing watchdog's exact-run evidence; failed reads stay unverified.
    try:
        restore_liveness(output_dir/"workflow_liveness_receipt.json",output_dir/"workflow_liveness_restore.json",now=now)
    except Exception:
        pass
    liveness=load_verified(output_dir,now=now)
    sources: dict[str, Any] = {}
    for name, restorer in RESTORERS.items():
        state_path = output_dir / _state_filename(name)
        metadata_path = metadata_dir / f"{name}.json"
        restore_status = "RESTORE_ERROR"
        error_class = None
        try:
            if name == "runtime":
                restore_status = restorer(
                    output=state_path,
                    metadata_output=metadata_path,
                    provider_health_output=output_dir / _state_filename("provider"),
                    provider_health_metadata_output=metadata_dir / "provider.json",
                )
            else:
                restore_status = restorer(state_path, metadata_path)
        except Exception as exc:
            error_class = type(exc).__name__
            restore_status = "RESTORE_ERROR"

        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        if restore_status.startswith("RESTORED") and state_path.exists():
            freshness, age = _classify(
                metadata,
                now=now,
                stale_after_minutes=STALE_AFTER_MINUTES[name],
            )
            source_ref = metadata.get("artifact_name")
            source_kind = "GITHUB_ACTIONS_ARTIFACT"
        else:
            source_ref = _fallback(name, state_path, now=now)
            source_kind = "CHECKED_IN_SEED"
            freshness = _fallback_status(restore_status,error_class)
            age = None

        state = json.loads(state_path.read_text(encoding="utf-8"))
        sources[name] = {
            "status": freshness,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "restore_status": restore_status,
            "source_run_id": metadata.get("source_run_id"),
            "source_head_sha": metadata.get("source_head_sha"),
            "artifact_id": metadata.get("artifact_id"),
            "artifact_created_at": metadata.get("artifact_created_at"),
            "artifact_expires_at": metadata.get("artifact_expires_at"),
            "age_minutes": age,
            "stale_after_minutes": STALE_AFTER_MINUTES[name],
            "state_sequence": state.get("sequence"),
            "source_sequence": state.get("sequence"),
            "source_state_hash": _hash_value(state),
            "state_updated_at": state.get("updated_at"),
            "error_class": error_class,
        }

    provider_path=output_dir/_state_filename("provider")
    provider_metadata_path=metadata_dir/"provider.json"
    provider_metadata=json.loads(provider_metadata_path.read_text(encoding="utf-8")) if provider_metadata_path.exists() else {}
    provider_restore_status=provider_metadata.get("restore_status","NO_VALID_PROVIDER_HEALTH_ARTIFACT")
    if provider_restore_status.startswith("RESTORED") and provider_path.exists():
        provider_freshness,provider_age=_classify(provider_metadata,now=now,stale_after_minutes=STALE_AFTER_MINUTES["provider"])
        provider_ref=provider_metadata.get("artifact_name")
        provider_kind="GITHUB_ACTIONS_ARTIFACT"
    else:
        provider_ref=_fallback("provider",provider_path,now=now)
        provider_kind="CHECKED_IN_SEED"
        provider_freshness=_fallback_status(provider_restore_status,provider_metadata.get("error_class"))
        provider_age=None
    provider_state=json.loads(provider_path.read_text(encoding="utf-8"))
    sources["provider"]={
      "status":provider_freshness,"source_kind":provider_kind,"source_ref":provider_ref,
      "restore_status":provider_restore_status,"source_run_id":provider_metadata.get("source_run_id"),
      "source_head_sha":provider_metadata.get("source_head_sha"),"artifact_id":provider_metadata.get("artifact_id"),
      "artifact_created_at":provider_metadata.get("artifact_created_at"),
      "artifact_expires_at":provider_metadata.get("artifact_expires_at"),"age_minutes":provider_age,
      "stale_after_minutes":STALE_AFTER_MINUTES["provider"],"state_sequence":provider_state.get("sequence"),
      "source_sequence":provider_state.get("sequence"),"source_state_hash":_hash_value(provider_state),
      "state_updated_at":provider_state.get("updated_at"),"error_class":provider_metadata.get("error_class"),
    }

    cost_state=json.loads((output_dir/_state_filename("cost")).read_text())
    apply_cost_verification(sources["cost"],cost_state,liveness,now=now)

    # System health is based on core operational state only. Optional
    # observability sources (provider readiness and agent heartbeats) may still
    # be warming up without degrading an otherwise healthy control plane.
    core_statuses = {sources[name]["status"] for name in CORE_HEALTH_SOURCES}
    if "BLOCKED" in core_statuses:
        bridge_status = "BLOCKED"
    elif core_statuses == {"LIVE"}:
        bridge_status = "LIVE"
    elif core_statuses == {"FALLBACK"}:
        bridge_status = "FALLBACK"
    elif core_statuses == {"STALE"}:
        bridge_status = "STALE"
    else:
        bridge_status = "DEGRADED"
    receipt = {
        "schema_version": "1.0.0",
        "bridge_id": "portfolio-command-center-live-state-v1",
        "authority_class": "OBSERVE",
        "mutation_capability": "NONE",
        "generated_at": _now_iso(now),
        "bridge_status": bridge_status,
        "health_sources": sorted(CORE_HEALTH_SOURCES),
        "optional_observability_sources": sorted(OPTIONAL_OBSERVABILITY_SOURCES),
        "sources": sources,
        "evidence_semantics": dict(EVIDENCE_SEMANTICS),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore command-center durable state")
    parser.add_argument("--output-dir", default="dashboard/live")
    parser.add_argument("--receipt", default="dashboard/live/state_sources.json")
    parser.add_argument("--now", default=None)
    args = parser.parse_args()
    now = None if args.now is None else _time(args.now)
    receipt = build_live_state(
        output_dir=Path(args.output_dir),
        receipt_path=Path(args.receipt),
        now=now,
    )
    print(json.dumps({
        "bridge_status": receipt["bridge_status"],
        "sources": {k: v["status"] for k, v in receipt["sources"].items()},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
