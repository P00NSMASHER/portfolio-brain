"""Adversarial, offline source-bound owner-activation regressions.

Never hits GitHub; synthetic records are NOT a production acceptance receipt.
"""
from datetime import datetime, timedelta, timezone
import unittest

from verification import owner_observation_window as ow

SOURCE = "a" * 40
OTHER = "b" * 40
START = datetime(2026, 10, 31, 10, 12, 54, tzinfo=timezone.utc)


def fmt(t):
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def observer_run(run_id=900, source=SOURCE, status="completed", conclusion="success",
                 path=ow.OBSERVER, branch="main", event="workflow_run", attempt=1,
                 when=START):
    return {"id": run_id, "head_sha": source, "head_branch": branch, "path": path,
            "event": event, "run_attempt": attempt, "status": status,
            "conclusion": conclusion, "created_at": fmt(when)}


def observer_job(run_id=900, source=SOURCE, status="completed", conclusion="success",
                 name="observe", attempt=1):
    return {"run_id": run_id, "head_sha": source, "run_attempt": attempt,
            "name": name, "status": status, "conclusion": conclusion}


class FakeAPI:
    def __init__(self, runs=None, jobs=None, current=None):
        self.runs = [observer_run()] if runs is None else runs
        self.jobs = ({900: observer_job()} if jobs is None else jobs)
        self.current = current

    def json(self, route):
        if route == ow.OBSERVER_RUNS:
            return {"total_count": len(self.runs), "workflow_runs": self.runs}
        if route.startswith("/actions/runs/") and route.endswith("/jobs?filter=all&per_page=100"):
            run_id = int(route.split("/")[3])
            job = self.jobs[run_id]
            return {"total_count": 1, "jobs": [job]}
        if route.startswith("/actions/runs/"):
            return self.current
        raise AssertionError("Unexpected provider GET: " + route)


def record(id, when):
    return {"id": id, "created": when - timedelta(minutes=2),
            "completed": when, "origin_kind": "cloudflare_cron_v1",
            "event": "workflow_dispatch"}


def sample_summary(n=26, first=START + timedelta(minutes=30)):
    # 26 genuine-looking synthetic records at 30-minute cadence.
    return {"automatic": [record(i+100, first + timedelta(minutes=30*i))
                          for i in range(n)]}


class OriginalObserverActivationTests(unittest.TestCase):
    def test_valid_first_success_has_exact_source_and_time(self):
        result = ow.activation(FakeAPI(), SOURCE)
        self.assertEqual(result["run_id"], 900)
        self.assertEqual(result["created"], START)

    def test_skipped_observer_never_activates(self):
        api = FakeAPI(runs=[observer_run(status="completed", conclusion="skipped")])
        with self.assertRaisesRegex(ow.OwnerWindowError, "NOT_FOUND"):
            ow.activation(api, SOURCE)

    def test_failed_or_cancelled_original_observer_not_relabelled(self):
        for conclusion in ("failure", "cancelled", "timed_out", None):
            with self.subTest(conclusion=conclusion):
                api = FakeAPI(runs=[
                    observer_run(run_id=899, conclusion=conclusion, when=START-timedelta(minutes=30)),
                    observer_run(),
                ])
                with self.assertRaisesRegex(ow.OwnerWindowError, "EARLIER_OBSERVER_ADVERSE"):
                    ow.activation(api, SOURCE)

    def test_wrong_source_wrong_branch_wrong_workflow_wrong_event_and_attempt(self):
        tamperings = [
            {"source": OTHER},
            {"branch": "dev"},
            {"path": ".github/workflows/other.yml"},
            {"event": "workflow_dispatch"},
            {"attempt": 2},
        ]
        for kwargs in tamperings:
            with self.subTest(kwargs=kwargs):
                api = FakeAPI(runs=[observer_run(**kwargs)])
                with self.assertRaisesRegex(ow.OwnerWindowError, "NOT_FOUND"):
                    ow.activation(api, SOURCE)

    def test_forged_original_job_denied(self):
        variants = [
            {"name": "monitor"}, {"source": OTHER}, {"attempt": 2},
            {"status": "completed", "conclusion": "skipped"},
            {"status": "completed", "conclusion": "failure"},
        ]
        for values in variants:
            with self.subTest(values=values):
                api = FakeAPI(jobs={900: observer_job(**values)})
                with self.assertRaises(ow.OwnerWindowError):
                    ow.activation(api, SOURCE)

    def test_choose_earliest_original_success_not_newer_success(self):
        early = START - timedelta(hours=1)
        api = FakeAPI(
            runs=[observer_run(run_id=901, when=START), observer_run(run_id=900, when=early)],
            jobs={900: observer_job(), 901: observer_job(run_id=901)})
        result = ow.activation(api, SOURCE)
        self.assertEqual(result["created"], early)

    def test_initial_run_can_anchor_only_verified_running_self(self):
        run = observer_run(status="in_progress", conclusion=None)
        api = FakeAPI(runs=[run], jobs={900: observer_job(status="in_progress", conclusion=None)},
                      current=run)
        self.assertEqual(ow.activation(api, SOURCE, current_run_id=900)["created"], START)
        for bad in (observer_run(source=OTHER, status="in_progress", conclusion=None),
                    observer_run(status="completed", conclusion="skipped")):
            with self.subTest(bad=bad):
                api = FakeAPI(runs=[], jobs={900: observer_job(status="in_progress", conclusion=None)},
                              current=bad)
                with self.assertRaises(ow.OwnerWindowError):
                    ow.activation(api, SOURCE, current_run_id=900)

    def test_bad_sha_and_bad_timestamp_rejected(self):
        for source in ("", "a"*39, "Z"*40, None):
            with self.subTest(source=source):
                with self.assertRaises(ow.OwnerWindowError):
                    ow.activation(FakeAPI(), source)
        for stamp in ("2026-10-31", "2026-10-31T06:00:00-04:00", "bad", 7):
            with self.subTest(stamp=stamp):
                with self.assertRaises(ow.OwnerWindowError):
                    ow.utc(stamp)

    def test_no_pre_activation_time_credit(self):
        before = [record(1, START-timedelta(hours=6)),
                  record(2, START-timedelta(hours=1))]
        summary = sample_summary(n=4)
        summary["automatic"] = before + summary["automatic"]
        window = ow.post_activation(summary, {"created": START})
        self.assertEqual(window["status"], "COLLECTING")
        self.assertEqual(len(window["automatic"]), 4)
        self.assertEqual(window["completed_span_seconds"], 5400)

    def test_real_twelve_hour_completed_core_span_required(self):
        before = ow.post_activation(sample_summary(n=24), {"created": START})
        boundary = ow.post_activation(sample_summary(n=25), {"created": START})
        self.assertEqual(before["status"], "COLLECTING")
        self.assertEqual(before["completed_span_seconds"], 23 * 1800)
        self.assertEqual(boundary["status"], "PASS")
        self.assertEqual(boundary["completed_span_seconds"], 43200)
        self.assertEqual(boundary["maximum_gap_seconds"], 1800)

    def test_one_gap_above_90_minutes_aborts_fail_closed(self):
        summary = sample_summary(n=25)
        summary["automatic"][8]["created"] += timedelta(hours=3)
        summary["automatic"][8]["completed"] += timedelta(hours=3)
        with self.assertRaisesRegex(ow.OwnerWindowError, "GAP_INVALID"):
            ow.post_activation(summary, {"created": START})

    def test_same_core_or_zero_gap_refused(self):
        summary = sample_summary(n=3)
        summary["automatic"][1] = dict(summary["automatic"][0])
        with self.assertRaisesRegex(ow.OwnerWindowError, "GAP_INVALID"):
            ow.post_activation(summary, {"created": START})

    def test_terminal_cutoff_requires_thirty_minutes(self):
        summary = sample_summary(n=25)
        scoped = ow.post_activation(summary, {"created": START})
        terminal = scoped["terminal"]["completed"]
        expected = ow.evidence_fields({"created": START, "run_id": 900}, scoped)
        with self.assertRaisesRegex(ow.OwnerWindowError, "REPAIR_PENDING"):
            ow.verify_post_activation(FakeAPI(), SOURCE, summary, expected,
                                      now=terminal + timedelta(minutes=29))
        self.assertEqual(
            ow.verify_post_activation(FakeAPI(), SOURCE, summary, expected,
                                      now=terminal + timedelta(minutes=30))["status"], "PASS")

    def test_forged_activation_in_receipt_cannot_pass(self):
        summary = sample_summary(n=25)
        scoped = ow.post_activation(summary, {"created": START})
        good = ow.evidence_fields({"created": START, "run_id": 900}, scoped)
        for key, bad in [
            ("owner_activation_observer_run_id", 999),
            ("owner_activation_observer_created_utc", fmt(START-timedelta(hours=5))),
            ("post_activation_completed_span_seconds", 1000),
            ("post_activation_maximum_gap_seconds", 0),
            ("post_activation_qualifying_cores", 2),
            ("post_activation_terminal_run_id", 777),
        ]:
            forged = dict(good)
            forged[key] = bad
            with self.subTest(key=key), self.assertRaisesRegex(
                    ow.OwnerWindowError, "EVIDENCE_MISMATCH"):
                ow.verify_post_activation(FakeAPI(), SOURCE, summary, forged,
                                          now=scoped["terminal"]["completed"]+timedelta(hours=1))

    def test_new_window_keeps_old_ancestry_but_not_old_12h_truncation(self):
        from verification.reliability_day import window
        first = START - timedelta(hours=5)
        rows = [{"head_sha": SOURCE, "created_at": fmt(first),
                 "status": "completed", "conclusion": "success",
                 "run_attempt": 1, "event": "push"}]
        for i in range(36):
            rows.append({"head_sha": SOURCE,
                         "created_at": fmt(first + timedelta(minutes=30*(i+1))),
                         "status": "completed", "conclusion": "success",
                         "run_attempt": 1, "event": "workflow_dispatch"})
        scoped = window(rows, SOURCE, activation_start=START)
        self.assertEqual(scoped[0]["event"], "push")
        # Source is 17.5h old but actual user-started 12h must remain observable.
        self.assertTrue(any(ow.utc(x["created_at"]) >= START + timedelta(hours=12)
                            for x in scoped))

    def test_no_last_mile_passing_if_post_activation_cores_missing(self):
        # Many earlier sources and a deployment-run success cannot fake time.
        summary = {"automatic": [
            record(i, START-timedelta(minutes=30*(25-i))) for i in range(25)]}
        scoped = ow.post_activation(summary, {"created": START})
        self.assertEqual(scoped["status"], "COLLECTING")
        with self.assertRaisesRegex(ow.OwnerWindowError, "12H_NOT_COMPLETE"):
            ow.verify_post_activation(FakeAPI(), SOURCE, summary, {},
                                      now=START+timedelta(days=2))


if __name__ == "__main__":
    unittest.main()
