"""Original provider run succession, not a historical red check, controls triage."""
import copy
import unittest

from brain.v11.owner_inbox import digest
from brain.v11.origin_currentness import evaluate, CurrentnessError

REPO = "P00NSMASHER/capturebrief"
SHA = "a" * 40
WORK = "b" * 64
ORIGINAL = 41901326276
WORKFLOW = 93428121


def packet():
    value = {
        "schema_version": 1, "source_sha": "c" * 40,
        "general_cross_project_executor": "NOT_CONFIGURED",
        "production_verified": False, "provider_writes": 0,
        "original_failure_handoffs": [{
            "repository": REPO, "source_sha": SHA,
            "run_id": ORIGINAL, "handoff_id": WORK,
            "original_run_event": "schedule",
            "owner": "retally-product", "project_id": "capturebrief",
        }]
    }
    value["packet_sha256"] = digest(value)
    return value


def original():
    return {
        "id": ORIGINAL, "workflow_id": WORKFLOW,
        "name": "Refresh ABVM school pack",
        "path": ".github/workflows/refresh-abvm-school-pack.yml",
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
        "head_branch": "main", "head_sha": SHA,
        "event": "schedule", "run_attempt": 1,
        "status": "completed", "conclusion": "failure",
    }


def later(n, *, conclusion="success", workflow=WORKFLOW,
          event="schedule", sha=SHA):
    r = original()
    r.update(id=n, workflow_id=workflow, event=event,
             head_sha=sha, conclusion=conclusion)
    return r


class Provider:
    def __init__(self, *, same=None, main_sha=SHA, bad_original=False):
        self.reads = 0
        self.history = list(same or [])
        self.main_sha = main_sha
        self.bad_original = bad_original
        self.routes = []

    def get(self, repository, route):
        self.reads += 1
        self.routes.append((repository, route))
        if repository != REPO:
            raise AssertionError("untrusted repository")
        if route == "actions/runs/" + str(ORIGINAL):
            r = original()
            if self.bad_original:
                r["head_sha"] = "f" * 40
            return r
        if route == "branches/main":
            return {"protected": True, "commit": {"sha": self.main_sha}}
        if route == f"actions/workflows/{WORKFLOW}/runs?per_page=100":
            return {"total_count": len(self.history),
                    "workflow_runs": self.history}
        raise AssertionError("unreviewed route")


class CurrentnessTests(unittest.TestCase):
    def test_later_original_success_is_historical_not_pending_repair(self):
        api = Provider(same=[later(42118307425), later(42027425969)])
        result = evaluate(packet(), api)
        self.assertEqual(result["historical_or_changed"], 1)
        self.assertEqual(result["reproduction_candidates"], 0)
        self.assertEqual(result["provider_reads"], 3)
        row = result["items"][0]
        self.assertEqual(row["status"],
            "LATER_SAME_SOURCE_WORKFLOW_SUCCESS_ORIGINAL_FAILURE_HISTORICAL")
        self.assertEqual(row["latest_run_id"], 42118307425)
        self.assertFalse(row["writer_authorized"])
        self.assertFalse(row["live_repair_verified"])
        self.assertEqual(result["live_repairs_verified"], 0)
        self.assertEqual(result["provider_writes"], 0)
        token = result["verdict_sha256"]
        self.assertEqual(digest({k:v for k,v in result.items()
                                 if k!="verdict_sha256"}), token)

    def test_newer_failed_same_workflow_cannot_be_hidden_by_old_success(self):
        api = Provider(same=[later(42118307425, conclusion="failure"),
                             later(42027425969, conclusion="success")])
        row = evaluate(packet(), api)["items"][0]
        self.assertEqual(row["status"], "LATEST_SAME_SOURCE_WORKFLOW_NOT_SUCCESS")
        self.assertTrue(row["reproduction_candidate"])
        self.assertFalse(row["root_cause_verified"])

    def test_mixed_workflow_inventory_fails_closed_not_actionable(self):
        # Workflow-specific GitHub inventory must reject foreign workflow rows
        # instead of treating a corrupt provider response as no later run.
        api = Provider(same=[later(42118307425, workflow=WORKFLOW+1),
                             later(42118307423, sha="f"*40)])
        row = evaluate(packet(), api)["items"][0]
        self.assertEqual(row["status"], "CURRENTNESS_UNVERIFIED")
        self.assertEqual(row["reason"], "CURRENTNESS_WORKFLOW_INVENTORY_MISMATCH")
        self.assertFalse(row["reproduction_candidate"])
        self.assertIsNone(row["latest_run_id"])

    def test_later_same_source_cross_event_green_is_hold_not_patch_authority(self):
        # Real regression: PermitPlate push source-health failed (41813490059)
        # and the identical source-health workflow succeeded via schedule
        # (42087457417) on the same SHA. Different triggers are not identical
        # execution evidence, so hold/recheck rather than falsely mark fixed
        # or propose a new repair from the superseded failure.
        inp = packet()
        inp["original_failure_handoffs"][0]["original_run_event"] = "push"
        inp["packet_sha256"] = digest({
            k: v for k, v in inp.items() if k != "packet_sha256"})

        class CrossEvent(Provider):
            def get(self, repository, route):
                run = super().get(repository, route)
                if route == "actions/runs/" + str(ORIGINAL):
                    run["event"] = "push"
                return run

        provider = CrossEvent(same=[later(ORIGINAL + 100, event="schedule")])
        result = evaluate(inp, provider)
        row = result["items"][0]
        self.assertEqual(row["status"],
                         "LATER_SAME_SOURCE_CROSS_EVENT_SUCCESS_RECHECK_HOLD")
        self.assertEqual(row["latest_run_id"], ORIGINAL + 100)
        self.assertEqual(result["reproduction_candidates"], 0)
        self.assertEqual(result["historical_or_changed"], 0)
        self.assertFalse(row["writer_authorized"])
        self.assertFalse(row["live_repair_verified"])
        self.assertEqual(result["provider_writes"], 0)

    def test_cross_event_green_cannot_mask_later_same_event_failure(self):
        inp = packet()
        inp["original_failure_handoffs"][0]["original_run_event"] = "push"
        inp["packet_sha256"] = digest({
            k: v for k, v in inp.items() if k != "packet_sha256"})

        class CrossEvent(Provider):
            def get(self, repository, route):
                run = super().get(repository, route)
                if route == "actions/runs/" + str(ORIGINAL):
                    run["event"] = "push"
                return run

        provider = CrossEvent(same=[
            later(ORIGINAL + 200, event="schedule"),
            later(ORIGINAL + 150, event="push", conclusion="failure")])
        result = evaluate(inp, provider)
        self.assertEqual(result["items"][0]["status"],
                         "LATEST_SAME_SOURCE_WORKFLOW_NOT_SUCCESS")
        self.assertTrue(result["items"][0]["reproduction_candidate"])

    def test_failed_cross_event_attempt_is_not_a_false_hold(self):
        inp = packet()
        inp["original_failure_handoffs"][0]["original_run_event"] = "push"
        inp["packet_sha256"] = digest({
            k: v for k, v in inp.items() if k != "packet_sha256"})

        class CrossEvent(Provider):
            def get(self, repository, route):
                run = super().get(repository, route)
                if route == "actions/runs/" + str(ORIGINAL):
                    run["event"] = "push"
                return run

        api = CrossEvent(same=[later(ORIGINAL + 100, event="schedule",
                                     conclusion="failure")])
        row = evaluate(inp, api)["items"][0]
        self.assertEqual(row["status"], "NO_LATER_MATCHING_COMPLETED_RUN")
        self.assertTrue(row["reproduction_candidate"])

    def test_source_drift_stops_without_sampling_run_list(self):
        api = Provider(same=[later(42118307425)], main_sha="f"*40)
        row = evaluate(packet(), api)["items"][0]
        self.assertEqual(row["status"],
                         "SOURCE_CHANGED_ORIGINAL_FAILURE_HISTORICAL")
        self.assertFalse(row["reproduction_candidate"])
        self.assertEqual(api.reads, 2)

    def test_forged_original_or_unknown_provider_is_not_success(self):
        api = Provider(same=[later(42118307425)], bad_original=True)
        row = evaluate(packet(), api)["items"][0]
        self.assertEqual(row["status"], "CURRENTNESS_UNVERIFIED")
        self.assertFalse(row["reproduction_candidate"])
        class Offline(Provider):
            def get(self, repository, route):
                raise CurrentnessError("CURRENTNESS_PROVIDER_UNAVAILABLE")
        result = evaluate(packet(), Offline())
        self.assertEqual(result["items"][0]["status"], "CURRENTNESS_UNVERIFIED")
        self.assertEqual(result["reproduction_candidates"], 0)

    def test_tampered_packet_and_bools_rejected_before_provider_calls(self):
        for changes in (
            {"provider_writes": True},
            {"provider_writes": False},
            {"production_verified": True},
            {"packet_sha256": "0" * 64},
            {"general_cross_project_executor": "FULL_ACCESS"},
        ):
            with self.subTest(changes=changes):
                item = packet()
                item.update(changes)
                api = Provider()
                with self.assertRaises(CurrentnessError):
                    evaluate(item, api)
                self.assertEqual(api.reads, 0)

    def test_bounded_ambiguous_census_is_not_a_false_recovery(self):
        class Bad(Provider):
            def get(self, repository, route):
                if route == f"actions/workflows/{WORKFLOW}/runs?per_page=100":
                    self.reads += 1
                    return {"total_count": True, "workflow_runs": [later(42118307425)]}
                return super().get(repository, route)
        result = evaluate(packet(), Bad())
        self.assertEqual(result["items"][0]["status"], "CURRENTNESS_UNVERIFIED")
        self.assertFalse(result["items"][0]["reproduction_candidate"])


if __name__ == "__main__":
    unittest.main()
