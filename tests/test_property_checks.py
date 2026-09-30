import unittest

from experiments.property_checks import PropertyCheckError, check_generated_cases


class PropertyChecksTests(unittest.TestCase):
    def test_generated_examples_are_reproducible_for_a_seed(self):
        def run():
            observed = []

            def property_holds(value):
                observed.append(value)
                return True

            count = check_generated_cases(
                lambda rng: rng.randrange(-100, 101),
                property_holds,
                examples=25,
                seed=4815,
            )
            return count, observed

        first = run()
        second = run()
        self.assertEqual(first, second)
        self.assertEqual(first[0], 25)

    def test_failure_reports_seed_and_greedily_shrinks_counterexample(self):
        def shrink(value):
            if value > 0:
                yield value - 1

        with self.assertRaises(PropertyCheckError) as raised:
            check_generated_cases(
                lambda rng: rng.randrange(1, 100),
                lambda _value: False,
                examples=10,
                seed=73,
                shrink=shrink,
            )

        error = raised.exception
        self.assertEqual(error.seed, 73)
        self.assertEqual(error.example_index, 0)
        self.assertEqual(error.counterexample, 0)
        self.assertIn("seed 73", str(error))

    def test_invalid_bounds_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            check_generated_cases(
                lambda rng: rng.random(),
                lambda _value: True,
                examples=0,
                seed=1,
            )


if __name__ == "__main__":
    unittest.main()
