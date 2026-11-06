"""Live failure: a busy repo's first 100 runs cannot cover an older source failure."""
import unittest
from brain.v11.owner_inbox import digest
from brain.v11.origin_currentness import evaluate

REPO = "P00NSMASHER/permitplate-nyc"
SOURCE = "b8d27a8cf2064cd679dfd188b5529ee254187d5c"
RUN = 41890592940
WORKFLOW = 363438370
PATH = ".github/workflows/current-graph.yml"
TITLE = "PermitPlate current graph replay"


def packet():
    value = {
        "schema_version": 1,
        "source_sha": "a" * 40,
        "general_cross_project_executor": "NOT_CONFIGURED",
        "provider_writes": 0, "production_verified": False,
        "original_failure_handoffs": [{
            "repository": REPO, "source_sha": SOURCE,
            "run_id": RUN, "handoff_id": "c" * 64,
            "original_run_event": "schedule",
        }],
    }
    value["packet_sha256"] = digest(value)
    return value


def original(run_id=RUN, *, source=SOURCE, conclusion="failure",
             workflow_id=WORKFLOW, event="schedule"):
    return {
        "id": run_id, "workflow_id": workflow_id,
        "name": TITLE, "path": PATH,
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
        "head_branch": "main", "head_sha": source,
        "event": event, "run_attempt": 1,
        "status": "completed", "conclusion": conclusion,
    }


class Provider:
    def __init__(self, rows=(), count=None):
        self.rows = list(rows)
        self.count = len(self.rows) if count is None else count
        self.reads = 0
        self.routes = []

    def get(self, repo, route):
        if repo != REPO:
            raise AssertionError("Unrecognized repository")
        self.routes.append(route)
        self.reads += 1
        if route == f"actions/runs/{RUN}":
            return original()
        if route == "branches/main":
            return {"protected": True, "commit": {"sha": SOURCE}}
        if route in ("actions/runs?per_page=100",
                     f"actions/workflows/{WORKFLOW}/runs?per_page=100"):
            return {"total_count": self.count, "workflow_runs": self.rows}
        raise AssertionError("Unapproved read route: " + route)


class OriginalWindowTests(unittest.TestCase):
    def test_busy_repo_truncation_is_not_a_new_actionable_repair(self):
        # Live repository had 100 returned runs from Nov 6 but original
        # graph failure was Nov 4. The original could not be in that window.
        later = [original(RUN + 1000 + i, source="d" * 40)
                 for i in range(100)]
        api = Provider(later, count=24000)
        result = evaluate(packet(), api)
        item = result["items"][0]
        self.assertEqual(item["status"], "CURRENTNESS_UNVERIFIED")
        self.assertFalse(item["reproduction_candidate"])
        self.assertEqual(item.get("reason"), "CURRENTNESS_RUN_WINDOW_INCOMPLETE")
        self.assertEqual(result["reproduction_candidates"], 0)
        self.assertEqual(result["provider_writes"], 0)
        self.assertEqual(api.reads, 3)

    def test_use_original_workflow_id_to_avoid_unrelated_run_churn(self):
        api = Provider()
        evaluate(packet(), api)
        self.assertEqual(api.routes, [
            f"actions/runs/{RUN}", "branches/main",
            f"actions/workflows/{WORKFLOW}/runs?per_page=100",
        ])

    def test_genuinely_complete_no_success_can_reach_reproduction_review(self):
        result = evaluate(packet(), Provider(rows=[], count=0))
        item = result["items"][0]
        self.assertEqual(item["status"], "NO_LATER_MATCHING_COMPLETED_RUN")
        self.assertTrue(item["reproduction_candidate"])
        self.assertFalse(item["writer_authorized"])
        self.assertFalse(item["root_cause_verified"])

    def test_later_same_workflow_success_is_historical_only(self):
        result = evaluate(packet(), Provider([
            original(RUN + 2, conclusion="success"), original(),
        ], count=2))
        item = result["items"][0]
        self.assertEqual(item["status"],
                         "LATER_SAME_SOURCE_WORKFLOW_SUCCESS_ORIGINAL_FAILURE_HISTORICAL")
        self.assertFalse(item["reproduction_candidate"])
        self.assertFalse(item["live_repair_verified"])

    def test_truncated_window_cannot_promote_observed_newer_failure(self):
        later = [original(RUN + 1000 + i, source="d" * 40)
                 for i in range(99)]
        later.insert(0, original(RUN + 2000, conclusion="failure"))
        result = evaluate(packet(), Provider(later, count=10000))
        self.assertEqual(result["items"][0]["status"], "CURRENTNESS_UNVERIFIED")
        self.assertEqual(result["items"][0]["reason"],
                         "CURRENTNESS_RUN_WINDOW_INCOMPLETE")
        self.assertEqual(result["reproduction_candidates"], 0)

    def test_wrong_workflow_in_filtered_inventory_is_unverified(self):
        result = evaluate(packet(), Provider([
            original(RUN + 10, workflow_id=WORKFLOW + 1)
        ], count=1))
        self.assertEqual(result["items"][0]["status"], "CURRENTNESS_UNVERIFIED")
        self.assertFalse(result["items"][0]["reproduction_candidate"])

    def test_original_in_first_page_allows_partial_older_history(self):
        # Older unrelated runs beyond original need not be fetched: the
        # original row is in the sampled page, after the newer success.
        result = evaluate(packet(), Provider([
            original(RUN + 1, conclusion="success"), original(),
        ], count=200))
        self.assertEqual(result["items"][0]["status"],
                         "LATER_SAME_SOURCE_WORKFLOW_SUCCESS_ORIGINAL_FAILURE_HISTORICAL")
        self.assertEqual(result["reproduction_candidates"], 0)


if __name__ == "__main__":
    unittest.main()
