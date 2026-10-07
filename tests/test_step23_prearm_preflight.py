import inspect
import unittest

from acceptance import step23_prearm_preflight as preflight


class Step23PrearmPreflightTests(unittest.TestCase):
    def test_correlation_ids_are_numeric_seeded_and_never_token_shaped(self):
        self.assertIsNotNone(preflight.CORRELATION.fullmatch("prearm-12345-initial-drain-1"))
        self.assertIsNotNone(preflight.CORRELATION.fullmatch("prearm-12345-2-runtime-hourly-sync"))
        self.assertIsNone(preflight.CORRELATION.fullmatch("prearm-initial-drain-1-ghs_secret"))
        self.assertIsNone(preflight.CORRELATION.fullmatch("prearm-12345-token.with.dots"))

    def test_drain_uses_auth_token_only_for_pending_state_reads(self):
        source=inspect.getsource(preflight.drain)
        self.assertIn("pending_event_count(github_token)",source)
        self.assertIn("correlation_seed",source)
        self.assertNotIn("{github_token}",source)
        self.assertNotIn("{token}",source)


if __name__=="__main__":
    unittest.main()
