import json
import unittest
from pathlib import Path

from agents.heartbeat_state import seed_state
from state_journal.archive_checkpoint import (
    ARCHIVE_BRANCH,
    build_archive,
    validate_manifest,
    verify_archive,
)
from state_journal.reducer import checkpoint, make_snapshot, set_authority

ROOT=Path(__file__).resolve().parents[1]


def snapshot(sequence=7):
    base=checkpoint({"heartbeat":seed_state()},{"heartbeat":"fixture:heartbeat"})
    state=make_snapshot(base,[],sequence=sequence,evidence={})
    return set_authority(state,mode="CANONICAL",production_authority=True)


def build(state,previous=None):
    return build_archive(
        state,
        source_reducer_run_id=123,
        source_head_sha="a"*40,
        source_artifact_id=456,
        source_artifact_digest="sha256:"+"b"*64,
        source_artifact_created_at="2026-09-30T12:00:00Z",
        source_artifact_expires_at="2026-10-30T12:00:00Z",
        archived_at="2026-09-30T12:01:00Z",
        previous=previous,
    )


class ArchiveCheckpointTests(unittest.TestCase):
    def test_build_and_verify_preserve_exact_canonical_snapshot(self):
        state=snapshot()
        raw,manifest=build(state)
        restored=verify_archive(raw,manifest)
        self.assertEqual(restored,state)
        self.assertEqual(manifest["canonical_state_hash"],state["state_hash"])
        self.assertEqual(manifest["canonical_sequence"],7)
        self.assertEqual(manifest["archive_branch"],ARCHIVE_BRANCH)
        self.assertTrue(manifest["sanitized"])
        self.assertEqual(manifest["replay_scan_start"],"2026-09-30T11:30:00Z")

    def test_archive_lineage_is_hash_linked_and_monotonic(self):
        raw1,m1=build(snapshot(7))
        self.assertEqual(verify_archive(raw1,m1)["sequence"],7)
        raw2,m2=build_archive(
            snapshot(8),
            source_reducer_run_id=124,
            source_head_sha="c"*40,
            source_artifact_id=457,
            source_artifact_digest="sha256:"+"d"*64,
            source_artifact_created_at="2026-09-30T13:00:00Z",
            source_artifact_expires_at="2026-10-30T13:00:00Z",
            archived_at="2026-09-30T13:01:00Z",
            previous=m1,
        )
        validate_manifest(m2,previous=m1)
        self.assertEqual(m2["previous_manifest_hash"],m1["manifest_hash"])
        self.assertEqual(m2["previous_checkpoint_hash"],m1["checkpoint_hash"])
        self.assertEqual(m2["previous_canonical_state_hash"],m1["canonical_state_hash"])
        self.assertEqual(verify_archive(raw2,m2,previous=m1)["sequence"],8)

    def test_archive_tamper_fails_closed(self):
        raw,manifest=build(snapshot())
        damaged=bytearray(raw);damaged[-1]^=1
        with self.assertRaises(Exception):
            verify_archive(bytes(damaged),manifest)
        changed=json.loads(json.dumps(manifest))
        changed["canonical_sequence"]+=1
        with self.assertRaises(Exception):
            validate_manifest(changed)

    def test_credential_like_material_is_rejected(self):
        state=snapshot()
        state["projection"]["states"]["heartbeat"]["recent_events"].append({
            "event_id":"EVT-X","agent_id":"AGT-X","at":"2026-09-30T12:00:00Z",
            "activity_kind":"TEST","source_workflow":"test","source_run_id":"1",
            "detail":"-----BEGIN PRIVATE KEY-----"
        })
        # The domain validator may reject the synthetic state first; either way
        # unsafe archive material must never be emitted.
        with self.assertRaises(Exception):
            build(state)

    def test_archive_workflow_isolated_from_main_and_uses_digest_validation(self):
        workflow=(ROOT/".github/workflows/portfolio-state-archive.yml").read_text()
        self.assertIn('workflows: ["portfolio-state-reducer"]',workflow)
        self.assertIn("artifact_digest(meta,raw)",workflow)
        self.assertIn("archive/state-journal",workflow)
        self.assertIn("git switch --orphan archive/state-journal",workflow)
        self.assertIn("git push origin HEAD:refs/heads/archive/state-journal",workflow)
        self.assertNotIn("git push origin HEAD:refs/heads/main",workflow)
        self.assertIn("contents: write",workflow)
        self.assertIn("actions: read",workflow)


if __name__=="__main__":
    unittest.main()
