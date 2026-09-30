import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.archive import (
    ARCHIVE_SCHEMA,
    build_rollover,
    load_active_manifest,
    validate_manifest,
)
from state_journal.contracts import JournalError, canonical, digest
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.reducer import checkpoint, make_snapshot, set_authority
from state_journal.transport import EVENT_PREFIX, UPLOAD_STEP, GitHubReader


SHA = "a" * 40


def canonical_state(sequence=5, *, base=None, events=None, evidence=None):
    base = base or checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    state = make_snapshot(
        base,
        events or [],
        sequence=sequence,
        evidence=evidence or {},
    )
    return set_authority(state, mode="CANONICAL", production_authority=True)


def event_from(before, *, run_id=301, attempt=1, at="2026-09-30T12:05:00Z"):
    after = heartbeat(
        before,
        agent_ids=["AGT-DATA-STEWARD"],
        activity_kind="RUNTIME_OBSERVATION",
        source_workflow="runtime-worker",
        source_run_id=str(run_id),
        at=at,
    )
    event = make_event(
        "runtime-worker",
        str(run_id),
        SHA,
        [make_change("heartbeat", before, after)],
        run_attempt=attempt,
    )
    evidence = {
        "kind": "FIXTURE",
        "event_hash": event["event_hash"],
        "fixture_id": "fixture:step7-lifecycle",
    }
    return event, evidence, after


def rollover(
    state,
    *,
    previous=None,
    run_id=900,
    artifact_id=901,
    created="2026-09-30T12:00:00Z",
    archived="2026-09-30T12:01:00Z",
):
    return build_rollover(
        state,
        source_reducer_run_id=run_id,
        source_artifact_id=artifact_id,
        source_head_sha="b" * 40,
        source_artifact_digest="sha256:" + "c" * 64,
        source_artifact_created_at=created,
        previous_manifest=previous,
        archive_created_at=archived,
    )


def artifact_for(event, *, artifact_id=77, created="2026-09-30T12:05:01Z", expired=False):
    return {
        "id": artifact_id,
        "name": (
            f"{EVENT_PREFIX}{event['run_id']}-{event['producer']}-"
            f"{event['source_sha']}-{event['run_attempt']}"
        ),
        "expired": expired,
        "created_at": created,
        "digest": "sha256:" + "d" * 64,
        "workflow_run": {
            "id": int(event["run_id"]),
            "head_branch": "main",
            "head_sha": event["source_sha"],
        },
    }


def producer_run(run_id, attempt=1, created="2026-09-30T12:05:00Z"):
    return {
        "id": run_id,
        "run_attempt": attempt,
        "created_at": created,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }


class CheckpointLifecycleV2Tests(unittest.TestCase):
    def test_manifest_has_content_identity_lineage_root_hash_and_replay_overlap(self):
        state = canonical_state(5)
        _archive_raw, _checkpoint_raw = None, None
        manifest, archive_raw, compacted, checkpoint_raw, archive_path = rollover(state)

        self.assertEqual(manifest["schema_version"], ARCHIVE_SCHEMA)
        self.assertEqual(
            manifest["archive_id"],
            "canonical-archive-seq-00000005-" + state["state_hash"].removeprefix("sha256:")[:16],
        )
        self.assertEqual(manifest["replay_overlap_seconds"], 1800)
        self.assertEqual(manifest["artifact_scan_start"], "2026-09-30T11:30:00Z")
        self.assertEqual(manifest["archive_created_at"], "2026-09-30T12:01:00Z")
        self.assertEqual(manifest["checkpoint_sequence"], 6)
        self.assertTrue(manifest["checkpoint_state_hash"].startswith("sha256:"))
        self.assertEqual(manifest["archived_source_run_ids"], [])
        self.assertEqual(manifest["archived_source_attempts"], [])
        self.assertTrue(archive_path.endswith(".json.gz"))
        self.assertTrue(archive_raw.startswith(b"\x1f\x8b"))
        self.assertTrue(checkpoint_raw.startswith(b"\x1f\x8b"))

        next_state = canonical_state(6, base=compacted)
        manifest2, _raw2, compacted2, _checkpoint2, _path2 = rollover(
            next_state,
            previous=manifest,
            run_id=902,
            artifact_id=903,
            created="2026-09-30T13:00:00Z",
            archived="2026-09-30T13:01:00Z",
        )
        self.assertEqual(manifest2["previous_manifest_hash"], manifest["manifest_hash"])
        self.assertEqual(manifest2["previous_manifest_path"], manifest["manifest_path"])
        self.assertEqual(manifest2["previous_archive_id"], manifest["archive_id"])
        self.assertEqual(manifest2["previous_archived_sequence"], manifest["archived_sequence"])
        self.assertEqual(manifest2["previous_archived_state_hash"], manifest["archived_state_hash"])
        self.assertEqual(manifest2["previous_checkpoint_hash"], manifest["new_checkpoint_hash"])
        validate_manifest(
            manifest2,
            root=None,
            archived_state=next_state,
            checkpoint_doc=compacted2,
            previous_manifest=manifest,
        )

    def test_old_expired_event_artifact_is_routine_when_exact_attempt_is_checkpoint_covered(self):
        reader = object.__new__(GitHubReader)
        run = producer_run(301, 2)
        calls = []

        def workflows(workflow_file, _since, *, max_pages):
            calls.append(("workflow", workflow_file, max_pages))
            if workflow_file == "portfolio-state-reducer.yml":
                return []
            self.assertEqual(workflow_file, "runtime-hourly-sync.yml")
            return [run]

        reader._workflow_runs_since = workflows
        reader._run_artifacts = lambda _run_id: []

        def no_jobs(suffix):
            self.fail("covered expired attempt must not require vanished Actions evidence: " + suffix)

        reader.get = no_jobs
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts(
                "2026-09-30T11:30:00Z",
                max_pages=1,
                covered_run_attempts={(301, 2)},
            )
        self.assertEqual(rows, [])
        self.assertEqual(len(calls), 2)

    def test_missing_required_replay_fails_closed(self):
        reader = object.__new__(GitHubReader)
        run = producer_run(302, 1)

        def workflows(workflow_file, _since, *, max_pages):
            if workflow_file == "portfolio-state-reducer.yml":
                return []
            return [run]

        reader._workflow_runs_since = workflows
        reader._run_artifacts = lambda _run_id: []

        def get(suffix):
            self.assertEqual(suffix, "/actions/runs/302/attempts/1/jobs?per_page=100")
            return {
                "total_count": 1,
                "jobs": [{
                    "steps": [{
                        "name": UPLOAD_STEP,
                        "status": "completed",
                        "conclusion": "success",
                    }]
                }],
            }

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ), self.assertRaisesRegex(JournalError, "MISSING_REPLAY"):
            reader.list_recent_journal_artifacts(
                "2026-09-30T11:30:00Z",
                max_pages=1,
            )

    def test_event_after_checkpoint_replays_from_compacted_root(self):
        archived = canonical_state(5)
        manifest, _raw, compacted, _checkpoint_raw, _path = rollover(archived)
        event, evidence, after = event_from(compacted["states"]["heartbeat"])
        meta = artifact_for(event)

        class Reader:
            def list_recent_journal_artifacts(self, *_args, **_kwargs):
                return [meta]

            def event(self, _meta, _upload_steps):
                return event, evidence

        candidate, receipt = reduce_from_provider(
            Reader(),
            since=manifest["artifact_scan_start"],
            current_run="999",
            upload_steps={},
            explicit_checkpoint=compacted,
            archive_manifest=manifest,
        )
        self.assertEqual(candidate["checkpoint"]["checkpoint_hash"], manifest["new_checkpoint_hash"])
        self.assertEqual(candidate["sequence"], 7)
        self.assertEqual(candidate["event_count"], 1)
        self.assertEqual(candidate["projection"]["states"]["heartbeat"], after)
        self.assertEqual(receipt["archive_checkpoint_status"], "VALID_CHECKPOINT")
        self.assertEqual(receipt["new_deliveries"], 1)

    def test_event_racing_checkpoint_merge_is_retained_and_reconstructs_projection(self):
        archived = canonical_state(5)
        manifest, _raw, compacted, _checkpoint_raw, _path = rollover(archived)
        event, evidence, after = event_from(
            archived["projection"]["states"]["heartbeat"],
            run_id=303,
            at="2026-09-30T11:45:00Z",
        )
        race_state = canonical_state(
            6,
            base=archived["checkpoint"],
            events=[event],
            evidence={event["event_id"]: [evidence]},
        )
        meta = artifact_for(event, artifact_id=78, created="2026-09-30T11:45:01Z")

        class Reader:
            def list_recent_journal_artifacts(self, since, **_kwargs):
                self_since = since
                if self_since != "2026-09-30T11:30:00Z":
                    raise AssertionError("checkpoint overlap boundary not used")
                return [meta]

            def event(self, _meta, _upload_steps):
                return event, evidence

        with patch("state_journal.github_reducer.restore_snapshot", return_value=race_state):
            candidate, receipt = reduce_from_provider(
                Reader(),
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )

        self.assertTrue(receipt["checkpoint_rollover"])
        self.assertEqual(candidate["checkpoint"]["checkpoint_hash"], manifest["new_checkpoint_hash"])
        self.assertEqual(candidate["projection"]["projection_hash"], race_state["projection"]["projection_hash"])
        self.assertEqual(candidate["projection"]["states"]["heartbeat"], after)

    def test_incomplete_premerge_replay_is_distinct_and_fails_closed(self):
        archived = canonical_state(5)
        manifest, _raw, compacted, _checkpoint_raw, _path = rollover(archived)
        event, evidence, _after = event_from(
            archived["projection"]["states"]["heartbeat"],
            run_id=304,
            at="2026-09-30T11:46:00Z",
        )
        race_state = canonical_state(
            6,
            base=archived["checkpoint"],
            events=[event],
            evidence={event["event_id"]: [evidence]},
        )

        class Reader:
            def list_recent_journal_artifacts(self, *_args, **_kwargs):
                return []

        with patch("state_journal.github_reducer.restore_snapshot", return_value=race_state), \
             self.assertRaisesRegex(JournalError, "INCOMPLETE_REPLAY"):
            reduce_from_provider(
                Reader(),
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )

    def test_unconsumed_expired_evidence_is_distinct_and_fails_closed(self):
        archived = canonical_state(5)
        manifest, _raw, compacted, _checkpoint_raw, _path = rollover(archived)
        event, _evidence, _after = event_from(compacted["states"]["heartbeat"], run_id=305)
        meta = artifact_for(event, artifact_id=79, expired=True)

        class Reader:
            def list_recent_journal_artifacts(self, *_args, **_kwargs):
                return [meta]

        with self.assertRaisesRegex(JournalError, "EXPIRED_EVIDENCE"):
            reduce_from_provider(
                Reader(),
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )

    def test_corrupted_checkpoint_hash_is_classified_and_fails_closed(self):
        state = canonical_state(5)
        manifest, archive_raw, _compacted, checkpoint_raw, archive_path = rollover(state)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state_journal/archive").mkdir(parents=True)
            (root / archive_path).write_bytes(archive_raw)
            (root / manifest["manifest_path"]).write_bytes(canonical(manifest) + b"\n")
            (root / "state_journal/ARCHIVE_MANIFEST.json").write_bytes(canonical(manifest) + b"\n")

            checkpoint_doc = json.loads(gzip.decompress(checkpoint_raw))
            checkpoint_doc["checkpoint_hash"] = "sha256:" + "0" * 64
            (root / "state_journal/CHECKPOINT.json.gz").write_bytes(
                gzip.compress(canonical(checkpoint_doc) + b"\n", compresslevel=9, mtime=0)
            )
            with self.assertRaisesRegex(JournalError, "CORRUPTED_CHECKPOINT"):
                load_active_manifest(root)

    def test_checkpoint_sequence_regression_fails(self):
        first = canonical_state(5)
        manifest, _raw, compacted, _checkpoint_raw, _path = rollover(first)
        regressed = canonical_state(5, base=compacted)
        with self.assertRaisesRegex(JournalError, "CHECKPOINT_SEQUENCE_REGRESSION"):
            rollover(
                regressed,
                previous=manifest,
                run_id=910,
                artifact_id=911,
                created="2026-09-30T13:00:00Z",
                archived="2026-09-30T13:01:00Z",
            )

    def test_mismatched_predecessor_hash_fails(self):
        first = canonical_state(5)
        manifest, _raw, compacted, _checkpoint_raw, _path = rollover(first)
        second = canonical_state(6, base=compacted)
        manifest2, _raw2, compacted2, _checkpoint2, _path2 = rollover(
            second,
            previous=manifest,
            run_id=912,
            artifact_id=913,
            created="2026-09-30T13:00:00Z",
            archived="2026-09-30T13:01:00Z",
        )
        changed = copy.deepcopy(manifest2)
        changed["previous_manifest_hash"] = "sha256:" + "e" * 64
        changed["manifest_hash"] = digest({k: v for k, v in changed.items() if k != "manifest_hash"})
        with self.assertRaisesRegex(JournalError, "CONFLICTING_LINEAGE"):
            validate_manifest(
                changed,
                root=None,
                archived_state=second,
                checkpoint_doc=compacted2,
                previous_manifest=manifest,
            )

    def test_conflicting_checkpoint_lineage_fails(self):
        first = canonical_state(5)
        manifest, _raw, _compacted, _checkpoint_raw, _path = rollover(first)
        unrelated = checkpoint(
            {"heartbeat": seed_state()},
            {"heartbeat": "fixture:unrelated-root"},
        )
        conflicting = canonical_state(6, base=unrelated)
        with self.assertRaisesRegex(JournalError, "CONFLICTING_LINEAGE"):
            rollover(
                conflicting,
                previous=manifest,
                run_id=914,
                artifact_id=915,
                created="2026-09-30T13:00:00Z",
                archived="2026-09-30T13:01:00Z",
            )

    def test_checkpoint_cannot_silently_change_root_state(self):
        archived = canonical_state(5)
        manifest, _raw, compacted, _checkpoint_raw, _path = rollover(archived)
        changed_heartbeat = heartbeat(
            compacted["states"]["heartbeat"],
            agent_ids=["AGT-DATA-STEWARD"],
            activity_kind="TEST",
            source_workflow="fixture",
            source_run_id="root-change",
            at="2026-09-30T12:10:00Z",
        )
        changed_checkpoint = checkpoint(
            {"heartbeat": changed_heartbeat},
            compacted["source_refs"],
        )
        with self.assertRaisesRegex(
            JournalError,
            "Compacted checkpoint hash mismatch|Compacted checkpoint state differs",
        ):
            validate_manifest(
                manifest,
                root=None,
                archived_state=archived,
                checkpoint_doc=changed_checkpoint,
            )

    def test_bounded_discovery_never_enumerates_repository_wide_artifacts(self):
        reader = object.__new__(GitHubReader)
        calls = []
        run = producer_run(306, 1)

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run]}
            if suffix == "/actions/runs/306/artifacts?per_page=100":
                return {"total_count": 0, "artifacts": []}
            raise AssertionError("unexpected request " + suffix)

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts(
                "2026-09-30T11:30:00Z",
                max_pages=1,
                covered_run_attempts={(306, 1)},
            )
        self.assertEqual(rows, [])
        self.assertLessEqual(len(calls), 3)
        self.assertFalse(any(call.startswith("/actions/artifacts?") for call in calls))


if __name__ == "__main__":
    unittest.main()
