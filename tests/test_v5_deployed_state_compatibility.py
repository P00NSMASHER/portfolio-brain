"""Networked, read-only replay of the CURRENT deployed source and durable state.

This is independent Foundation source/state compatibility evidence, not a
scheduled core, release authorization, soak or production-state mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from brain.core import Store, utcnow
from test_v5_live_state_compatibility import (
    PRODUCTION, STATE_REF, git, physical_ledger_snapshot,
)

V4_ACCEPTANCE_SHA = "b1b9f63dc8136f259abdc1b9ad18fcd47cf3b681"



def _original_state_at_commit(commit):
    """Read exact Git objects, including a sharded future branch, without writes.

    Fetches only a depth-one state ref. Every raw Git blob is independently
    hashed before the archived SQLite bytes are passed to application code.
    """
    names = set(git("ls-tree", "--name-only", commit).splitlines())
    legacy = "state.sqlite" in names
    archived = "state-manifest.json" in names
    if legacy == archived:
        raise AssertionError("State branch must have exactly one storage format")
    if legacy:
        blob = git("rev-parse", f"{commit}:state.sqlite")
        raw = git("show", f"{commit}:state.sqlite", raw=True)
        expected = hashlib.sha1(b"blob " + str(len(raw)).encode()
                                + b"\x00" + raw).hexdigest()
        if blob != expected or not raw.startswith(b"SQLite format 3\x00"):
            raise AssertionError("Original legacy Git blob identity mismatch")
        return raw, blob, "legacy_sqlite", None

    from brain.state_archive import _read_manifest, restore
    import re
    manifest_blob = git("rev-parse", f"{commit}:state-manifest.json")
    document = git("show", f"{commit}:state-manifest.json", raw=True)
    expected = hashlib.sha1(b"blob " + str(len(document)).encode()
                            + b"\x00" + document).hexdigest()
    if manifest_blob != expected:
        raise AssertionError("Original manifest Git blob identity mismatch")
    with tempfile.TemporaryDirectory(prefix="brain-original-archive-") as tmp:
        folder = Path(tmp)
        (folder / "state-manifest.json").write_bytes(document)
        verified = _read_manifest(folder)
        chunks = folder / "state-chunks"
        chunks.mkdir()
        for item in verified["chunks"]:
            name = item["name"]
            if not re.fullmatch(r"part-[0-9]{6}\.z", name):
                raise AssertionError("Unsafe original chunk name")
            path = f"state-chunks/{name}"
            oid = git("rev-parse", f"{commit}:{path}")
            value = git("show", f"{commit}:{path}", raw=True)
            actual = hashlib.sha1(b"blob " + str(len(value)).encode()
                                  + b"\x00" + value).hexdigest()
            if oid != actual:
                raise AssertionError("Original Git chunk identity mismatch")
            (chunks / name).write_bytes(value)
        restored = restore(folder)
        if restored["raw_sha256"] != verified["raw_sha256"]:
            raise AssertionError("Original decompressed database mismatch")
        raw = (folder / "state.sqlite").read_bytes()
    return raw, None, "sqlite-zlib-chunks-v1", manifest_blob


class DeployedV5ReadOnlyProof(unittest.TestCase):
    def test_current_source_and_sqlite_replay_without_production_writes(self):
        if os.environ.get("GITHUB_ACTIONS") != "true":
            self.skipTest("OFFLINE: only Foundation CI can retrieve original state")
        trigger = os.environ.get("GITHUB_EVENT_NAME")
        if trigger not in {"push", "pull_request"}:
            self.skipTest("Only protected pushes and reviewed PR candidates")
        main = git("ls-remote", "origin", "refs/heads/main").split()[0]
        self.assertRegex(main, r"^[0-9a-f]{40}$")
        if main == PRODUCTION:
            self.skipTest("V4 prepromotion proof covers this source")
        self.assertEqual(
            git("ls-remote", "origin", "refs/heads/brain-acceptance-v4").split()[0],
            V4_ACCEPTANCE_SHA, "Historical V4 acceptance ref was changed",
        )
        checkout = git("rev-parse", "HEAD")
        source = checkout
        branch_ref = None
        if trigger == "push":
            self.assertEqual(checkout, main, "Push checkout is not deployed main")
        else:
            head_name = os.environ.get("GITHUB_HEAD_REF", "")
            self.assertRegex(head_name, r"^[a-zA-Z0-9_./-]+$")
            self.assertNotIn("..", head_name)
            branch_ref = "refs/heads/" + head_name
            expected_head = git("ls-remote", "origin", branch_ref).split()[0]
            self.assertRegex(expected_head, r"^[0-9a-f]{40}$")
            git("fetch", "--quiet", "--no-tags", "origin", branch_ref)
            source = git("rev-parse", "FETCH_HEAD")
            self.assertEqual(source, expected_head, "Reviewed head drift")
            self.assertEqual(git("rev-parse", "HEAD^{tree}"),
                             git("rev-parse", f"{source}^{{tree}}"),
                             "CI checkout tree differs from reviewed candidate")
            if checkout != source:
                parents = [
                    line[7:] for line in git("cat-file", "-p", "HEAD").splitlines()
                    if line.startswith("parent ")
                ]
                self.assertEqual(parents, [main, source],
                                 "Virtual merge parent identities are wrong")

        # The earlier full-history fetch timed out against years of large
        # state-branch blobs. A pinned shallow tip includes the entire exact
        # current tree/blob identity without downloading the full history.
        state_remote = git("ls-remote", "origin", STATE_REF).split()[0]
        git("fetch", "--quiet", "--no-tags", "--depth=1", "origin", STATE_REF)
        state_commit = git("rev-parse", "FETCH_HEAD")
        self.assertEqual(state_commit, state_remote, "State head drift on fetch")
        raw, blob, storage_format, manifest_blob = _original_state_at_commit(
            state_commit
        )
        self.assertTrue(raw.startswith(b"SQLite format 3\x00"))
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        self.assertEqual(git("ls-remote", "origin", STATE_REF).split()[0],
                         state_commit, "State branch drift during immutable replay")
        self.assertEqual(git("ls-remote", "origin", "refs/heads/main").split()[0],
                         main, "Main drift during snapshot")
        if branch_ref is not None:
            self.assertEqual(git("ls-remote", "origin", branch_ref).split()[0],
                             source, "Candidate drift during snapshot")

        with tempfile.TemporaryDirectory(prefix="v5-deployed-readonly-") as temp:
            original = Path(temp) / "original.sqlite"
            original.write_bytes(raw)
            os.chmod(original, 0o400)
            # Source and state advance independently. A docs/tests-only merge
            # may precede its first genuine new-source scheduled core.
            # Require a canonical last-report source that is current main
            # or an actual ancestor; never invent a completed current cycle.
            with sqlite3.connect(
                original.as_uri() + "?mode=ro&immutable=1", uri=True
            ) as evidence:
                latest = evidence.execute(
                    "SELECT source_sha FROM reports ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertIsNotNone(latest, "State report evidence unavailable")
            recorded_source = latest[0]
            self.assertRegex(recorded_source, r"^[0-9a-f]{40}$")
            if recorded_source != main:
                if git("rev-parse", "--is-shallow-repository") == "true":
                    git("fetch", "--quiet", "--no-tags", "--deepen=16",
                        "origin", "refs/heads/main")
                ancestry = subprocess.run(
                    ["git", "merge-base", "--is-ancestor",
                     recorded_source, main],
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(
                    ancestry.returncode, 0,
                    "Stored report source not a verified protected-main "
                    "ancestor (or history too shallow): fail closed",
                )
                self.assertEqual(
                    git("ls-remote", "origin", "refs/heads/main").split()[0],
                    main, "Main drift during ancestry check",
                )
            before = physical_ledger_snapshot(
                original, expected_source=recorded_source
            )
            self.assertGreater(before["sequence"], 210)
            # Real source-bound, OFFLINE and READ-ONLY migration rehearsal.
            # The genuine immutable state is copied into disposable storage;
            # compress/restore can NEVER mutate the remote state branch.
            from brain.state_archive import CHUNK_BYTES, FORMAT, pack, restore
            shadow_dir = Path(temp) / "chunked-migration-proof"
            shadow_dir.mkdir()
            shutil.copyfile(original, shadow_dir / "state.sqlite")
            transport = pack(shadow_dir)
            self.assertEqual(transport["raw_sha256"], raw_sha256)
            self.assertEqual(transport["raw_size"], len(raw))
            self.assertFalse((shadow_dir / "state.sqlite").exists())
            self.assertGreaterEqual(transport["chunks"], 1)
            self.assertTrue(all(
                p.stat().st_size <= CHUNK_BYTES + 32768
                for p in (shadow_dir / "state-chunks").iterdir()
            ))
            restored = restore(shadow_dir)
            self.assertEqual(restored["storage_format"], FORMAT)
            self.assertEqual(restored["raw_sha256"], raw_sha256)
            self.assertEqual(
                physical_ledger_snapshot(
                    shadow_dir / "state.sqlite", expected_source=recorded_source
                ), before, "Real immutable ledger changed across chunk migration"
            )
            disposable = Path(temp) / "analysis-copy.sqlite"
            shutil.copyfile(original, disposable)
            os.chmod(disposable, 0o600)
            store = Store(disposable, visibility="PUBLIC")
            try:
                events, seq, chain = store._verified_events()
                self.assertEqual((seq, chain),
                                 (before["sequence"], before["canonical_hash"]))
                attempts = store.db.execute(
                    "SELECT count(*) FROM attempts").fetchone()[0]
                last = store.db.execute(
                    "SELECT hash,source_sha FROM reports ORDER BY id DESC LIMIT 1"
                ).fetchone()
                when = utcnow()
                result = store.report(source, now=when)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["source_sha"], source)
                self.assertEqual(result["state_sequence"], seq)
                self.assertEqual(result["canonical_hash"], chain)
                self.assertEqual(result["pending_events"], 0)
                self.assertEqual(store.read_report(source, now=when), result)
                self.assertEqual(store.db.execute(
                    "SELECT count(*) FROM events").fetchone()[0], len(events))
                self.assertEqual(store.db.execute(
                    "SELECT count(*) FROM attempts").fetchone()[0], attempts)
                prior = store.db.execute(
                    "SELECT hash,source_sha FROM reports "
                    "ORDER BY id DESC LIMIT 1 OFFSET 1").fetchone()
                self.assertEqual(tuple(prior), tuple(last))
            finally:
                store.close()
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),
                             raw_sha256, "Immutable original was modified")
            self.assertEqual(
                physical_ledger_snapshot(original, expected_source=recorded_source),
                before, "Canonical original changed"
            )
        print("POST_V5_SOURCE_STATE_RECEIPT=" + json.dumps({
            "status": "PASS_READONLY_COMPATIBILITY_NOT_ACCEPTANCE",
            "trigger": trigger, "reviewed_source": source,
            "protected_main": main, "state_commit": state_commit,
            "sqlite_blob": blob, "manifest_blob": manifest_blob,
            "storage_format": storage_format, "sqlite_sha256": raw_sha256,
            "sqlite_bytes": len(raw), "sequence": before["sequence"],
            "canonical_hash": before["canonical_hash"],
            "pending_events": 0, "v4_acceptance_ref_intact": True,
            "recorded_state_source": recorded_source,
            "recorded_source_is_protected_main": recorded_source == main,
            "pending_current_source_core_if_ancestor": recorded_source != main,
            "chunked_migration_shadow_verified": True,
            "chunked_migration_shadow_parts": transport["chunks"],
            "production_writes": 0, "scheduled_acceptance": False,
        }, sort_keys=True))
