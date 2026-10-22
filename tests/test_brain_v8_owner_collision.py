"""Owner handoffs must not issue competing writers for a shared repository."""
import copy
import unittest

from brain.core import BrainError
from brain.v8.engineering import build_cycle
from brain.v8.planning import select_work
from test_brain_v8_contracts import work


SHA = "a" * 40
NOW = "2026-10-16T07:00:00Z"
SHARED = "P00NSMASHER/github-value-hunt-ledger"
ABVM = "P00NSMASHER/abvmschoolstarworld"


def candidates():
    return [
        work("research-labs", repository=SHARED, resource="1" * 64,
             fingerprint="1" * 64, priority_tier=0),
        work("retally", repository=SHARED, resource="2" * 64,
             fingerprint="2" * 64, priority_tier=0),
        work("abvm", repository=ABVM, resource="3" * 64,
             fingerprint="3" * 64, priority_tier=1),
    ]


class OwnerLaneCollisionTests(unittest.TestCase):
    def test_shared_repository_never_consumes_two_owner_slots(self):
        rows = candidates()
        before = copy.deepcopy(rows)
        for cycle, winner in ((0, "research-labs"), (1, "retally"),
                              (2, "research-labs"), (3, "retally")):
            with self.subTest(cycle=cycle):
                result = select_work(rows, cycle=cycle, limit=2,
                                     collision_safe=True)
                chosen = result["selected"]
                self.assertEqual([r["project_id"] for r in chosen],
                                 [winner, "abvm"])
                self.assertEqual(len({r["repository"].casefold()
                                      for r in chosen}), 2)
                self.assertEqual(len(result["deferred"]), 1)
                self.assertFalse(result["automatic_execution_authority"])
        self.assertEqual(rows, before)

    def test_shared_resource_across_repositories_is_deferred_and_backfilled(self):
        a, b, c = candidates()
        b = work("other", repository="P00NSMASHER/other",
                 resource=a["resource"], fingerprint="4" * 64, priority_tier=0)
        result = select_work([a, b, c], cycle=0, limit=2,
                             collision_safe=True)
        self.assertEqual({r["project_id"] for r in result["selected"]},
                         {"research-labs", "abvm"})
        self.assertEqual([r["project_id"] for r in result["deferred"]],
                         ["other"])

    def test_repository_case_aliases_do_not_escape_writer_exclusion(self):
        a, b, c = candidates()
        b = work("retally", repository="p00nsmasher/GITHUB-VALUE-HUNT-LEDGER",
                 resource="5" * 64, fingerprint="5" * 64, priority_tier=0)
        result = select_work([a, b, c], cycle=0, limit=3,
                             collision_safe=True)
        self.assertEqual(len(result["selected"]), 2)
        self.assertEqual(len(result["deferred"]), 1)

    def test_collisions_do_not_erase_priority_or_change_legacy_diagnostics(self):
        rows = candidates()
        original = select_work(rows, cycle=0, limit=2)
        self.assertEqual({r["project_id"] for r in original["selected"]},
                         {"research-labs", "retally"})
        for invalid in ("yes", 1, None, [], {}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                    BrainError, "V8_PLAN_COLLISION_POLICY_INVALID"):
                select_work(rows, cycle=0, limit=2, collision_safe=invalid)

    def test_engineering_owner_bridge_is_collision_safe_by_default(self):
        def project(ident, repo):
            return {"id": ident, "repository": repo,
                    "repository_revision": SHA,
                    "source_check_state": "ADVERSE_CHECKS_OBSERVED"}
        report = {"source_sha": SHA, "projects": [
            project("retally", SHARED),
            project("research-labs", SHARED),
            project("abvm", ABVM),
        ]}
        for cycle in (0, 1):
            with self.subTest(cycle=cycle):
                output = build_cycle(report, source_sha=SHA,
                                     cycle=cycle, now=NOW)
                jobs = output["owner_jobs"]
                self.assertEqual(len(jobs), 2)
                self.assertEqual(len({job["repository"].casefold()
                                      for job in jobs}), 2)
                self.assertEqual({job["project_id"] for job in jobs}
                                 & {"retally", "research-labs"},
                                 {("research-labs" if cycle == 0 else "retally")})
                self.assertTrue(all(not job["merge_or_deployment_authority"]
                                    for job in jobs))
                self.assertEqual(output["runtime_actions_executed"], 0)
                self.assertFalse(output["production_accepted"])


if __name__ == "__main__":
    unittest.main()
