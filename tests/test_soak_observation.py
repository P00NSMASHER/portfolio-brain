"""Regression tests use deterministic provider fixtures, not live-soak evidence."""
from __future__ import annotations
import copy
import unittest
from datetime import datetime, timedelta, timezone
from acceptance.soak_observation import (
    ObservationChanged, scheduled_runs, transport_runs, reset_history,
    final_census_unchanged, parse_time,
)

SHA = "a" * 40
START = datetime(2026, 10, 5, 19, 0, tzinfo=timezone.utc)
NAME = "portfolio-state-reducer"


def row(i=1, *, minute=1, status="completed", conclusion="success", sha=SHA):
    at = START + timedelta(minutes=minute)
    return dict(id=i, name=NAME, head_sha=sha, head_branch="main", event="schedule",
                workflow_id=31, path=".github/workflows/portfolio-state-reducer.yml",
                run_attempt=1, created_at=at.isoformat(), updated_at=(at + timedelta(seconds=30)).isoformat(),
                status=status, conclusion=conclusion)


class FakeAPI:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []
    def get(self, path):
        self.calls.append(path)
        if not self.pages:
            raise AssertionError("unexpected extra API request")
        value = self.pages.pop(0)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value if isinstance(value, dict) else {"workflow_runs": value})


class ScheduleObservationTests(unittest.TestCase):
    def test_ordinary_status_progress_does_not_destroy_observation(self):
        before = row(status="in_progress", conclusion=None)
        after = row()
        api = FakeAPI([before], [after])
        got = scheduled_runs(api, {NAME}, SHA, START)
        self.assertEqual(got[NAME][0]["conclusion"], "success")
        self.assertEqual(len(api.calls), 2)

    def test_status_regression_is_consumed_not_hidden(self):
        before = row()
        after = row(status="in_progress", conclusion=None)
        got = scheduled_runs(FakeAPI([before], [after]), {NAME}, SHA, START)
        self.assertEqual(got[NAME][0]["status"], "in_progress")

    def test_updated_timestamp_is_not_membership_drift(self):
        before, after = row(), row()
        after["updated_at"] = (START + timedelta(minutes=3)).isoformat()
        got = scheduled_runs(FakeAPI([before], [after]), {NAME}, SHA, START)
        self.assertEqual(got[NAME][0]["updated_at"], after["updated_at"])

    def test_new_run_retries_then_includes_it(self):
        older, newer = row(), row(2, minute=2)
        api = FakeAPI([older], [newer, older], [newer, older], [newer, older])
        got = scheduled_runs(api, {NAME}, SHA, START)
        self.assertEqual([r["id"] for r in got[NAME]], [1, 2])
        self.assertEqual(len(api.calls), 4)

    def test_deleted_run_retries_instead_of_counting_it(self):
        api = FakeAPI([row()], [], [], [])
        got = scheduled_runs(api, {NAME}, SHA, START)
        self.assertEqual(got[NAME], [])

    def test_changed_attempt_retries(self):
        first, second = row(), row()
        second["run_attempt"] = 2
        api = FakeAPI([first], [second], [second], [second])
        self.assertEqual(scheduled_runs(api, {NAME}, SHA, START)[NAME][0]["run_attempt"], 2)

    def test_continuously_changing_membership_stops_after_three_attempts(self):
        api = FakeAPI([row()], [], [row()], [], [row()], [])
        with self.assertRaises(ObservationChanged):
            scheduled_runs(api, {NAME}, SHA, START)
        self.assertEqual(len(api.calls), 6)

    def test_api_auth_failure_is_not_retried_or_disguised(self):
        api = FakeAPI(PermissionError("denied"))
        with self.assertRaises(PermissionError):
            scheduled_runs(api, {NAME}, SHA, START)
        self.assertEqual(len(api.calls), 1)

    def test_different_head_cannot_count(self):
        r = row(sha="b" * 40)
        self.assertEqual(scheduled_runs(FakeAPI([r], [r]), {NAME}, SHA, START)[NAME], [])

    def test_before_window_cannot_count(self):
        r = row(minute=-2)
        self.assertEqual(scheduled_runs(FakeAPI([r], [r]), {NAME}, SHA, START)[NAME], [])

    def test_unrequired_workflow_cannot_count(self):
        r = row(); r["name"] = "other"
        self.assertEqual(scheduled_runs(FakeAPI([r], [r]), {NAME}, SHA, START)[NAME], [])

    def test_dispatch_never_masquerades_as_schedule(self):
        r = row(); r["event"] = "workflow_dispatch"
        with self.assertRaisesRegex(RuntimeError, "wrong-branch or wrong-event"):
            scheduled_runs(FakeAPI([r]), {NAME}, SHA, START)

    def test_transport_runs_keeps_schedule_and_dispatch_distinct(self):
        scheduled=row(1)
        dispatched=row(2,minute=2); dispatched["event"]="workflow_dispatch"
        api=FakeAPI([scheduled],[scheduled],[dispatched],[dispatched])
        got=transport_runs(api,{NAME},SHA,START)
        self.assertEqual([(r["id"],r["event"]) for r in got[NAME]],[(1,"schedule"),(2,"workflow_dispatch")])

    def test_non_main_never_counts(self):
        r = row(); r["head_branch"] = "feature"
        with self.assertRaisesRegex(RuntimeError, "wrong-branch or wrong-event"):
            scheduled_runs(FakeAPI([r]), {NAME}, SHA, START)

    def test_malformed_provider_data_is_not_empty_success(self):
        for doc in ({}, {"workflow_runs": None}, {"workflow_runs": [None]}):
            with self.subTest(doc=doc), self.assertRaises(RuntimeError):
                scheduled_runs(FakeAPI(doc), {NAME}, SHA, START)

    def test_boolean_id_is_not_valid_identity(self):
        r = row(); r["id"] = True
        with self.assertRaises(RuntimeError):
            scheduled_runs(FakeAPI([r]), {NAME}, SHA, START)

    def test_naive_timestamp_is_rejected(self):
        r = row(); r["created_at"] = "2026-10-05T19:01:00"
        with self.assertRaises(RuntimeError):
            scheduled_runs(FakeAPI([r]), {NAME}, SHA, START)

    def test_completed_without_conclusion_is_rejected(self):
        r = row(conclusion=None)
        with self.assertRaises(RuntimeError):
            scheduled_runs(FakeAPI([r]), {NAME}, SHA, START)

    def test_page_bound_is_not_silently_truncated(self):
        batch = [row(i, minute=101-i) for i in range(1, 101)]
        with self.assertRaisesRegex(RuntimeError, "page bound"):
            scheduled_runs(FakeAPI(batch), {NAME}, SHA, START, max_pages=1)

    def test_multi_page_success(self):
        batch = [row(i, minute=101-i) for i in range(1, 101)]
        tail = [row(101, minute=0)]
        api = FakeAPI(batch, tail, batch)
        got = scheduled_runs(api, {NAME}, SHA, START)
        self.assertEqual(len(got[NAME]), 101)

    def test_duplicate_across_pages_fails_bounded(self):
        batch = [row(i, minute=101-i) for i in range(1, 101)]
        with self.assertRaises(ObservationChanged):
            scheduled_runs(FakeAPI(batch, [batch[-1]]), {NAME}, SHA, START, max_attempts=1)

    def test_invalid_bounds_are_rejected(self):
        for kwargs in ({"max_pages": 0}, {"max_pages": 21}, {"max_attempts": 0}, {"max_attempts": 4}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                scheduled_runs(FakeAPI(), {NAME}, SHA, START, **kwargs)


class ResetHistoryTests(unittest.TestCase):
    @staticmethod
    def no_coalescing(r, rows):
        return None

    def test_all_failures_are_counted_not_only_latest(self):
        rows = [row(i, minute=i, conclusion="failure") for i in range(1, 4)]
        history, effective = reset_history({NAME: rows}, START, 5, self.no_coalescing)
        self.assertEqual(len(history), 3)
        self.assertEqual(effective, parse_time(rows[-1]["updated_at"]))

    def test_six_existing_failures_exceed_limit_even_on_first_observation(self):
        rows = [row(i, minute=i, conclusion="failure") for i in range(1, 7)]
        with self.assertRaisesRegex(RuntimeError, "MAX_RESETS"):
            reset_history({NAME: rows}, START, 5, self.no_coalescing)

    def test_restarting_once_mode_preserves_identical_history(self):
        data = {NAME: [row(1, conclusion="failure"), row(2, minute=3, conclusion="timed_out")]}
        self.assertEqual(reset_history(data, START, 5, self.no_coalescing),
                         reset_history(copy.deepcopy(data), START, 5, self.no_coalescing))

    def test_success_and_active_run_do_not_reset(self):
        data = {NAME: [row(), row(2, status="in_progress", conclusion=None)]}
        self.assertEqual(reset_history(data, START, 5, self.no_coalescing), ([], START))

    def test_short_cancellation_requires_existing_classifier_acceptance(self):
        rows = [row(1, conclusion="cancelled"), row(2, minute=2)]
        self.assertEqual(len(reset_history({NAME: rows}, START, 5, self.no_coalescing)[0]), 1)
        self.assertEqual(reset_history({NAME: rows}, START, 5, lambda r, rs: rs[-1])[0], [])

    def test_reset_history_rejects_duplicate_run(self):
        r = row(conclusion="failure")
        with self.assertRaises(RuntimeError):
            reset_history({NAME: [r, r]}, START, 5, self.no_coalescing)

    def test_completion_before_creation_is_rejected(self):
        r = row(conclusion="failure"); r["updated_at"] = START.isoformat()
        with self.assertRaises(RuntimeError):
            reset_history({NAME: [r]}, START, 5, self.no_coalescing)

    def test_prior_window_failure_is_not_counted(self):
        r = row(minute=-1, conclusion="failure")
        self.assertEqual(reset_history({NAME: [r]}, START, 5, self.no_coalescing), ([], START))

    def test_new_failure_changes_effective_start(self):
        a, b = row(1, conclusion="failure"), row(2, minute=9, conclusion="failure")
        h1, t1 = reset_history({NAME: [a]}, START, 5, self.no_coalescing)
        h2, t2 = reset_history({NAME: [a, b]}, START, 5, self.no_coalescing)
        self.assertEqual((len(h1), len(h2)), (1, 2))
        self.assertGreater(t2, t1)


class FinalCensusTests(unittest.TestCase):
    def test_unchanged_census_is_accepted(self):
        grouped = {NAME: [row()]}
        self.assertTrue(final_census_unchanged(grouped, copy.deepcopy(grouped)))

    def test_new_active_run_blocks_finalization(self):
        old = {NAME: [row()]}
        new = {NAME: [row(), row(2, status="in_progress", conclusion=None)]}
        self.assertFalse(final_census_unchanged(old, new))

    def test_new_failure_blocks_finalization(self):
        old = {NAME: [row()]}
        new = {NAME: [row(), row(2, conclusion="failure")]}
        self.assertFalse(final_census_unchanged(old, new))

    def test_deleted_run_blocks_finalization(self):
        self.assertFalse(final_census_unchanged({NAME: [row()]}, {NAME: []}))

    def test_rerun_attempt_blocks_finalization(self):
        old = {NAME: [row()]}; new = copy.deepcopy(old)
        new[NAME][0]["run_attempt"] = 2
        self.assertFalse(final_census_unchanged(old, new))

    def test_changed_conclusion_blocks_finalization(self):
        self.assertFalse(final_census_unchanged({NAME: [row()]}, {NAME: [row(conclusion="failure")]}))

    def test_changed_workflow_set_blocks_finalization(self):
        self.assertFalse(final_census_unchanged({NAME: []}, {}))

    def test_incidental_actor_metadata_does_not_invalidate_evidence(self):
        old = {NAME: [row()]}; new = copy.deepcopy(old)
        new[NAME][0]["actor"] = {"login": "updated-profile"}
        self.assertTrue(final_census_unchanged(old, new))

if __name__ == "__main__":
    unittest.main()
