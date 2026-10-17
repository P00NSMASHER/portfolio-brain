"""Read-only inspection of ORIGINAL locally downloaded GitHub Actions ZIPs.

This module DOES NOT fetch provider data or authenticate a Cloudflare scheduled
event. The digest metadata is a caller-supplied value which must first be read
independently from the GitHub artifacts API. All returned evidence is explicitly
non-authoritative; it cannot certify the V5 six-hour production acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import zipfile

from soak_v3.audit import (
    EvidenceError, require, sha40, utc, verify_artifact,
)

MAX_ORIGINAL_ARTIFACTS = 100
MAX_MANIFEST_BYTES = 256_000
EXPECTED_OPERATIONS = {
    "preflight/report.json": "preflight",
    "report/report.json": "monitor",
    "research/report.json": "research",
    "experiment/report.json": "experiment",
    "doctor/report.json": "doctor",
}


def _load_json_member(archive, name):
    try:
        info = archive.getinfo(name)
        require(info.file_size <= 200_000, "ORIGINAL_MEMBER_SIZE_EXCEEDED")
        value = json.loads(archive.read(name))
    except (KeyError, ValueError, UnicodeError, OSError, zipfile.BadZipFile) as exc:
        raise EvidenceError("ORIGINAL_MEMBER_MISSING_OR_INVALID") from exc
    require(type(value) is dict, "ORIGINAL_MEMBER_NOT_OBJECT")
    return value


def inspect_original_zip_bundle(manifest):
    """Verify real local ZIP bytes, contiguous embedded delivery, and no success
    claim beyond byte-level evidence. The manifest is NOT provider-authenticated.
    """
    require(type(manifest) is dict, "ORIGINAL_MANIFEST_NOT_OBJECT")
    source = sha40(manifest.get("source_sha"))
    first_parent = sha40(manifest.get("first_state_parent"))
    artifacts = manifest.get("artifacts")
    require(type(artifacts) is list and 1 <= len(artifacts) <= MAX_ORIGINAL_ARTIFACTS,
            "ORIGINAL_ARTIFACT_LIST_INVALID")
    # Validate the complete submitted run-ID order before reading ANY ZIP.
    # This yields stable error attribution even if a reversed manifest would
    # otherwise encounter an earlier state-parent mismatch.
    previous_input_run = 0
    for item in artifacts:
        require(type(item) is dict, "ORIGINAL_ARTIFACT_ROW_INVALID")
        value = item.get("run_id")
        require(type(value) is int and value > previous_input_run,
                "ORIGINAL_RUN_ORDER_OR_ID_INVALID")
        previous_input_run = value
    previous_parent = first_parent
    previous_run = 0
    previous_sequence = -1
    previous_signed_time = None
    previous_doctor_time = None
    records = []
    for row in artifacts:
        require(type(row) is dict, "ORIGINAL_ARTIFACT_ROW_INVALID")
        run_id = row.get("run_id")
        require(type(run_id) is int and run_id > previous_run,
                "ORIGINAL_RUN_ORDER_OR_ID_INVALID")
        original_path = row.get("path")
        require(type(original_path) is str and len(original_path) <= 4096,
                "ORIGINAL_FILE_PATH_INVALID")
        # The provider digest here has to be sourced out-of-band and independently
        # confirmed. A forged digest+ZIP pair can satisfy this pure offline check.
        digest = row.get("provider_digest")
        state_commit = sha40(row.get("state_commit"))
        require(state_commit != previous_parent, "ORIGINAL_STATE_NO_ADVANCE")
        result = verify_artifact(
            original_path, digest, run_id=run_id, source_sha=source,
            state_parent=previous_parent, state_commit=state_commit,
        )
        with zipfile.ZipFile(original_path) as archive:
            cf = _load_json_member(archive, "cloudflare-origin.json")
            require(
                cf.get("kind") == "cloudflare_cron_v1"
                and cf.get("signed_origin") is True
                and cf.get("soak_pass") is False
                and cf.get("source_sha") == source
                and cf.get("status") == "CLOUDFLARE_SIGNED_ORIGIN_VERIFIED",
                "ORIGINAL_EMBEDDED_CLOCK_NOT_VALIDATED",
            )
            signed_time = utc(cf.get("scheduled_at"))
            doctor = _load_json_member(archive, "doctor/report.json")
            doctor_time = utc(doctor.get("checked_at"))
            require(
                doctor.get("mandatory_workloads") ==
                {"monitor": "PASS", "research": "PASS", "experiment": "PASS"}
                and doctor.get("verified_canonical_state") is True
                and doctor.get("production_accepted") is False,
                "ORIGINAL_DOCTOR_SCOPE_INVALID",
            )
            for path, operation in EXPECTED_OPERATIONS.items():
                payload = _load_json_member(archive, path)
                require(
                    payload.get("status") == "PASS"
                    and payload.get("source_sha") == source,
                    "ORIGINAL_MANDATORY_REPORT_FAILED",
                )
            require(
                result["state_sequence"] > previous_sequence,
                "ORIGINAL_STATE_SEQUENCE_NOT_INCREASING",
            )
            require(
                previous_signed_time is None or signed_time > previous_signed_time,
                "ORIGINAL_SCHEDULE_ORDER_INVALID",
            )
            require(
                previous_doctor_time is None or doctor_time > previous_doctor_time,
                "ORIGINAL_DOCTOR_TIME_ORDER_INVALID",
            )
            records.append({
                "run_id": run_id,
                "artifact_sha256": result["artifact_sha256"],
                "state_parent": previous_parent,
                "state_commit": state_commit,
                "state_sequence": result["state_sequence"],
                "canonical_hash": result["canonical_hash"],
                "embedded_scheduled_at": cf["scheduled_at"],
                "embedded_doctor_checked_at": doctor["checked_at"],
                "zip_bytes_verified": True,
                "embedded_clock_claim_checked": True,
            })
        previous_run = run_id
        previous_parent = state_commit
        previous_sequence = result["state_sequence"]
        previous_signed_time = signed_time
        previous_doctor_time = doctor_time

    expected_tip = manifest.get("expected_last_state_commit")
    if expected_tip is not None:
        require(sha40(expected_tip) == previous_parent, "ORIGINAL_FINAL_STATE_TIP_MISMATCH")
    first_time = utc(records[0]["embedded_doctor_checked_at"])
    last_time = utc(records[-1]["embedded_doctor_checked_at"])
    return {
        "scope": "OFFLINE_ORIGINAL_GITHUB_ARTIFACT_BYTES_ONLY",
        "status": "EVIDENCE_INSPECTED_NOT_ACCEPTED",
        "source_sha": source,
        "run_count": len(records),
        "original_zip_digest_matches_supplied_provider_metadata": True,
        "embedded_state_parent_chain_contiguous": True,
        "first_state_parent": first_parent,
        "last_state_commit": previous_parent,
        "first_doctor_checked_at": records[0]["embedded_doctor_checked_at"],
        "last_doctor_checked_at": records[-1]["embedded_doctor_checked_at"],
        "doctor_timestamp_span_seconds": (last_time-first_time).total_seconds(),
        "records": records,
        "independent_github_digest_provenance_verified": False,
        "independent_cloudflare_cron_provenance_verified": False,
        "original_remote_state_bytes_replayed": False,
        "complete_failed_and_excluded_run_census_verified": False,
        "soak_pass": False,
        "terminal_v5_acceptance": "NOT_ESTABLISHED",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline non-authoritative original ZIP audit")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(args.manifest.stat().st_size <= MAX_MANIFEST_BYTES,
                "ORIGINAL_MANIFEST_TOO_LARGE")
        doc = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = inspect_original_zip_bundle(doc)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (EvidenceError, OSError, TypeError, ValueError, KeyError) as exc:
        # No source file paths, URLs or exception messages in evidence logs.
        reason = str(exc) if isinstance(exc, EvidenceError) else "ORIGINAL_AUDIT_INVALID_INPUT"
        print(json.dumps({
            "scope": "OFFLINE_ORIGINAL_GITHUB_ARTIFACT_BYTES_ONLY",
            "status": "BLOCKED", "terminal_v5_acceptance": "NOT_ESTABLISHED",
            "reason": reason[:160],
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
