import hashlib
import io
import unittest
import zipfile

from dashboard.history_state import ARTIFACT_NAME, append_point
from state_journal.contracts import MAX_BYTES, canonical
from state_journal.events import make_change, make_event
from state_journal.reducer import checkpoint, make_snapshot
from state_journal.transport import REPO_ID, validate_artifact_publication_fallback


def telemetry(at):
    projects = {
        f"PRJ-{index:03d}": {
            "open_work": index,
            "completed_work": index * 2,
            "cancelled_work": 0,
            "sent_actions": index // 2,
            "verified_outcomes": index // 3,
        }
        for index in range(12)
    }
    return {
        "generated_at": at,
        "queue": {
            "open_total": 12,
            "counts": {"QUEUED": 12, "ACTIVE": 0, "COMPLETE": 20, "CANCELLED": 0},
            "completed_fingerprint_count": 20,
        },
        "cost": {"actual_usage_today": {
            "cost_usd": 1.25, "model_calls": 2, "api_calls": 1, "github_runner_minutes": 7,
        }},
        "hunter": {"totals": {"candidates": 10, "retained": 3}},
        "actions": {"total_sent": 1},
        "failures": {"count": 0},
        "verified_external_outcomes": 0,
        "project_activity": projects,
    }


class HistoryEventCompactionRegressionTests(unittest.TestCase):
    def test_history_event_retains_observation_without_copying_full_history_states(self):
        from datetime import datetime, timedelta, timezone

        state = {
            "schema_version": "1.0.0",
            "state_id": "portfolio-command-center-history",
            "sequence": 0,
            "updated_at": None,
            "points": [],
        }
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for hour in range(120):
            at = (start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z")
            state = append_point(state, telemetry(at), source_commit=f"{hour + 1:040x}")

        base_state = state
        events = []
        evidence = {}
        for index in range(80):
            hour = 120 + index
            at = (start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z")
            after = append_point(state, telemetry(at), source_commit=f"{hour + 1:040x}")
            change = make_change("history", state, after)
            event = make_event(
                "command-center-pages", str(101 + index), f"{index + 1:040x}", [change]
            )
            events.append(event)
            evidence[event["event_id"]] = [{
                "kind": "FIXTURE",
                "event_hash": event["event_hash"],
                "fixture_id": "fixture:history-compaction",
            }]
            state = after

        base = checkpoint({"history": base_state}, {"history": "fixture:history"})
        # A long immutable event run must stay below the same hard cap without
        # pruning observations or increasing the configured byte budget.
        snapshot = make_snapshot(base, events, sequence=len(events), evidence=evidence)
        self.assertLess(len(canonical(snapshot)), MAX_BYTES)
        self.assertEqual(snapshot["projection"]["states"]["history"], after)
        for event in events:
            change = event["changes"][0]
            self.assertEqual(change["operation"], "HISTORY_OBSERVATION")
            self.assertNotIn("before", change)
            self.assertNotIn("after", change)
            self.assertLess(len(canonical(event)), 10_000)

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("history_state.json", canonical(after))
        state_raw = stream.getvalue()
        last_event = events[-1]
        run_id = int(last_event["run_id"])
        source = {
            "id": run_id,
            "head_sha": last_event["source_sha"],
            "head_branch": "main",
            "repository_id": REPO_ID,
            "head_repository_id": REPO_ID,
        }
        state_artifact = {
            "id": 901,
            "name": ARTIFACT_NAME,
            "expired": False,
            "created_at": "2026-06-01T12:00:01Z",
            "digest": "sha256:" + hashlib.sha256(state_raw).hexdigest(),
            "workflow_run": source,
        }
        job_id = validate_artifact_publication_fallback(
            last_event,
            {"created_at": "2026-06-01T12:00:02Z"},
            {"id": run_id, "run_attempt": 1, "conclusion": "success"},
            {"total_count": 1, "jobs": [{
                "id": 902,
                "run_id": run_id,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "steps": [],
            }]},
            [state_artifact],
            {state_artifact["id"]: state_raw},
            {"command-center-pages": {"history": ARTIFACT_NAME}},
        )
        self.assertEqual(job_id, 902)


if __name__ == "__main__":
    unittest.main()
