import datetime as dt
import unittest

from brain import hunter_schedule_watchdog as h


def when(hour, minute=0):
    return dt.datetime(2026, 11, 6, hour, minute, tzinfo=dt.timezone.utc)


def item(id, event, title, when_created, status="completed", conclusion="success"):
    return {
        "id": id, "run_attempt": 1, "event": event,
        "display_title": title, "status": status, "conclusion": conclusion,
        "created_at": when_created.isoformat().replace("+00:00", "Z"),
    }


class IndependentScoutClockTests(unittest.TestCase):
    def test_exact_original_fifteen_crons_and_app_authentication(self):
        content = "\n".join('    - cron: "' + c + '"' for c in h.CRONS)
        required = (
            "run-name: >-\n"
            "github.event.schedule\n"
            "github.event.client_payload.scheduled_slot\n"
            "github.actor == 'portfolio-brain-v8-runtime[bot]'\n"
            "github.event.client_payload.expected_main == github.sha\n"
            "hunter-integrator-\n"
            "needs.scout.outputs.worker != 'INTEGRATOR'\n"
            "types: [retally-scout-recovery-v1]\n"
        )
        h.check_source(content + "\n" + required)
        with self.assertRaises(h.EvidenceError):
            h.check_source(content.replace("7 2,14", "8 2,14") + "\n" + required)
        with self.assertRaises(h.EvidenceError):
            h.check_source(content + "\n" + required.replace("github.actor", "github.other_actor"))

    def test_cron_slots_are_utc_two_daily_with_grace(self):
        before = h.recent_due_slots(when(2, 25))
        self.assertFalse(any(x["slot"] == "2026-11-06T02:07:00Z" for x in before))
        after = h.recent_due_slots(when(2, 40))
        self.assertTrue(any(x["worker"] == "HUNTER-01" and
                            x["slot"] == "2026-11-06T02:07:00Z"
                            for x in after))
        self.assertFalse(any(x["worker"] == "HUNTER-02" and
                             x["slot"] == "2026-11-06T02:15:00Z"
                             for x in after))
        self.assertEqual(len(h.CRONS), 15)
        self.assertEqual(len(set(h.CRONS.values())), 15)

    def test_exact_source_slots_do_not_accept_generic_green_runs(self):
        d = {"worker": "HUNTER-01", "cron": "7 2,14 * * *",
             "slot": "2026-11-06T02:07:00Z"}
        native = item(11, "schedule", "Hunter 7 2,14 * * * slot=native", when(2, 13))
        dispatched = item(12, "repository_dispatch",
                          "Hunter HUNTER-01 slot=2026-11-06T02:07:00Z", when(2, 40))
        self.assertTrue(h.belongs(native, d, when(3)))
        self.assertTrue(h.belongs(dispatched, d, when(3)))
        self.assertFalse(h.belongs({**native, "display_title": "Hunter SOURCE_PUSH slot=native"}, d, when(3)))
        self.assertFalse(h.belongs({**dispatched, "display_title": "Hunter HUNTER-02 slot=2026-11-06T02:07:00Z"}, d, when(3)))
        self.assertFalse(h.belongs({**dispatched, "display_title": "Hunter HUNTER-01 slot=2026-11-05T14:07:00Z"}, d, when(3)))
        self.assertFalse(h.belongs({**native, "event": "push"}, d, when(3)))

    def test_success_needs_worker_job_and_retained_artifact(self):
        run = item(23, "schedule", "Hunter 7 2,14 * * * slot=native", when(2, 13))
        def good(path):
            if path.endswith("/jobs?per_page=100"):
                return {"jobs": [{"name": "scout", "conclusion": "success"},
                                 {"name": "candidate-inspection", "conclusion": "success"}]}
            return {"artifacts": [{"name": "hunter-inspection-23-1",
                                  "size_in_bytes": 503, "expired": False}]}
        self.assertTrue(h.completed_receipt(run, "HUNTER-01", good))
        def absent(path):
            r = good(path)
            if "artifacts?" in path:
                r["artifacts"] = []
            return r
        self.assertFalse(h.completed_receipt(run, "HUNTER-01", absent))
        def skipped(path):
            r = good(path)
            if "jobs?" in path:
                r["jobs"][1]["conclusion"] = "skipped"
            return r
        self.assertFalse(h.completed_receipt(run, "HUNTER-01", skipped))
        def outage(_):
            raise ConnectionError("provider unavailable")
        with self.assertRaises(ConnectionError):
            h.completed_receipt(run, "HUNTER-01", outage)
        integrator = item(24, "repository_dispatch",
                          "Hunter INTEGRATOR slot=2026-11-06T04:07:00Z", when(4, 50))
        def integrator_receipt(path):
            if path.endswith("/jobs?per_page=100"):
                return {"jobs": [{"name": "scout", "conclusion": "success"},
                                 {"name": "candidate-inspection", "conclusion": "skipped"}]}
            return {"artifacts": [{"name": "hunter-integrator-24-1",
                                  "size_in_bytes": 100, "expired": False}]}
        self.assertTrue(h.completed_receipt(integrator, "INTEGRATOR", integrator_receipt))

    def test_missing_slot_is_recovered_once_then_bounded(self):
        now = when(4, 30)
        missing = h.reconcile(now, [], lambda *_: False)
        self.assertEqual(missing["due"][0]["worker"], "HUNTER-01")
        self.assertEqual(len(missing["due"]), 1)
        self.assertGreater(missing["backlog"], 1)
        self.assertEqual(h.MAX_PER_CYCLE, 1)
        self.assertEqual(missing["due"][0]["slot"], "2026-11-06T02:07:00Z")
        native = item(23, "schedule", "Hunter 7 2,14 * * * slot=native", when(2, 13))
        self.assertFalse(any(x["worker"] == "HUNTER-01" for x in
                             h.reconcile(now, [native], lambda *_: True)["due"]))
        queued = item(25, "repository_dispatch",
                      "Hunter HUNTER-01 slot=2026-11-06T02:07:00Z", when(4, 0),
                      "in_progress", None)
        self.assertFalse(any(x["worker"] == "HUNTER-01" for x in
                             h.reconcile(now, [queued], lambda *_: False)["due"]))
        failed = {**queued, "status": "completed", "conclusion": "failure"}
        self.assertFalse(any(x["worker"] == "HUNTER-01" for x in
                             h.reconcile(now, [failed], lambda *_: False)["due"]))
        later = when(5, 30)
        self.assertTrue(any(x["worker"] == "HUNTER-01" for x in
                            h.reconcile(later, [failed], lambda *_: False)["due"]))
        failed2 = {**failed, "id": 26, "created_at": when(5, 20).isoformat().replace("+00:00","Z")}
        self.assertTrue(any(x["worker"] == "HUNTER-01" for x in
                            h.reconcile(when(6, 5), [failed, failed2], lambda *_: False)["exhausted"]))

    def test_does_not_write_other_repositories_or_extra_endpoints(self):
        with self.assertRaises(h.EvidenceError):
            h.api("repos/somewhere/else/branches/main")
        with self.assertRaises(h.EvidenceError):
            h.api("repos/P00NSMASHER/github-value-hunt-ledger/contents/README.md",
                  payload={"injected": "write"})


    def test_watchdog_is_downstream_of_original_core_and_does_not_create_timer(self):
        from pathlib import Path
        source = Path(".github/workflows/v8-scoped-repair.yml").read_text(encoding="utf-8")
        job = source.split("\n  recover-missed-hunter-slots:\n", 1)[1]
        self.assertIn("github.event.workflow_run.name == 'brain-cycle-v2'", job)
        self.assertIn("github.event.workflow_run.head_sha == github.sha", job)
        self.assertIn("github.event.workflow_run.run_attempt == 1", job)
        self.assertIn("steps.missed.outputs.due == 'true'", job)
        self.assertIn("permission-contents: write", job)
        self.assertIn("permission-actions: read", job)
        self.assertIn("--dispatch", job)
        self.assertIn("brain-hunter-schedule-recovery-", job)
        self.assertNotIn("\n  schedule:", job)
        self.assertNotIn("on:\n  schedule:", job)


    def test_shared_github_pending_queue_never_gets_a_second_dispatch(self):
        now = when(4, 30)
        for status in ("queued", "in_progress", "pending", "waiting", "requested"):
            with self.subTest(status=status):
                pending = item(933, "repository_dispatch",
                               "Hunter HUNTER-05 slot=2026-11-06T02:39:00Z",
                               when(4, 20), status, None)
                plan = h.reconcile(now, [pending], lambda *_: False)
                self.assertEqual(plan["due"], [])
                self.assertGreater(plan["backlog"], 0)
                self.assertEqual(plan["blocking_run_ids"], [933])
        # Failed and cancelled completed runs are not counted as active.
        canceled = item(934, "repository_dispatch",
                        "Hunter HUNTER-05 slot=2026-11-06T02:39:00Z",
                        when(3, 30), "completed", "cancelled")
        later = h.reconcile(now, [canceled], lambda *_: False)
        self.assertEqual(len(later["due"]), 1)
        self.assertEqual(later["blocking_run_ids"], [])



if __name__ == "__main__":
    unittest.main()
