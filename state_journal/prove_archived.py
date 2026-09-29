"""Replay exact archived production states. This is NOT live event-stream proof."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

from state_journal.contracts import canonical, digest, require, strict_load
from state_journal.events import make_change, make_event
from state_journal.reducer import checkpoint, make_snapshot, advance, validate_snapshot
from state_journal.transport import GitHubReader
from runtime.artifact_state import validate_runtime_artifact_bundle

SOURCE_SHA = "87a8ed87ec69eabe1a2be7f520b4c4b59ba50818"
ARCHIVES = {
    "runtime125": (11040673069, 36583811231, "8d8ab394c8a36bf4aaaae361da835f0548c955dfb811b2e41310b5cdb78834f8", "runtime_state.json"),
    "heartbeat134": (11040378363, 36583811231, "1c34b8e9ef2d83358e60c358acdbe7c0b0bdd098da3701ec2578d2a7e959365f", "agent_heartbeat_state.json"),
    "runtime126": (11040158694, 36583811390, "59c80ec590725642ce42ef044e962de1a32718f21aaf2524f7d9565b11e09654", "runtime_state.json"),
    "heartbeat135": (11040158700, 36583811390, "6534c40338f1ee0c2b7bd6b61788a621934b2b715d1f1ad6ddf55e05a670b3ba", "agent_heartbeat_state.json"),
    "heartbeat136": (11040338366, 36584001091, "7f19b3a5e36fc88891d68afe14f593c432bb8dd36e69588d1fbd8f199dc3b2df", "agent_heartbeat_state.json"),
}


def prove(directory: Path, *, fetch: bool = False) -> dict:
    reader = GitHubReader(os.environ.get("GITHUB_TOKEN", "")) if fetch else None
    values = {}; receipts = {}; sources = []
    directory.mkdir(parents=True, exist_ok=True)
    for name, (artifact_id, run_id, expected, member) in ARCHIVES.items():
        path = directory / (name + ".zip")
        if reader:
            meta = reader.get(f"/actions/artifacts/{artifact_id}")
            require(meta.get("id") == artifact_id and meta.get("workflow_run", {}).get("id") == run_id,
                    "Archived provider source identity changed")
            require(meta["workflow_run"].get("head_sha") == SOURCE_SHA and meta["workflow_run"].get("head_branch") == "main",
                    "Archived source revision mismatch")
            require(meta.get("digest") == "sha256:" + expected and meta.get("expired") is False,
                    "Archived provider digest missing, changed or expired")
            path.write_bytes(reader.archive(artifact_id))
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected, "Pinned production archive digest mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            require(archive.namelist().count(member) == 1, "Missing/duplicate archived state")
            values[name] = strict_load(archive.read(member))
            if name.startswith("runtime"):
                validate_runtime_artifact_bundle(raw, max_archive_bytes=16777216, max_member_bytes=16777216)
                receipts[name] = strict_load(archive.read("cycle_receipt.json"))
        sources.append({"name": name, "artifact_id": artifact_id, "source_run_id": run_id,
                        "source_sha": SOURCE_SHA, "archive_sha256": expected})
    base = checkpoint({"runtime": values["runtime125"], "heartbeat": values["heartbeat134"]},
                      {"runtime": "github-artifact:11040673069", "heartbeat": "github-artifact:11040378363"})
    runtime = make_event("runtime-worker", "36583811390", SOURCE_SHA, [
        make_change("runtime", values["runtime125"], values["runtime126"], proofs={"cycle_receipt": receipts["runtime126"]}),
        make_change("heartbeat", values["heartbeat134"], values["heartbeat135"]),
    ])
    hunter_heartbeat = make_event("hunter-autonomous-cycle", "36584001091", SOURCE_SHA, [
        make_change("heartbeat", values["heartbeat135"], values["heartbeat136"]),
    ])
    initial = make_snapshot(base, [], sequence=0, evidence={})
    def pair(e):
        # These events are reconstructed here, NOT claimed to have been emitted
        # by the old production workflows. Their exact input archives are above.
        return e, {"kind": "FIXTURE", "event_hash": e["event_hash"], "fixture_id": "fixture:archived-production-replay"}
    forward = advance(initial, [pair(runtime), pair(hunter_heartbeat)])
    reverse = advance(initial, [pair(hunter_heartbeat), pair(runtime)])
    require(forward == reverse, "Replay depends on delivery order")
    require(forward["projection"]["states"]["runtime"] == values["runtime126"], "Runtime replay differs from actual saved state")
    require(forward["projection"]["states"]["heartbeat"] == values["heartbeat136"], "Heartbeat replay differs from actual saved state")
    require(advance(forward, [pair(runtime), pair(hunter_heartbeat)]) == forward, "Duplicate delivery changed state")
    validate_snapshot(strict_load(canonical(forward)))
    return {"status": "PASS", "evidence_class": "ARCHIVED_PRODUCTION_STATE_REPLAY", "sources": sources,
            "event_count": 2, "runtime_sequence": 126, "heartbeat_sequence": 136,
            "exact_native_state_equality": True, "reverse_delivery_equality": True, "duplicate_delivery_no_effect": True,
            "projection_hash": forward["projection"]["projection_hash"],
            "live_event_stream_exercised": False, "production_cutover_complete": False,
            "commercial_value_claimed": False, "steps_3_to_8_started": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--fetch", action="store_true")
    args = p.parse_args()
    report = prove(args.archive_dir, fetch=args.fetch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(report) + b"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
