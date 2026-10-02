"""Regression for bounded aggregate journal snapshots larger than one event."""
import hashlib
import io
import unittest
import zipfile
from datetime import datetime, timedelta, timezone

from dashboard.history_state import STATE_ID, replay_history_observation
from state_journal.contracts import MAX_BYTES, MAX_SNAPSHOT_BYTES, canonical
from state_journal.events import make_change, make_event
from state_journal.reducer import checkpoint, make_snapshot, validate_snapshot
from state_journal.transport import extract_json


class SnapshotCapacityRegressionTests(unittest.TestCase):
    def test_snapshot_retains_valid_replay_above_event_byte_limit(self):
        history = {
            "schema_version": "1.0.0",
            "state_id": STATE_ID,
            "sequence": 0,
            "updated_at": None,
            "points": [],
        }
        base = checkpoint({"history": history}, {"history": "fixture:history"})
        metrics = {
            "open_work": 0,
            "queued_work": 0,
            "active_work": 0,
            "completed_work_total": 0,
            "cancelled_work_total": 0,
            "cost_usd_today": 0,
            "model_calls_today": 0,
            "api_calls_today": 0,
            "github_runner_minutes_today": 0,
            "hunter_candidates_total": 0,
            "hunter_retained_total": 0,
            "action_executions_total": 0,
            "failures_total": 0,
            "verified_external_outcomes_total": 0,
        }
        project_activity = {
            f"project-{index:05d}": {"open_work": 0}
            for index in range(30_000)
        }
        state = history
        events = []
        evidence = {}
        observed = datetime(2026, 9, 29, tzinfo=timezone.utc)

        for index in range(4):
            timestamp = (observed + timedelta(hours=index)).isoformat().replace("+00:00", "Z")
            core = {
                "bucket_at": timestamp,
                "observed_at": timestamp,
                "source_commit": "a" * 40,
                "metrics": metrics,
                "project_activity": project_activity,
            }
            point = {
                "point_id": "HPT-" + hashlib.sha256(
                    canonical(core)
                ).hexdigest()[:20].upper(),
                **core,
            }
            after = replay_history_observation(state, point)
            event = make_event(
                "command-center-pages",
                str(900 + index),
                "a" * 40,
                [make_change("history", state, after)],
            )
            self.assertLess(len(canonical(event)), MAX_BYTES)
            events.append(event)
            evidence[event["event_id"]] = [{
                "kind": "FIXTURE",
                "event_hash": event["event_hash"],
                "fixture_id": "fixture:capacity-regression",
            }]
            state = after

        snapshot = make_snapshot(base, events, sequence=4, evidence=evidence)
        serialized_size = len(canonical(snapshot))
        self.assertGreater(serialized_size, MAX_BYTES)
        self.assertLess(serialized_size, MAX_SNAPSHOT_BYTES)
        validate_snapshot(snapshot)
        self.assertEqual(snapshot["projection"]["states"]["history"], state)
        self.assertEqual(snapshot["event_count"], len(events))
        for event in events:
            self.assertEqual(evidence[event["event_id"]][0]["event_hash"], event["event_hash"])
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("snapshot.json", canonical(snapshot))
        self.assertLess(len(archive.getvalue()), MAX_BYTES)
        self.assertEqual(
            extract_json(archive.getvalue(), "snapshot.json"),
            snapshot,
        )


if __name__ == "__main__":
    unittest.main()
