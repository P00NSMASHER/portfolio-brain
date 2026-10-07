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


if __name__=="__main__":
    unittest.main()
