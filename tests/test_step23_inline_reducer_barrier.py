import inspect
import unittest

from acceptance import step23_inline_reducer_barrier as barrier


class Step23InlineReducerBarrierTests(unittest.TestCase):
    def test_only_stale_sensitive_targets_are_allowed(self):
        self.assertEqual(
            barrier.ALLOWED_TARGETS,
            {"hunter-autonomous-cycle","command-center-pages"},
        )

    def test_prearm_id_is_numeric_seeded_and_nonsecret(self):
        self.assertIsNotNone(barrier.PREARM_ID.fullmatch("prearm-12345-4-hunter-autonomous-cycle"))
        self.assertIsNone(barrier.PREARM_ID.fullmatch("prearm-ghs_secret"))
        self.assertIsNone(barrier.PREARM_ID.fullmatch("manual"))

    def test_barrier_waits_for_reducer_and_zero_pending_events(self):
        source=inspect.getsource(barrier.main)
        self.assertIn("run_reducer",source)
        self.assertIn("pending_event_count(token)",source)
        self.assertIn("pending==0",source.replace(" ",""))
        self.assertIn('"acceptance_credit":False',source.replace(" ",""))


if __name__=="__main__":
    unittest.main()
