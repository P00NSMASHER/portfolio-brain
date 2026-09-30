import random
import unittest

from experiments.property_testing import (
    MAX_EXAMPLES,
    PropertyCheckError,
    PropertyFailure,
    run_property,
)


class PropertyTestingTests(unittest.TestCase):
    def test_bounded_generated_properties_are_reproducible(self):
        observed = []

        def generate(rng: random.Random) -> int:
            value = rng.randrange(100)
            observed.append(value)
            return value

        first = run_property(generate, lambda value: value < 100, seed=42, examples=25)
        first_examples = observed[:]
        observed.clear()
        second = run_property(generate, lambda value: value < 100, seed=42, examples=25)
        self.assertEqual(
            first,
            {"seed": 42, "examples_checked": 25, "status": "PASSED"},
        )
        self.assertEqual(second, first)
        self.assertEqual(observed, first_examples)

    def test_failure_reports_reproducible_and_shrunk_counterexample(self):
        def generate(rng: random.Random) -> int:
            return rng.randrange(50, 100)

        def shrink(value: int):
            return range(value - 1, -1, -1)

        with self.assertRaises(PropertyFailure) as raised:
            run_property(
                generate,
                lambda value: value < 50,
                seed=1,
                examples=10,
                shrink=shrink,
                max_shrinks=100,
            )

        failure = raised.exception
        self.assertEqual(failure.seed, 1)
        self.assertEqual(failure.example_index, 0)
        self.assertGreaterEqual(failure.counterexample, 50)
        self.assertEqual(failure.minimized_counterexample, 50)
        self.assertEqual(failure.examples_checked, 1)
        self.assertLessEqual(failure.shrinks_checked, 100)

    def test_invalid_or_unbounded_requests_fail_closed(self):
        with self.assertRaises(PropertyCheckError):
            run_property(lambda _rng: 1, lambda _value: True, seed=0, examples=MAX_EXAMPLES + 1)
        with self.assertRaises(PropertyCheckError):
            run_property(lambda _rng: 1, lambda _value: 1, seed=0, examples=1)


if __name__ == "__main__":
    unittest.main()
