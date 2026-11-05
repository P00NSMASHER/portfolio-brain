"""Read exact-run artifacts as observations, never as independent release authority.

Called only after the original successful core and its artifact were checked
by GitHub. The downloaded archive is untrusted input: no executable content,
symlink following, write privileges, or optimistic interpretation of absences.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_DOCUMENT = 2_000_000


class CycleEvidenceError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise CycleEvidenceError(code)


def _json(root, name, *, required=True):
    path = root.joinpath(*name.split("/"))
    require(not path.is_symlink(), "CYCLE_ARTIFACT_SYMLINK_DENIED")
    if not path.exists() and not required:
        return None
    require(path.is_file() and 0 < path.stat().st_size <= MAX_DOCUMENT,
            "CYCLE_ARTIFACT_MISSING_OR_OVERSIZED")
    try:
        text = path.read_text(encoding="utf-8")
        def pairs(items):
            result = {}
            for key, value in items:
                require(key not in result, "CYCLE_DUPLICATE_JSON_KEY")
                result[key] = value
            return result
        data = json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, "CYCLE_NONFINITE_JSON"))
    except (UnicodeError, OSError, ValueError) as exc:
        raise CycleEvidenceError("CYCLE_ARTIFACT_INVALID_JSON") from exc
    require(type(data) is dict, "CYCLE_ARTIFACT_SCHEMA")
    return data


def inspect(root, *, source_sha, run_id, run_attempt=1):
    """Verify a single successful original core's published-state reconciliation."""
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(),
            "CYCLE_ARTIFACT_ROOT_UNSAFE")
    require(type(source_sha) is str and SHA.fullmatch(source_sha)
            and type(run_id) is int and 0 < run_id < 10**12
            and type(run_attempt) is int and run_attempt == 1,
            "CYCLE_ORIGIN_UNVERIFIED")
    delivery = _json(root, "delivery.json")
    restored = _json(root, "state-restoration.json")
    packed = _json(root, "state-publication.json")
    capacity = _json(root, "state-capacity.json")
    maintenance = _json(root, "state-maintenance.json")
    engineering = _json(root, "v8-engineering.json")
    owner_queue = _json(root, "v9-engineering.json", required=False)
    research = _json(root, "research/report.json", required=False)
    upgrade = _json(root, "upgrade/report.json", required=False)
    require(delivery.get("schema_version") == 2
            and delivery.get("source_sha") == source_sha
            and delivery.get("workflow") == "brain-cycle-v2"
            and delivery.get("run_id") == str(run_id)
            and delivery.get("run_attempt") == str(run_attempt)
            and delivery.get("publication_verified") is True
            and type(delivery.get("state_commit")) is str
            and SHA.fullmatch(delivery["state_commit"])
            and type(delivery.get("state_parent")) is str
            and SHA.fullmatch(delivery["state_parent"])
            and delivery["state_parent"] != delivery["state_commit"],
            "CYCLE_DELIVERY_RECEIPT_UNVERIFIED")
    require(restored.get("storage_format") == "sqlite-zlib-chunks-v1"
            and type(restored.get("raw_size")) is int
            and type(restored.get("compressed_size")) is int
            and restored.get("restored") is True
            and type(packed.get("raw_size")) is int
            and type(packed.get("compressed_size")) is int
            and packed.get("published") is False
            and packed.get("storage_format") == restored["storage_format"]
            and type(capacity.get("raw_size")) is int
            and type(capacity.get("compressed_size")) is int
            and capacity.get("status") == "VERIFIED_PRODUCTION_CAPACITY_ENVELOPE_PASS"
            and type(capacity.get("raw_headroom_bytes")) is int
            and type(capacity.get("compressed_headroom_bytes")) is int
            and capacity.get("published") is False
            and packed["raw_size"] == capacity["raw_size"]
            and packed["compressed_size"] == capacity["compressed_size"]
            and type(maintenance.get("storage_pressure")) is dict
            and maintenance["storage_pressure"].get("raw_bytes") == packed["raw_size"]
            # Maintenance is measured before later SQLite activity; the final
            # separately packed archive can differ even at identical raw size.
            # Only publication + capacity receipts certify the packed bytes.
            and type(maintenance["storage_pressure"].get("compressed_bytes")) is int
            and 0 < maintenance["storage_pressure"]["compressed_bytes"] <=
            capacity["verified_compressed_capacity_bytes"],
            "CYCLE_STATE_CAPACITY_RECEIPTS_CONFLICT")
    require(0 < restored["raw_size"] <= capacity["verified_raw_capacity_bytes"]
            and 0 < packed["raw_size"] <= capacity["verified_raw_capacity_bytes"]
            and 0 < packed["compressed_size"] <= capacity["verified_compressed_capacity_bytes"]
            and 0 <= capacity["raw_headroom_bytes"] ==
            capacity["verified_raw_capacity_bytes"] - packed["raw_size"]
            and 0 <= capacity["compressed_headroom_bytes"] ==
            capacity["verified_compressed_capacity_bytes"] - packed["compressed_size"],
            "CYCLE_STATE_CAPACITY_MARGIN_UNVERIFIED")
    require(engineering.get("source_sha") == source_sha
            and engineering.get("production_accepted") is False
            and type(engineering.get("owner_jobs")) is list,
            "CYCLE_ENGINEERING_PROOF_UNVERIFIED")
    verified_owner_stages = None
    owner_work_counts = None
    if owner_queue is not None:
        data = owner_queue.get("metrics")
        stages = data.get("stages") if type(data) is dict else None
        require(owner_queue.get("source_sha") == source_sha
                and type(data) is dict
                and type(data.get("work_items")) is int
                and 0 <= data["work_items"] <= 256
                and type(stages) is dict
                and set(stages) == {"OBSERVED","DIAGNOSED","PATCHED","TESTED","LIVE_VERIFIED"}
                and all(type(v) is int and v >= 0 for v in stages.values())
                and sum(stages.values()) == data["work_items"]
                and owner_queue.get("production_accepted") is False,
                "CYCLE_OWNER_QUEUE_SOURCE_UNVERIFIED")
        owner_work_counts = stages
        proof = owner_queue.get("verified_owner_progress")
        if proof is not None:
            require(type(proof) is dict and type(proof.get("status")) is str
                    and type(proof.get("provider_gets")) is int
                    and 0 <= proof["provider_gets"] <= 3
                    and type(proof.get("transitions")) is int
                    and 0 <= proof["transitions"] <= 3
                    and proof.get("production_accepted") is False,
                    "CYCLE_OWNER_PROGRESS_SCHEMA_INVALID")
            if proof["status"] == "REVIEWED_OWNER_REPAIR_TESTED_FROM_ORIGINAL_GITHUB":
                from brain.v9.reviewed_owner_followthrough import WORK_ID, MERGE_SHA
                require(proof.get("work_id") == WORK_ID
                        and proof.get("protected_merge_sha") == MERGE_SHA
                        and proof.get("independent_checks_verified") is True
                        and proof.get("real_world_functionality_verified") is False
                        and proof["transitions"] > 0
                        and stages["TESTED"] >= 1,
                        "CYCLE_OWNER_PROGRESS_CANNOT_SELF_CERTIFY")
                verified_owner_stages = proof["transitions"]
            else:
                verified_owner_stages = 0
    persisted_candidates = None
    coalesced = None
    if research is not None:
        op = research.get("operation")
        require(type(op) is dict and op.get("name") == "research"
                and research.get("source_sha") == source_sha
                and type(op.get("candidates_observed")) is int
                and 0 <= op["candidates_observed"] <= 100,
                "CYCLE_RESEARCH_REPORT_UNVERIFIED")
        coalesced = op.get("unchanged_events_coalesced", 0)
        require(type(coalesced) is int
                and 0 <= coalesced <= op["candidates_observed"],
                "CYCLE_RESEARCH_ACTIVITY_INVALID")
        persisted_candidates = op["candidates_observed"] - coalesced
    cooldown = None
    if upgrade is not None:
        require(upgrade.get("source_sha") == source_sha,
                "CYCLE_UPGRADE_SOURCE_UNVERIFIED")
        cooldown = upgrade.get("status") == "COOLDOWN"
    return {
        "schema_version": 1,
        "scope": "ONE_ORIGINAL_SUCCESSFUL_CORE_AND_ATTACHED_BYTES",
        "source_sha": source_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "state_commit": delivery["state_commit"],
        "state_parent": delivery["state_parent"],
        "source_snapshot_restored_bytes": restored["raw_size"],
        "published_snapshot_raw_bytes": packed["raw_size"],
        "published_snapshot_compressed_bytes": packed["compressed_size"],
        # This is an observation, not the authoritative packed archive size.
        "maintenance_compression_observation_bytes": maintenance["storage_pressure"]["compressed_bytes"],
        "maintenance_to_pack_compression_delta_bytes": (
            maintenance["storage_pressure"]["compressed_bytes"] - packed["compressed_size"]),
        "state_growth_raw_bytes": packed["raw_size"] - restored["raw_size"],
        "state_growth_compressed_bytes": packed["compressed_size"] - restored["compressed_size"],
        "raw_headroom_bytes": capacity["raw_headroom_bytes"],
        "compressed_headroom_bytes": capacity["compressed_headroom_bytes"],
        "verified_raw_capacity_bytes": capacity["verified_raw_capacity_bytes"],
        "verified_compressed_capacity_bytes": capacity["verified_compressed_capacity_bytes"],
        "storage_warning": maintenance["storage_pressure"].get("capacity_warning"),
        "reports_retained": maintenance["storage_pressure"].get("reports"),
        "candidate_events_persisted": persisted_candidates,
        "verified_novel_candidates": None,
        "unchanged_source_events_coalesced": coalesced,
        "unreleased_owner_jobs": len(engineering["owner_jobs"]),
        "owner_queue_stages": owner_work_counts,
        "original_provider_owner_stage_transitions": verified_owner_stages,
        "knowledge_cooldown_observed": cooldown,
        "functional_release_verified": None,
        "real_world_value_verified": None,
        "activity_classification": ("SOURCE_OBSERVATIONS_PERSISTED_NOT_PROVEN_NEW" if persisted_candidates
                                    else "NO_SOURCE_OBSERVATIONS_APPENDED" if persisted_candidates == 0
                                    else "RESEARCH_ACTIVITY_UNKNOWN"),
        "provider_writes": 0,
    }
