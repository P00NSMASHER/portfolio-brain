"""Real registry focus prevents stale specialist handoffs after the task reset."""
import copy
import unittest

from brain.v8.engineering import ACTIVE_OWNER_PROJECTS, build_cycle


SHA = "a" * 40
NOW = "2026-10-16T07:00:00Z"
PROJECTS = {
    "portfolio-brain": "P00NSMASHER/portfolio-brain",
    "abvm": "P00NSMASHER/abvmschoolstarworld",
    "retally": "P00NSMASHER/github-value-hunt-ledger",
    "research-labs": "P00NSMASHER/github-value-hunt-ledger",
    "permitplate": "P00NSMASHER/permitplate-nyc",
    "capturebrief": "P00NSMASHER/capturebrief",
    "product-factory": "P00NSMASHER/x402-product-factory",
    "pips-classroom": "P00NSMASHER/PipsQuestWorld",
    "trading-platform": "P00NSMASHER/trading-platform",
}
DEFERRED = {"product-factory", "pips-classroom", "trading-platform"}


def project(pid, *, check_state="ADVERSE_CHECKS_OBSERVED"):
    return dict(id=pid, repository=PROJECTS[pid],
                repository_revision=SHA, source_check_state=check_state)


class OwnerFocusTests(unittest.TestCase):
    def test_observed_deferred_projects_have_no_stale_specialist_jobs(self):
        rows = [project(pid) for pid in sorted(DEFERRED)]
        before = copy.deepcopy(rows)
        result = build_cycle(dict(source_sha=SHA, projects=rows),
                             source_sha=SHA, cycle=0, now=NOW)
        self.assertEqual(len(result["project_maps"]), 9)
        self.assertEqual(result["owner_jobs"], [])
        self.assertEqual(result["coverage"]["observed"], 0)
        self.assertEqual({r["project_id"] for r in result["outside_owner_scope"]},
                         DEFERRED)
        self.assertTrue(all(r["source_sha"] == SHA for r in
                            result["outside_owner_scope"]))
        self.assertFalse(result["automatic_execution_authority"])
        self.assertFalse(result["production_accepted"])
        self.assertEqual(result["runtime_actions_executed"], 0)
        self.assertEqual(rows, before)

    def test_all_six_focus_projects_are_kept_and_have_one_repo_owner(self):
        self.assertEqual(ACTIVE_OWNER_PROJECTS, set(PROJECTS) - DEFERRED)
        rows = [project(pid) for pid in PROJECTS]
        output = build_cycle(dict(source_sha=SHA, projects=rows),
                             source_sha=SHA, cycle=0, now=NOW)
        self.assertEqual(len(output["work_items"]), len(ACTIVE_OWNER_PROJECTS))
        self.assertEqual(len(output["owner_jobs"]), 4)
        self.assertEqual(len({r["repository"].casefold()
                              for r in output["owner_jobs"]}), 4)
        self.assertEqual({r["project_id"] for r in output["outside_owner_scope"]},
                         DEFERRED)
        self.assertEqual(len({r["owner"].casefold() for r in output["owner_jobs"]}), 4)
        self.assertEqual(output["coverage"]["registered"], 9)
        self.assertTrue(all(not r["merge_or_deployment_authority"]
                            for r in output["owner_jobs"]))

    def test_missing_active_source_remains_explicit_gap_not_invented_work(self):
        rows = [dict(project("abvm"), repository_revision=None),
                project("product-factory")]
        output = build_cycle(dict(source_sha=SHA, projects=rows),
                             source_sha=SHA, cycle=0, now=NOW)
        self.assertEqual(output["owner_jobs"], [])
        gaps = {r["project_id"] for r in output["coverage_gaps"]}
        self.assertIn("abvm", gaps)
        self.assertTrue(gaps.issubset(ACTIVE_OWNER_PROJECTS))
        self.assertTrue(gaps.isdisjoint(DEFERRED))
        self.assertEqual({r["project_id"] for r in output["outside_owner_scope"]},
                         {"product-factory", "pips-classroom", "trading-platform"})
        self.assertFalse(output["automatic_execution_authority"])


if __name__ == "__main__":
    unittest.main()
