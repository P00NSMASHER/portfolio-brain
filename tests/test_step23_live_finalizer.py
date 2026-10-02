import unittest

from acceptance.final_acceptance import validate_step23
from acceptance.step23_finalize import Step23FinalizeError, build_receipt
from acceptance.step23_live_collect import (
    Step23CollectError,
    _claim_window,
    _classify_runs,
    _pending_count,
)


SHA = "a" * 40
H = "sha256:" + "b" * 64

WORKFLOWS = [
    "portfolio-state-reducer",
    "runtime-hourly-sync",
    "portfolio-autonomous-scheduler",
    "hunter-autonomous-cycle",
    "agent-heartbeat-sweep",
    "portfolio-cost-watchdog",
    "portfolio-notification-cycle",
    "command-center-pages",
]


def success_run(workflow, run_id, minute):
    return {
        "workflow": workflow,
        "event": "schedule",
        "classification": "SUCCESS",
        "classification_reason": "COMPLETED_SUCCESSFULLY",
        "conclusion": "success",
        "created_at": f"2026-10-02T00:{minute:02d}:00Z",
        "completed_at": f"2026-10-02T00:{minute:02d}:30Z",
        "superseding_run_id": None,
        "run_id": run_id,
        "head_sha": SHA,
        "artifact_hash": H,
    }


def valid_meta():
    runs = []
    run_id = 100
    for workflow in WORKFLOWS:
        for minute in (1, 11, 21):
            runs.append(success_run(workflow, run_id, minute))
            run_id += 1

    reducer_ids = [
        row["run_id"] for row in runs
        if row["workflow"] == "portfolio-state-reducer"
    ]
    scheduler_ids = [
        row["run_id"] for row in runs
        if row["workflow"] == "portfolio-autonomous-scheduler"
    ]
    hunter_id = next(
        row["run_id"] for row in runs
        if row["workflow"] == "hunter-autonomous-cycle"
    )

    return {
        "schema_version": "1.0.0",
        "exact_main_sha": SHA,
        "hash_traceability_pass": True,
        "dashboard": {
            "fresh": True,
            "hash": H,
            "run_id": 999,
            "completed_at": "2026-10-02T00:30:00Z",
            "artifact_name": "portfolio-command-center-history",
        },
        "runs": runs,
        "canonical_samples": [
            {
                "run_id": reducer_ids[index],
                "observed_at": f"2026-10-02T00:{30 + index:02d}:00Z",
                "sequence": 10 + index,
                "state_hash": H,
                "source_sha": SHA,
            }
            for index in range(3)
        ],
        "pending_events_start": 3,
        "pending_events_final": 0,
        "handler_execution_evidence": [
            {
                "kind": kind,
                "status": "COMPLETED",
                "run_id": scheduler_ids[index],
                "execution_id": f"execution-{kind.lower()}-1",
                "head_sha": SHA,
                "artifact_hash": H,
            }
            for index, kind in enumerate(("REPAIR", "TEST", "VERIFICATION"))
        ],
        "hunter_substantive_work_evidence": [
            {
                "run_id": hunter_id,
                "work_id": "hunt-controlled-1",
                "substantive": True,
                "heartbeat_only": False,
                "head_sha": SHA,
                "artifact_hash": H,
            }
        ],
    }


class FakeGH:
    def __init__(self, artifacts=None):
        self.artifacts = artifacts or {}

    def get(self, path):
        run_id = int(path.split("/")[3])
        return {"artifacts": self.artifacts.get(run_id, [])}


class Step23FinalizerTests(unittest.TestCase):
    def test_build_receipt_passes_existing_step23_validator(self):
        receipt = build_receipt(valid_meta())
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["handler_execution_counts"], {
            "REPAIR": 1,
            "TEST": 1,
            "VERIFICATION": 1,
        })
        self.assertEqual(receipt["hunter_substantive_work_count"], 1)
        validate_step23(receipt)

    def test_build_receipt_fails_closed_when_pending_work_remains(self):
        meta = valid_meta()
        meta["pending_events_final"] = 1
        with self.assertRaisesRegex(Step23FinalizeError, "pending events did not drain"):
            build_receipt(meta)

    def test_claim_window_waits_for_three_successes_per_workflow(self):
        rows = []
        run_id = 1
        for workflow in WORKFLOWS:
            count = 2 if workflow == "hunter-autonomous-cycle" else 3
            for index in range(count):
                rows.append({
                    "id": run_id,
                    "name": workflow,
                    "event": "schedule",
                    "head_sha": SHA,
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": f"2026-10-02T00:{run_id:02d}:00Z",
                    "updated_at": f"2026-10-02T00:{run_id:02d}:30Z",
                })
                run_id += 1
        with self.assertRaisesRegex(Step23CollectError, "WAITING: hunter-autonomous-cycle"):
            _claim_window(rows, WORKFLOWS, 3)

    def test_classification_rejects_actual_failure(self):
        rows = [{
            "id": 1,
            "name": "hunter-autonomous-cycle",
            "event": "schedule",
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-10-02T00:10:00Z",
            "updated_at": "2026-10-02T00:11:00Z",
        }]
        with self.assertRaisesRegex(Step23CollectError, "soak contains failure"):
            _classify_runs(FakeGH(), rows, SHA)

    def test_classification_accepts_cancelled_only_with_later_success(self):
        cancelled = {
            "id": 10,
            "name": "agent-heartbeat-sweep",
            "event": "schedule",
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "cancelled",
            "created_at": "2026-10-02T00:10:00Z",
            "updated_at": "2026-10-02T00:11:00Z",
        }
        success = {
            "id": 11,
            "name": "agent-heartbeat-sweep",
            "event": "schedule",
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-10-02T00:20:00Z",
            "updated_at": "2026-10-02T00:21:00Z",
        }
        gh = FakeGH({
            11: [{
                "id": 1001,
                "name": "portfolio-agent-heartbeat-state",
                "expired": False,
                "digest": H,
            }]
        })
        classified = _classify_runs(gh, [cancelled, success], SHA)
        self.assertEqual(classified[0]["classification"], "CANCELLED_COALESCED")
        self.assertEqual(classified[0]["superseding_run_id"], 11)
        self.assertEqual(classified[1]["classification"], "SUCCESS")

    def test_classification_rejects_unsuperseded_cancellation(self):
        rows = [{
            "id": 20,
            "name": "portfolio-notification-cycle",
            "event": "schedule",
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "cancelled",
            "created_at": "2026-10-02T00:10:00Z",
            "updated_at": "2026-10-02T00:11:00Z",
        }]
        with self.assertRaisesRegex(Step23CollectError, "has no later successful successor"):
            _classify_runs(FakeGH(), rows, SHA)

    def test_pending_count_includes_only_queued_or_active(self):
        state = {
            "work_items": [
                {"state": "QUEUED"},
                {"state": "ACTIVE"},
                {"state": "COMPLETE"},
                {"state": "CANCELLED"},
            ]
        }
        self.assertEqual(_pending_count(state), 2)


if __name__ == "__main__":
    unittest.main()
