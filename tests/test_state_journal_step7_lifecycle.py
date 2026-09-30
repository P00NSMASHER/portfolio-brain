import copy
import gzip
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agents.heartbeat_state import seed_state
from state_journal.archive import (
    REPLAY_OVERLAP_MINUTES,
    build_rollover,
    load_active_archive,
    validate_manifest,
)
from state_journal.contracts import JournalError, canonical, digest
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.production_reader import (
    _assert_no_expired_unconsumed,
    restore_domain,
)
from state_journal.reducer import advance, checkpoint, make_snapshot, set_authority
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, UPLOAD_STEP, GitHubReader
from test_state_journal import SHA, fixture_evidence, tick


def canonical_state(sequence=5, *, base=None):
    base = base or checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    state = make_snapshot(base, [], sequence=sequence, evidence={})
    return set_authority(state, mode="CANONICAL", production_authority=True)


def build(sequence=5, *, base=None, previous=None, created="2026-09-30T13:17:34Z"):
    return build_rollover(
        canonical_state(sequence, base=base),
        source_reducer_run_id=900 + sequence,
        source_artifact_id=1900 + sequence,
        source_head_sha="a" * 40,
        source_artifact_digest="sha256:" + "b" * 64,
        source_artifact_created_at=created,
        previous_manifest=previous,
        archived_at="2026-09-30T13:18:00Z",
    )


def write_archive(root: Path, manifest: dict, archive_raw: bytes, checkpoint_raw: bytes) -> None:
    (root / "state_journal/archive").mkdir(parents=True, exist_ok=True)
    (root / manifest["archive_path"]).write_bytes(archive_raw)
    (root / manifest["manifest_path"]).write_bytes(canonical(manifest) + b"\n")
    (root / "state_journal/ARCHIVE_MANIFEST.json").write_bytes(canonical(manifest) + b"\n")
    (root / "state_journal/CHECKPOINT.json.gz").write_bytes(checkpoint_raw)


def recalc_manifest(manifest: dict) -> dict:
    changed = copy.deepcopy(manifest)
    core = {key: value for key, value in changed.items() if key != "manifest_hash"}
    changed["manifest_hash"] = digest(core)
    return changed


def run(run_id, created_at="2026-09-30T13:12:00Z"):
    return {
        "id": run_id,
        "created_at": created_at,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }


def event_artifact(run_id=301, created_at="2026-09-30T13:19:00Z", *, expired=False):
    return {
        "id": 77,
        "name": EVENT_PREFIX + f"{run_id}-runtime-worker-" + SHA + "-1",
        "created_at": created_at,
        "expired": expired,
        "digest": "sha256:" + "c" * 64,
        "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": SHA},
    }


class Step7LifecycleAcceptanceTests(unittest.TestCase):
    def test_checkpoint_identity_timestamp_and_replay_overlap_are_explicit(self):
        manifest, _raw, _cp, _cpraw, _path = build()
        self.assertEqual(manifest["schema_version"], "1.1.0")
        self.assertIn(manifest["archived_state_hash"].split(":", 1)[1][:16], manifest["archive_id"])
        source = datetime.fromisoformat(manifest["source_artifact_created_at"].replace("Z", "+00:00"))
        scan = datetime.fromisoformat(manifest["artifact_scan_start"].replace("Z", "+00:00"))
        archived = datetime.fromisoformat(manifest["archived_at"].replace("Z", "+00:00"))
        self.assertEqual(source - scan, timedelta(minutes=REPLAY_OVERLAP_MINUTES))
        self.assertGreaterEqual(archived, source)
        self.assertEqual(manifest["replay_overlap_minutes"], REPLAY_OVERLAP_MINUTES)

    def test_second_checkpoint_records_and_validates_exact_predecessor_lineage(self):
        first, first_raw, first_cp, _first_cpraw, _ = build()
        second_state = canonical_state(first["checkpoint_sequence"], base=first_cp)
        second, second_raw, second_cp, second_cpraw, _ = build_rollover(
            second_state,
            source_reducer_run_id=999,
            source_artifact_id=1999,
            source_head_sha="d" * 40,
            source_artifact_digest="sha256:" + "e" * 64,
            source_artifact_created_at="2026-09-30T13:40:00Z",
            previous_manifest=first,
            archived_at="2026-09-30T13:41:00Z",
        )
        self.assertEqual(second["previous_manifest_hash"], first["manifest_hash"])
        self.assertEqual(second["previous_archive_id"], first["archive_id"])
        self.assertEqual(second["previous_archived_sequence"], first["archived_sequence"])
        self.assertEqual(second["previous_archived_state_hash"], first["archived_state_hash"])
        self.assertEqual(second["previous_new_checkpoint_hash"], first["new_checkpoint_hash"])
        self.assertEqual(second["archived_checkpoint_hash"], first["new_checkpoint_hash"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state_journal/archive").mkdir(parents=True)
            (root / first["archive_path"]).write_bytes(first_raw)
            (root / first["manifest_path"]).write_bytes(canonical(first) + b"\n")
            write_archive(root, second, second_raw, second_cpraw)
            archived_state, checkpoint_doc = validate_manifest(second, root=root)
            self.assertEqual(archived_state["state_hash"], second["archived_state_hash"])
            self.assertEqual(checkpoint_doc["checkpoint_hash"], second_cp["checkpoint_hash"])

    def test_checkpoint_sequence_regression_fails(self):
        first, _raw, first_cp, _cpraw, _ = build(sequence=5)
        regressed = canonical_state(sequence=5, base=first_cp)
        with self.assertRaisesRegex(JournalError, "sequence regression"):
            build_rollover(
                regressed,
                source_reducer_run_id=999,
                source_artifact_id=1999,
                source_head_sha="d" * 40,
                source_artifact_digest="sha256:" + "e" * 64,
                source_artifact_created_at="2026-09-30T13:40:00Z",
                previous_manifest=first,
                archived_at="2026-09-30T13:41:00Z",
            )

    def test_mismatched_predecessor_hash_fails_closed(self):
        first, first_raw, first_cp, _first_cpraw, _ = build()
        second_state = canonical_state(first["checkpoint_sequence"], base=first_cp)
        second, second_raw, _second_cp, second_cpraw, _ = build_rollover(
            second_state,
            source_reducer_run_id=999,
            source_artifact_id=1999,
            source_head_sha="d" * 40,
            source_artifact_digest="sha256:" + "e" * 64,
            source_artifact_created_at="2026-09-30T13:40:00Z",
            previous_manifest=first,
            archived_at="2026-09-30T13:41:00Z",
        )
        second["previous_manifest_hash"] = "sha256:" + "0" * 64
        second = recalc_manifest(second)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state_journal/archive").mkdir(parents=True)
            (root / first["archive_path"]).write_bytes(first_raw)
            (root / first["manifest_path"]).write_bytes(canonical(first) + b"\n")
            write_archive(root, second, second_raw, second_cpraw)
            with self.assertRaisesRegex(JournalError, "Mismatched predecessor manifest hash"):
                validate_manifest(second, root=root)

    def test_conflicting_checkpoint_lineage_fails_closed(self):
        first, first_raw, first_cp, _first_cpraw, _ = build()
        second_state = canonical_state(first["checkpoint_sequence"], base=first_cp)
        second, second_raw, _second_cp, second_cpraw, _ = build_rollover(
            second_state,
            source_reducer_run_id=999,
            source_artifact_id=1999,
            source_head_sha="d" * 40,
            source_artifact_digest="sha256:" + "e" * 64,
            source_artifact_created_at="2026-09-30T13:40:00Z",
            previous_manifest=first,
            archived_at="2026-09-30T13:41:00Z",
        )
        second["previous_archive_id"] = "conflicting-archive"
        second = recalc_manifest(second)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state_journal/archive").mkdir(parents=True)
            (root / first["archive_path"]).write_bytes(first_raw)
            (root / first["manifest_path"]).write_bytes(canonical(first) + b"\n")
            write_archive(root, second, second_raw, second_cpraw)
            with self.assertRaisesRegex(JournalError, "Conflicting checkpoint lineage archive identity"):
                validate_manifest(second, root=root)

    def test_checkpoint_cannot_silently_change_root_state(self):
        first, _raw, _first_cp, _cpraw, _ = build()
        unrelated = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:other-root"})
        wrong = canonical_state(first["checkpoint_sequence"], base=unrelated)
        with self.assertRaisesRegex(JournalError, "Mismatched predecessor checkpoint hash"):
            build_rollover(
                wrong,
                source_reducer_run_id=999,
                source_artifact_id=1999,
                source_head_sha="d" * 40,
                source_artifact_digest="sha256:" + "e" * 64,
                source_artifact_created_at="2026-09-30T13:40:00Z",
                previous_manifest=first,
                archived_at="2026-09-30T13:41:00Z",
            )

    def test_corrupted_checkpoint_hash_fails_closed(self):
        manifest, archive_raw, checkpoint_doc, _checkpoint_raw, _ = build()
        damaged = copy.deepcopy(checkpoint_doc)
        damaged["checkpoint_hash"] = "sha256:" + "0" * 64
        damaged_raw = gzip.compress(canonical(damaged) + b"\n", compresslevel=9, mtime=0)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_archive(root, manifest, archive_raw, damaged_raw)
            with self.assertRaises(JournalError):
                load_active_archive(root)

    def test_event_after_checkpoint_replays_to_exact_expected_canonical_state(self):
        archived = canonical_state(sequence=5)
        manifest, _raw, compacted, _cpraw, _path = build_rollover(
            archived,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="a" * 40,
            source_artifact_digest="sha256:" + "b" * 64,
            source_artifact_created_at="2026-09-30T13:17:34Z",
            archived_at="2026-09-30T13:18:00Z",
        )
        before = seed_state()
        after = tick(before, run="301", at="2026-09-30T13:19:00Z")
        event = make_event("runtime-worker", "301", SHA, [make_change("heartbeat", before, after)])
        provider = fixture_evidence(event)
        artifact = event_artifact()

        class Reader:
            def list_recent_journal_artifacts(self, *args, **kwargs):
                return [artifact]
            def event(self, *args, **kwargs):
                return event, provider

        candidate, receipt = reduce_from_provider(
            Reader(),
            since=manifest["artifact_scan_start"],
            current_run="999",
            upload_steps={},
            explicit_checkpoint=compacted,
            archive_manifest=manifest,
            archive_state=archived,
        )
        expected_base = make_snapshot(
            compacted, [], sequence=manifest["checkpoint_sequence"], evidence={}
        )
        expected = advance(expected_base, [(event, provider)])
        self.assertEqual(candidate["state_hash"], expected["state_hash"])
        self.assertEqual(candidate["projection"], expected["projection"])
        self.assertEqual(receipt["new_deliveries"], 1)

    def test_event_racing_checkpoint_publication_is_inside_retained_overlap(self):
        manifest, _raw, _cp, _cpraw, _path = build(created="2026-09-30T13:17:34Z")
        reader = object.__new__(GitHubReader)
        artifact = event_artifact(created_at="2026-09-30T13:18:00Z")
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run(301, "2026-09-30T13:12:00Z")]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [artifact]}
            raise AssertionError("unexpected request " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts(manifest["artifact_scan_start"])
        self.assertEqual([row["id"] for row in rows], [77])
        self.assertLess(
            datetime.fromisoformat(manifest["artifact_scan_start"].replace("Z", "+00:00")),
            datetime.fromisoformat(manifest["source_artifact_created_at"].replace("Z", "+00:00")),
        )

    def test_old_event_artifact_may_expire_only_when_checkpoint_covers_its_run(self):
        reader = object.__new__(GitHubReader)
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run(301)]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 0, "artifacts": []}
            raise AssertionError("covered run should not require job archaeology: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts(
                "2026-09-30T12:47:34Z", covered_run_ids={301}
            )
        self.assertEqual(rows, [])
        self.assertFalse(any(suffix == "/actions/runs/301/jobs?per_page=100" for suffix in calls))

    def test_missing_required_replay_fails_closed(self):
        reader = object.__new__(GitHubReader)

        def get(suffix):
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run(302)]}
            if suffix == "/actions/runs/302/artifacts?per_page=100":
                return {"total_count": 0, "artifacts": []}
            if suffix == "/actions/runs/302/jobs?per_page=100":
                return {
                    "total_count": 1,
                    "jobs": [{"steps": [
                        {"name": UPLOAD_STEP, "status": "completed", "conclusion": "success"}
                    ]}],
                }
            raise AssertionError("unexpected request " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}), \
             self.assertRaisesRegex(JournalError, "MISSING_REPLAY"):
            reader.list_recent_journal_artifacts("2026-09-30T12:47:34Z")

    def test_expired_unconsumed_evidence_is_distinct_and_fails_closed(self):
        with self.assertRaisesRegex(JournalError, "EXPIRED_EVIDENCE"):
            _assert_no_expired_unconsumed(
                canonical_state(), [event_artifact(expired=True)], archived_ids=set()
            )

    def test_production_reader_restores_validated_repo_archive_when_actions_snapshot_is_missing(self):
        archived = canonical_state(sequence=5)
        manifest, _raw, compacted, _cpraw, _path = build_rollover(
            archived,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="a" * 40,
            source_artifact_digest="sha256:" + "b" * 64,
            source_artifact_created_at="2026-09-30T13:17:34Z",
            archived_at="2026-09-30T13:18:00Z",
        )

        class EmptyReader:
            def list_recent_artifacts(self, *args, **kwargs):
                return []

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "heartbeat.json"
            metadata = root / "meta.json"
            cache = root / "cache.json"
            with patch.dict(os.environ, {
                "GITHUB_TOKEN": "token",
                "GITHUB_RUN_ID": "999",
                "PORTFOLIO_CANONICAL_CACHE": str(cache),
            }, clear=False), \
                 patch("state_journal.production_reader.load_active_archive",
                       return_value=(manifest, archived, compacted)), \
                 patch("state_journal.production_reader.GitHubReader", return_value=EmptyReader()), \
                 patch("state_journal.production_reader.restore_snapshot", return_value=None):
                status = restore_domain("heartbeat", output, metadata)
            self.assertEqual(status, "RESTORED_CANONICAL_DURABLE_ARCHIVE")
            self.assertEqual(json.loads(output.read_text()), seed_state())
            meta = json.loads(metadata.read_text())
            self.assertEqual(meta["canonical_state_hash"], archived["state_hash"])
            self.assertEqual(meta["source_run_id"], manifest["source_reducer_run_id"])


if __name__ == "__main__":
    unittest.main()
