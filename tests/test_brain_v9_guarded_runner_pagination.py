"""Hostile, network-free pagination tests for guarded PR discovery."""
import copy
import unittest

from brain.v9 import guarded_merge_runner as runner
from brain.v9.guarded_merge import Denied, REPO

ROOT = "repos/" + REPO + "/"
PREFIX = ROOT + "pulls?state=open&per_page=20&page="


class FakePagedCensus:
    def __init__(self, records):
        self.records = records
        self.paths = []
        self.writes = 0

    def get(self, path):
        self.paths.append(path)
        if not path.startswith(PREFIX):
            raise AssertionError("unapproved path")
        page = path[len(PREFIX):]
        if page not in ("1", "2", "3", "4", "5"):
            raise AssertionError("unbounded page")
        start = (int(page) - 1) * 20
        return copy.deepcopy(self.records[start:start + 20])

    def graphql(self, *_):
        self.writes += 1
        raise AssertionError("pagination must not write")


def records(count):
    return [{"number": n, "state": "open", "draft": False,
             "labels": [], "head": {"sha": "a" * 40}}
            for n in range(1, count + 1)]


class GuardedOpenPrPaginationTests(unittest.TestCase):
    def test_sixty_open_prs_are_read_in_bounded_double_census(self):
        api = FakePagedCensus(records(60))
        result = runner.complete_open_pull_census(api, ROOT)
        self.assertEqual(len(result), 60)
        self.assertEqual(len({row["number"] for row in result}), 60)
        self.assertEqual(api.paths, [PREFIX + str(p) for p in (1, 2, 3, 4)] * 2)
        self.assertEqual(api.writes, 0)

    def test_zero_and_99_are_in_bounds(self):
        for count in (0, 1, 19, 20, 21, 80, 99):
            with self.subTest(count=count):
                api = FakePagedCensus(records(count))
                self.assertEqual(len(runner.complete_open_pull_census(api, ROOT)), count)
                self.assertLessEqual(len(api.paths), 10)
                self.assertEqual(api.writes, 0)

    def test_100_or_more_hold_without_partial_admission(self):
        for count in (100, 103):
            with self.subTest(count=count):
                api = FakePagedCensus(records(count))
                with self.assertRaisesRegex(Denied, "RUNNER_OPEN_PR_CENSUS_INCOMPLETE"):
                    runner.complete_open_pull_census(api, ROOT)
                self.assertEqual(len(api.paths), 5)
                self.assertEqual(api.writes, 0)

    def test_duplicate_across_pages_denied(self):
        rows = records(21)
        rows[-1]["number"] = rows[0]["number"]
        api = FakePagedCensus(rows)
        with self.assertRaisesRegex(Denied, "RUNNER_DUPLICATE_CANDIDATES"):
            runner.complete_open_pull_census(api, ROOT)
        self.assertEqual(api.writes, 0)

    def test_non_list_and_oversized_pages_denied(self):
        for faulty in ("not-a-list", records(21), [None]):
            class Faulty(FakePagedCensus):
                def get(self, path):
                    return faulty
            with self.subTest(kind=str(type(faulty))):
                with self.assertRaisesRegex(Denied, "RUNNER_OPEN_PR_CENSUS_INCOMPLETE"):
                    runner.complete_open_pull_census(Faulty(records(0)), ROOT)

    def test_invalid_numbers_denied_instead_of_silent_skips(self):
        for value in (True, 0, -4, "1", None, 10**9):
            with self.subTest(value=value):
                api = FakePagedCensus([{"number": value}])
                with self.assertRaisesRegex(Denied, "RUNNER_PR_NUMBER_INVALID"):
                    runner.complete_open_pull_census(api, ROOT)
                self.assertEqual(api.writes, 0)

    def test_changes_between_censuses_fail_closed(self):
        class Drifting(FakePagedCensus):
            def get(self, path):
                self.paths.append(path)
                if len(self.paths) == 2:
                    return [{"number": 12, "labels": []}]
                return [{"number": 11, "labels": []}]
        api = Drifting(records(1))
        with self.assertRaisesRegex(Denied, "RUNNER_OPEN_PR_CENSUS_CHANGED"):
            runner.complete_open_pull_census(api, ROOT)
        self.assertEqual(len(api.paths), 2)
        self.assertEqual(api.writes, 0)

    def test_missing_or_changed_labels_between_censuses_hold(self):
        class Relabeled(FakePagedCensus):
            def get(self, path):
                self.paths.append(path)
                return [{"number": 10, "labels": [{"name": "brain:guarded-automerge"}]
                         if len(self.paths) > 1 else []}]
        api = Relabeled(records(1))
        with self.assertRaisesRegex(Denied, "RUNNER_OPEN_PR_CENSUS_CHANGED"):
            runner.complete_open_pull_census(api, ROOT)
        self.assertEqual(api.writes, 0)


if __name__ == "__main__":
    unittest.main()
