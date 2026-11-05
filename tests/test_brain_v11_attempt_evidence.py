"""Hostile GitHub attempt evidence must fail closed before V11 enrollment."""
from copy import deepcopy
import unittest

from brain.v11 import verified_delivery as d
from test_brain_v11_delivery import Fake, BASE, RUN


class AttemptProvider:
    def __init__(self, run_attempt=1, job_attempt=1):
        self.original = Fake()
        self.run_attempt = run_attempt
        self.job_attempt = job_attempt
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path))
        result = deepcopy(self.original.get(path))
        if path == d.ROOT + "actions/runs/" + str(RUN):
            result["run_attempt"] = self.run_attempt
        if path == d.ROOT + "actions/runs/" + str(RUN) + "/jobs?per_page=100":
            result["jobs"][0]["run_attempt"] = self.job_attempt
        return result


class OriginalAttemptEvidenceTests(unittest.TestCase):
    def test_real_first_attempt_integer_still_admitted(self):
        self.assertEqual(d._original_failed_run(AttemptProvider(), RUN, BASE),
                         {"PREFLIGHT"})

    def test_malformed_run_and_job_attempts_never_count_as_first(self):
        for field, expected_error in (
            ("run_attempt", "V11_ORIGINAL_FAILURE_UNVERIFIED"),
            ("job_attempt", "V11_ORIGINAL_FAILED_STEP_OR_AUTOMATIC_ORIGIN_MISSING"),
        ):
            for malicious in (True, 1.0, "1", None, False, 0, 2):
                with self.subTest(field=field, attempt=malicious):
                    values = {field: malicious}
                    api = AttemptProvider(**values)
                    with self.assertRaisesRegex(d.DeliveryDenied, expected_error):
                        d._original_failed_run(api, RUN, BASE)
                    self.assertTrue(all(method == "GET" for method, _ in api.calls))


if __name__ == "__main__":
    unittest.main()
