import json
import unittest

from runtime.state import bootstrap_state
from scheduler.autonomous_scheduler import build_context, load_state, schedule_cycle
from scheduler.work_executor import execute_cycle


AT = "2026-09-26T20:40:00Z"


class SchedulerWorkExecutorTests(unittest.TestCase):
    def _single(self, work_type):
        state, receipt = schedule_cycle(load_state(), build_context(), at=AT)
        work = next(row for row in receipt["selected_work"] if row["work_type"] == work_type)
        state["work_items"] = [json.loads(json.dumps(work))]
        return state, work

    def test_success_is_only_path_to_complete(self):
        state, work = self._single("RESEARCH")
        def handler(row, ctx):
            return {
                "status": "SUCCESS",
                "result_kind": "TEST_PROOF",
                "evidence_refs": ["proof:test-success"],
                "result": {"source_ref": row["source_ref"]},
            }
        updated, receipts, executed, meta = execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            handlers={"RESEARCH": handler},
            max_items=1,
            at=AT,
        )
        row = updated["work_items"][0]
        self.assertEqual(row["state"], "COMPLETE")
        self.assertIn(work["fingerprint"], updated["completed_fingerprints"])
        self.assertEqual(receipts[0]["status"], "SUCCESS")
        self.assertEqual(len(executed), 1)
        self.assertEqual(meta["summary"]["completed_count"], 1)

    def test_handler_exception_requeues_and_never_paints_green(self):
        state, work = self._single("RESEARCH")
        def handler(row, ctx):
            raise RuntimeError("synthetic failure")
        updated, receipts, executed, meta = execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            handlers={"RESEARCH": handler},
            max_items=1,
            at=AT,
        )
        self.assertEqual(updated["work_items"][0]["state"], "QUEUED")
        self.assertNotIn(work["fingerprint"], updated["completed_fingerprints"])
        self.assertEqual(receipts[0]["status"], "DEFERRED")
        self.assertEqual(receipts[0]["result_kind"], "EXECUTION_ERROR")
        self.assertEqual(executed, [])
        self.assertEqual(meta["summary"]["completed_count"], 0)

    def test_explicit_defer_keeps_work_queued(self):
        state, work = self._single("INTEGRATION")
        def handler(row, ctx):
            return {
                "status": "DEFERRED",
                "result_kind": "WAITING_FOR_EVIDENCE",
                "evidence_refs": ["proof:not-ready"],
                "result": {},
            }
        updated, receipts, executed, _ = execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            handlers={"INTEGRATION": handler},
            max_items=1,
            at=AT,
        )
        self.assertEqual(updated["work_items"][0]["state"], "QUEUED")
        self.assertNotIn(work["fingerprint"], updated["completed_fingerprints"])
        self.assertEqual(receipts[0]["status"], "DEFERRED")
        self.assertEqual(executed, [])

    def test_unsupported_work_is_visible_and_not_completed(self):
        state, work = self._single("RESEARCH")
        updated, receipts, executed, _ = execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            handlers={},
            max_items=1,
            at=AT,
        )
        self.assertEqual(updated["work_items"][0]["state"], "QUEUED")
        self.assertEqual(receipts[0]["result_kind"], "NO_EXECUTION_HANDLER")
        self.assertEqual(executed, [])


if __name__ == "__main__":
    unittest.main()
