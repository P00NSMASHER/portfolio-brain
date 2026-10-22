"""One scheduled owner cannot receive two simultaneous project handoffs."""
import unittest

from brain.v8.engineering import build_cycle
from brain.v8.planning import select_work
from test_brain_v8_contracts import work

SHA = "a" * 40
NOW = "2026-10-21T22:00:00Z"
PLATE = "P00NSMASHER/permitplate-nyc"
CAPTURE = "P00NSMASHER/capturebrief"
ABVM = "P00NSMASHER/abvmschoolstarworld"


def candidates():
    return [
        work("capturebrief", repository=CAPTURE, owner="portfolio-health-owner",
             resource="1" * 64, fingerprint="1" * 64, priority_tier=0),
        work("permitplate", repository=PLATE, owner="portfolio-health-owner",
             resource="2" * 64, fingerprint="2" * 64, priority_tier=0),
        work("abvm", repository=ABVM, owner="school-data-owner",
             resource="3" * 64, fingerprint="3" * 64, priority_tier=0),
    ]


class RealOwnerCapacityTests(unittest.TestCase):
    def test_distinct_repos_same_owner_cannot_fill_two_active_slots(self):
        rows = candidates()
        winners = set()
        for cycle in range(6):
            out = select_work(rows, cycle=cycle, limit=3, collision_safe=True)
            selected = out["selected"]
            self.assertEqual(len(selected), 2)
            self.assertEqual(len({item["owner"].casefold() for item in selected}), 2)
            self.assertEqual(len({item["repository"].casefold() for item in selected}), 2)
            self.assertEqual(len(out["deferred"]), 1)
            self.assertFalse(out["automatic_execution_authority"])
            winners.update(item["project_id"] for item in selected)
        self.assertEqual(winners, {"capturebrief", "permitplate", "abvm"})

    def test_case_variant_owner_cannot_bypass_single_writer_rule(self):
        first, second, third = candidates()
        second["owner"] = "PORTFOLIO-HEALTH-OWNER"
        out = select_work([first, second, third], cycle=0, limit=3,
                          collision_safe=True)
        self.assertEqual(len(out["selected"]), 2)
        self.assertEqual({row["project_id"] for row in out["selected"]},
                         {"abvm", "capturebrief"})

    def test_legacy_diagnostic_mode_remains_unchanged_and_never_executes(self):
        rows = candidates()
        legacy = select_work(rows, cycle=0, limit=3)
        self.assertEqual(len(legacy["selected"]), 3)
        self.assertFalse(legacy["automatic_execution_authority"])

    def test_actual_registry_maps_permitplate_and_capturebrief_to_same_owner(self):
        def project(name, repository):
            return dict(id=name, repository=repository,
                        repository_revision=SHA,
                        source_check_state="ADVERSE_CHECKS_OBSERVED")
        original = dict(source_sha=SHA, projects=[
            project("capturebrief", CAPTURE),
            project("permitplate", PLATE),
            project("abvm", ABVM),
        ])
        all_winners = set()
        for cycle in range(6):
            result = build_cycle(original, source_sha=SHA, cycle=cycle, now=NOW)
            jobs = result["owner_jobs"]
            self.assertEqual(len(jobs), 2)
            self.assertEqual(len({job["owner"].casefold() for job in jobs}), 2)
            self.assertTrue(all(job["merge_or_deployment_authority"] is False
                                for job in jobs))
            self.assertEqual(result["runtime_actions_executed"], 0)
            self.assertFalse(result["production_accepted"])
            all_winners.update(job["project_id"] for job in jobs)
        self.assertEqual(all_winners, {"capturebrief", "permitplate", "abvm"})


if __name__ == "__main__":
    unittest.main()
