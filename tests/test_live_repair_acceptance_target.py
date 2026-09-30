import unittest

from software_factory.live_repair_acceptance_target import acceptance_value


class LiveRepairAcceptanceTargetTests(unittest.TestCase):
    def test_acceptance_value_is_candidate(self):
        self.assertEqual(acceptance_value(), "CANDIDATE")
