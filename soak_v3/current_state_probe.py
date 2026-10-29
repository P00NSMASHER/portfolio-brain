"""Original remote binary + canonical event/report replay, with no acceptance claim.

CLI is manual, read-only on GitHub, and writes only an explicitly supplied
new private local proof file. It never triggers a core, alters an acceptance
receipt, announces a six-hour PASS, or changes the production state branch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile

from brain.core import BrainError, Store
from soak_v3.audit import EvidenceError, require, sha40, sha64, verify_sqlite
from soak_v3.chunked_evidence import MAX_RAW_BYTES, verify_original_state
from soak_v3.remote_probe import GitHubReadOnly


def verify_source_state(api, *, state_commit, source_sha, expected_parent,
                        expected_sequence, expected_chain):
    """Proof about exact published bytes, not live scheduling or signed origin."""
    sha40(state_commit)
    sha40(source_sha)
    sha40(expected_parent)
    sha64(expected_chain)
    require(type(expected_sequence) is int and expected_sequence > 0,
            "EXPECTED_SEQUENCE_INVALID")
    before = api.json("/branches/main")
    require(before.get("commit", {}).get("sha") == source_sha,
            "CURRENT_MAIN_SOURCE_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="brain-original-state-proof-") as temp:
        folder = Path(temp)
        original = folder/"original.sqlite"
        source = verify_original_state(
            api, state_commit=state_commit, target=original
        )
        require(source["state_parent"] == expected_parent,
                "REMOTE_GIT_STATE_PARENT_MISMATCH")
        independent = verify_sqlite(
            original, expected_source=source_sha,
            expected_sequence=expected_sequence, expected_chain=expected_chain,
            max_bytes=MAX_RAW_BYTES, strict_event_ids=True,
        )
        require(independent["sha256"] == source["raw_image_sha256"],
                "INDEPENDENT_LEDGER_BYTES_MISMATCH")
        with sqlite3.connect(
            original.as_uri()+"?mode=ro&immutable=1", uri=True
        ) as db:
            row = db.execute(
                "SELECT body, created_at FROM reports ORDER BY id DESC LIMIT 1"
            ).fetchone()
            count = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
        require(row is not None, "LATEST_REPORT_MISSING")
        stored = json.loads(row[0])
        # The on-disk original bytes are immutable; replay the canonical app
        # projection on a separate, expendable SQLite copy only.
        copy = folder/"disposable-report-replay.sqlite"
        shutil.copyfile(original, copy)
        store = Store(copy, visibility="PUBLIC")
        try:
            replayed = store.read_report(source_sha, now=row[1])
        except BrainError as exc:
            raise EvidenceError("DETERMINISTIC_REPORT_REPLAY_FAILED") from exc
        finally:
            store.close()
        require(replayed == stored and replayed.get("status") == "PASS"
                and replayed.get("state_sequence") == expected_sequence
                and replayed.get("canonical_hash") == expected_chain
                and replayed.get("pending_events") == 0,
                "DETERMINISTIC_REPORT_REPLAY_MISMATCH")
        with original.open("rb") as stream:
            after_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        require(after_hash == independent["sha256"],
                "ORIGINAL_BINARY_MUTATED_DURING_AUDIT")
    after = api.json("/branches/main")
    require(after.get("commit", {}).get("sha") == source_sha,
            "CURRENT_MAIN_DRIFT_DURING_AUDIT")
    return {
        "status": "ORIGINAL_BINARY_AND_PROJECTION_VERIFIED_NOT_SOAK_PASS",
        "source_sha": source_sha,
        "state_commit": state_commit,
        "state_parent": expected_parent,
        "state_sequence": expected_sequence,
        "canonical_hash": expected_chain,
        "state_bytes_sha256": independent["sha256"],
        "state_bytes": source["raw_size"],
        "state_chunks": source["chunk_count"],
        "git_manifest_blob": source["manifest_git_blob_sha"],
        "real_provider_attempt_count": count,
        "pending_events": 0,
        "source_exact_main_verified": True,
        "original_git_sha256_verified": True,
        "canonical_event_id_verified": True,
        "immutable_ledger_replay_verified": True,
        "deterministic_report_replay_verified": True,
        "no_remote_state_writes": True,
        "automatic_origin_verified": False,
        "six_hour_soak_accepted": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only exact-Git chunked Brain binary and report replay"
    )
    parser.add_argument("--state-commit", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--expected-parent", required=True)
    parser.add_argument("--expected-sequence", type=int, required=True)
    parser.add_argument("--expected-chain", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_source_state(
            GitHubReadOnly(os.environ.get("GITHUB_TOKEN", ""), max_calls=656),
            state_commit=args.state_commit,
            source_sha=args.source_sha,
            expected_parent=args.expected_parent,
            expected_sequence=args.expected_sequence,
            expected_chain=args.expected_chain,
        )
    except (EvidenceError, BrainError, OSError, ValueError, KeyError, TypeError):
        result = {
            "status": "BLOCKED_ORIGINAL_SOURCE_NOT_VERIFIED",
            "six_hour_soak_accepted": False,
        }
    path = args.output
    if path.is_symlink() or path.exists():
        raise SystemExit("EVIDENCE_OUTPUT_EXISTS_OR_IS_SYMLINK")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (path.parent.is_symlink() or
        stat.S_IMODE(path.parent.stat().st_mode) != 0o700):
        raise SystemExit("EVIDENCE_OUTPUT_DIRECTORY_NOT_PRIVATE")
    with path.open("x", encoding="utf-8") as file:
        os.chmod(path, 0o600)
        file.write(json.dumps(result, sort_keys=True, indent=2)+"\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"].startswith("ORIGINAL_BINARY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
