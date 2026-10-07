import inspect
import unittest

from acceptance import step23_wait_reducer_barrier as barrier


class Step23WaitReducerBarrierTests(unittest.TestCase):
    def test_all_step23_canonical_readers_are_allowed(self):
        self.assertEqual(
            barrier.ALLOWED_TARGETS,
            {
                "runtime-hourly-sync",
                "portfolio-autonomous-scheduler",
                "hunter-autonomous-cycle",
                "agent-heartbeat-sweep",
                "portfolio-cost-watchdog",
                "portfolio-notification-cycle",
                "command-center-pages",
            },
        )

    def test_prearm_id_is_numeric_seeded_and_nonsecret(self):
        self.assertIsNotNone(barrier.PREARM_ID.fullmatch("prearm-12345-4-hunter-autonomous-cycle"))
        self.assertIsNone(barrier.PREARM_ID.fullmatch("prearm-ghs_secret"))
        self.assertIsNone(barrier.PREARM_ID.fullmatch("manual"))

    def test_barrier_wait_is_read_only_and_requires_zero_pending_events(self):
        api_source=inspect.getsource(barrier.API)
        main_source=inspect.getsource(barrier.main)
        self.assertNotIn("def post",api_source)
        self.assertNotIn('method="POST"',api_source)
        self.assertIn("pending_event_count(token)",main_source)
        self.assertIn("pending==0",main_source.replace(" ",""))
        self.assertIn('"acceptance_credit":False',main_source.replace(" ",""))

    def test_steady_state_barrier_binds_source_run_and_attempt(self):
        main_source=inspect.getsource(barrier.main)
        self.assertIn("GITHUB_RUN_ID",main_source)
        self.assertIn("GITHUB_RUN_ATTEMPT",main_source)
        self.assertIn("writerbarrier-",main_source)
        self.assertIn('"STEADY_STATE"',main_source)
        self.assertIn('expected_event="workflow_run"',main_source)

    def test_in_progress_barrier_does_not_mark_live_writer_as_explicit_recovery(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        reducer=(root/".github/workflows/portfolio-state-reducer.yml").read_text()
        self.assertIn(
            "TRIGGER_WORKFLOW_RUN_ID: ${{ github.event_name == 'workflow_run' && github.event.action == 'completed' && github.event.workflow_run.id || '' }}",
            reducer,
        )
        self.assertIn("types: [in_progress, completed]",reducer)


    def test_steady_fallback_accepts_only_new_exact_main_reducer_success(self):
        exact="a"*40
        old={
            "id":10,"run_attempt":1,"status":"completed","conclusion":"success",
            "head_branch":"main","head_sha":exact,"updated_at":"2026-10-07T16:00:00Z",
        }
        baseline=barrier.reducer_success_keys([old],exact)
        self.assertIsNone(barrier.fresh_reducer_success([old],exact,baseline))
        new={
            "id":11,"run_attempt":1,"status":"completed","conclusion":"success",
            "head_branch":"main","head_sha":exact,"updated_at":"2026-10-07T16:01:00Z",
        }
        self.assertEqual(
            barrier.fresh_reducer_success([new,old],exact,baseline)["id"],
            11,
        )

    def test_reducer_that_was_in_progress_at_entry_becomes_fresh_on_success(self):
        exact="a"*40
        running={
            "id":12,"run_attempt":1,"status":"in_progress","conclusion":None,
            "head_branch":"main","head_sha":exact,"updated_at":"2026-10-07T16:00:00Z",
        }
        baseline=barrier.reducer_success_keys([running],exact)
        self.assertEqual(baseline,set())
        completed={**running,"status":"completed","conclusion":"success","updated_at":"2026-10-07T16:02:00Z"}
        self.assertEqual(
            barrier.fresh_reducer_success([completed],exact,baseline)["id"],
            12,
        )

    def test_baseline_ignores_prior_main_success_and_records_exact_current_main(self):
        exact="a"*40
        prior={
            "id":13,"run_attempt":1,"status":"completed","conclusion":"success",
            "head_branch":"main","head_sha":"b"*40,"updated_at":"2026-10-07T16:03:00Z",
        }
        current={
            "id":14,"run_attempt":1,"status":"completed","conclusion":"success",
            "head_branch":"main","head_sha":exact,"updated_at":"2026-10-07T16:04:00Z",
        }
        self.assertEqual(
            barrier.reducer_success_keys([prior,current],exact),
            {(14,1,"2026-10-07T16:04:00Z")},
        )

    def test_new_wrong_head_success_cannot_satisfy_fallback(self):
        exact="a"*40
        wrong={
            "id":15,"run_attempt":1,"status":"completed","conclusion":"success",
            "head_branch":"main","head_sha":"b"*40,"updated_at":"2026-10-07T16:05:00Z",
        }
        self.assertIsNone(barrier.fresh_reducer_success([wrong],exact,set()))

    def test_exact_main_success_with_malformed_identity_fails_closed(self):
        exact="a"*40
        malformed={
            "id":"16","run_attempt":1,"status":"completed","conclusion":"success",
            "head_branch":"main","head_sha":exact,"updated_at":"2026-10-07T16:06:00Z",
        }
        with self.assertRaisesRegex(RuntimeError,"run identity malformed"):
            barrier.fresh_reducer_success([malformed],exact,set())

    def test_prearm_never_uses_fresh_reducer_fallback(self):
        source=inspect.getsource(barrier.main).replace(" ","")
        self.assertIn('ifbarrier_kind=="STEADY_STATE":',source)
        self.assertIn('"FRESH_REDUCER_FALLBACK"iffallback_usedelse"CORRELATED"',source)
        self.assertNotIn('barrier_kind=="PREARM":\n            fresh=',inspect.getsource(barrier.main))


if __name__=="__main__":
    unittest.main()
