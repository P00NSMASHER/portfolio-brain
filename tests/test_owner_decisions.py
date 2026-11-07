import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.v11.owner_decisions import REGISTRY, changes, incidents, observe, registered_rows, strict_load
from brain.v11.owner_inbox import digest
from tests.test_brain_v11_currentness_window import Provider, REPO, RUN, SOURCE, PATH, original
from tests.test_brain_v11_owner_inbox import report


class DecisionTests(unittest.TestCase):
    def test_changed_target_or_problem_notifies_once_after_legacy_digest(self):
        base = {"id": "stable", "state": "BLOCKED", "repository": "P00NSMASHER/a", "problem": "storage"}
        old_keys = ("state", "owner_decision", "owner", "existing_pr", "request", "acceptance",
                    "chat_approval", "approved_scope", "proof")
        with sqlite3.connect(":memory:") as db:
            changes(db, [base])
            db.execute("UPDATE owner_decision SET material=?", (digest([base.get(k) for k in old_keys]),))
            # A new source read alone stays quiet across the schema upgrade.
            row = dict(base, head="f" * 40)
            self.assertEqual(changes(db, [row])["decisions"], [])
            for updates in ({"problem": "ingress"}, {"repository": "P00NSMASHER/b"}):
                row.update(updates)
                self.assertEqual(changes(db, [row])["decisions"], [row])
                self.assertEqual(changes(db, [row])["decisions"], [])

    def test_observed_incident_recovery_and_recurrence(self):
        doc = report()
        job = doc["owner_jobs"][0]
        job["source_sha"] = SOURCE
        proof = job["failure_evidence"]
        proof.update(run_id=RUN, source_sha=SOURCE, workflow_path=PATH, job_name="verify",
                     url=f"https://github.com/{REPO}/actions/runs/{RUN}/job/{proof['job_id']}")
        failed = Provider([original()])
        green = Provider([original(), original(RUN+1, conclusion="success")])
        rows = list(incidents(doc, failed, 0))
        self.assertEqual(len(rows), 1)
        with sqlite3.connect(":memory:") as db:
            self.assertEqual(changes(db, rows)["decisions"], rows)
            recovered = list(incidents(doc, green, 0))
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["state"], "ORIGINAL_FAILURE_HISTORICAL")
            self.assertFalse(recovered[0]["behavior_verified"])
            self.assertEqual(changes(db, recovered)["decisions"], recovered)
            self.assertEqual(changes(db, recovered)["decisions"], [])
            # Losing sight of the later green cannot re-open the old failure.
            self.assertEqual(changes(db, incidents(doc, failed, 0))["decisions"], [])
            proof.update(run_id=RUN+2, url=f"https://github.com/{REPO}/actions/runs/{RUN+2}/job/{proof['job_id']}")
            class Recurrence(Provider):
                def get(self, repo, route):
                    if route == f"actions/runs/{RUN+2}":
                        self.reads += 1
                        return original(RUN+2)
                    return super().get(repo, route)
            recurring = list(incidents(doc, Recurrence([original(RUN+2)]), 0))
            self.assertEqual(len(recurring), 1)
            self.assertEqual(changes(db, recurring)["decisions"], recurring)

    def test_restart_dedup_and_three_changed_items(self):
        rows = [{"id": str(n), "state": "BLOCKED", "owner_decision": "AWAITING_CHAT_DECISION"}
                for n in range(4)]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.sqlite"
            with sqlite3.connect(path) as db:
                self.assertEqual(len(changes(db, rows)["decisions"]), 3)
            with sqlite3.connect(path) as db:
                self.assertEqual(changes(db, [])["decisions"], [])
                self.assertEqual([r["id"] for r in changes(db, rows)["decisions"]], ["3"])
                rows[0]["head"] = "different-source-same-block"
                self.assertEqual(changes(db, rows)["decisions"], [])
                rows[0]["state"] = "MERGED_AWAITING_TARGET_PROOF"
                self.assertEqual([r["id"] for r in changes(db, rows)["decisions"]], ["0"])

    def test_historical_or_truncated_permitplate_failure_stays_quiet(self):
        doc = report()
        job = doc["owner_jobs"][0]
        job["source_sha"] = SOURCE
        proof = job["failure_evidence"]
        proof.update(run_id=RUN, source_sha=SOURCE, workflow_path=PATH, job_name="verify",
                     url=f"https://github.com/{REPO}/actions/runs/{RUN}/job/{proof['job_id']}")
        for api in (Provider([original(), original(RUN+1, conclusion="success")]),
                    Provider([original(RUN+1, source="e"*40)], count=500)):
            with sqlite3.connect(":memory:") as db:
                self.assertEqual(changes(db, incidents(doc, api, 0))["decisions"], [])
            self.assertEqual(api.reads, 3)
        self.assertEqual(len(list(incidents(doc, Provider([original()]), 0))), 1)

    def test_large_registry_rotates_and_keeps_declined_records(self):
        base = strict_load(REGISTRY)["records"][0]
        records = [dict(base, id=f"target-{n}") for n in range(14)]
        records[-1]["owner_decision"] = "DECLINED"
        with patch("brain.v11.owner_decisions.observe", side_effect=lambda r, api: dict(r)) as reader:
            for index in range(13):
                rows = registered_rows(records, None, index, {})
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows["target-13"]["owner_decision"], "DECLINED")
        self.assertEqual({c.args[0]["id"] for c in reader.call_args_list},
                         {r["id"] for r in records[:-1]})

    def test_target_postrelease_requires_original_behavior_at_exact_merge(self):
        record = strict_load(REGISTRY)["records"][0]
        repo = record["repository"]
        head, merge = record["original_head"], "c" * 40
        pr = {"number": 1093, "state": "closed", "merged": True, "merge_commit_sha": merge,
              "merged_at": "2026-11-07T00:00:00Z", "merged_by": {"login": "release-owner"},
              "user": {"login": "pr-author"}, "base": {"repo": {"full_name": repo}, "ref": "main"},
              "head": {"repo": {"full_name": repo}, "sha": head}}
        proof = {"run_id": 123, "workflow_id": 456, "path": ".github/workflows/postrelease.yml",
                 "job": "production-probe", "behavior_step": "Observe exhausted bucket writes",
                 "reviewed_workflow_blob": "b" * 40}
        link = {"number": 1093, "url": "https://api.github.com/repos/" + repo + "/pulls/1093"}
        class Provider:
            original_link = link
            current_link = link
            current_workflow = record["workflow_id"]
            checks = []
            def get(self, repository, route):
                self_test.assertEqual(repository, repo)
                if route == "pulls/1093":
                    return pr
                if "/check-runs?" in route:
                    return {"total_count": len(self.checks), "check_runs": self.checks}
                if route == "actions/runs/4567":
                    return {"id": 4567, "head_sha": head, "event": "pull_request",
                            "repository": {"full_name": repo}, "head_repository": {"full_name": repo},
                            "workflow_id": self.current_workflow, "path": record["workflow_path"],
                            "pull_requests": [self.current_link]}
                if route.startswith("contents/"):
                    return {"path": proof["path"], "sha": proof["reviewed_workflow_blob"]}
                first = str(record["original_run"]) in route
                ident = record["original_run"] if first else proof["run_id"]
                sha = head if first else merge
                conclusion = "failure" if first else "success"
                if "/jobs?" in route:
                    return {"total_count": 1, "jobs": [{"id": record["original_job"] if first else 11,
                        "name": record["job"] if first else proof["job"], "run_id": ident,
                        "run_attempt": 1, "head_sha": sha, "conclusion": conclusion,
                        "html_url": "https://github.com/" + repo + "/actions/runs/123/job/11",
                        "steps": [{"name": record["failed_step"] if first else proof["behavior_step"],
                                   "conclusion": conclusion, "status": "completed"}]}]}
                return {"id": ident, "repository": {"full_name": repo}, "head_repository": {"full_name": repo},
                        "pull_requests": [self.original_link] if first else [],
                        "head_sha": sha, "event": "pull_request" if first else "push", "head_branch": "main",
                        "workflow_id": record["workflow_id"] if first else proof["workflow_id"],
                        "path": record["workflow_path"] if first else proof["path"],
                        "status": "completed", "run_attempt": 1, "conclusion": conclusion,
                        "created_at": "2026-11-07T01:00:00Z"}
        self_test = self
        self.assertEqual(observe(record, Provider())["state"], "MERGED_AWAITING_TARGET_PROOF")
        enrolled = dict(record, postrelease_workflow=proof)
        self.assertEqual(observe(enrolled, Provider())["state"], "MERGED_AWAITING_TARGET_PROOF")
        proof["acceptance_sha256"] = digest([record[k] for k in
                                            ("id", "repository", "existing_pr", "problem", "acceptance")])
        respecified = dict(enrolled, acceptance="A different production budget reduced latency by 99%.")
        held = observe(respecified, Provider())
        self.assertEqual(held["state"], "MERGED_AWAITING_TARGET_PROOF")
        self.assertFalse(held["behavior_verified"])
        self.assertEqual(observe(enrolled, Provider())["delivered_by"], "release-owner")
        wrong = copy.deepcopy(enrolled)
        wrong["postrelease_workflow"]["reviewed_workflow_blob"] = "e" * 40
        self.assertFalse(observe(wrong, Provider())["behavior_verified"])
        foreign = dict(link, number=1122)
        api = Provider()
        api.original_link = foreign
        self.assertEqual(observe(enrolled, api)["state"], "EVIDENCE_UNAVAILABLE")

        pr.update(state="open", merged=False)
        api = Provider()
        self.assertEqual(observe(record, api)["state"], "OPEN_AWAITING_TARGET_CHECK")
        check = {"id": 9876, "head_sha": head, "name": record["job"], "app": {"id": 15368},
                 "pull_requests": [link], "status": "completed", "conclusion": "success",
                 "details_url": f"https://github.com/{repo}/actions/runs/4567/job/9876"}
        api.checks = [check]
        current = observe(record, api)
        self.assertEqual(current["state"], "OPEN_WITH_EXISTING_OWNER")
        self.assertNotEqual(current["request"], record["request"])
        self.assertEqual(current["current_check"], check["details_url"])
        check["conclusion"] = "failure"
        self.assertEqual(observe(record, api)["state"], "BLOCKED")
        check["status"] = "in_progress"
        self.assertEqual(observe(record, api)["state"], "OPEN_AWAITING_TARGET_CHECK")
        check.update(status="completed", conclusion="success")
        api.current_workflow += 1
        self.assertNotEqual(observe(record, api)["state"], "OPEN_WITH_EXISTING_OWNER")
        api.current_workflow = record["workflow_id"]
        api.current_link = foreign
        self.assertNotEqual(observe(record, api)["state"], "OPEN_WITH_EXISTING_OWNER")

    def test_scheduled_writers_held_and_recovery_still_enabled(self):
        directory = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        core = (directory / "brain-cycle.yml").read_text()
        self.assertNotIn("python -m brain evolve", core)
        self.assertNotIn("pull-requests: write", core)
        self.assertIn("python -m brain.v11.owner_decisions", core)
        scoped = (directory / "v8-scoped-repair.yml").read_text()
        self.assertNotIn("python -m brain.v11.owner_executor", scoped)
        self.assertIn("false && github.repository", scoped.split("  propose-only:", 1)[1].split("runs-on:", 1)[0])
        self.assertEqual(scoped.count("false && steps.request.outputs.artifact"), 2)
        self.assertEqual(scoped.count("false && steps.recipe.outputs.eligible"), 2)
        self.assertIn("python -m brain.hunter_schedule_watchdog --dispatch", scoped)
        native = (directory / "v9-guarded-native-automerge.yml").read_text()
        self.assertNotIn("pull-requests: write", native)
        self.assertNotIn("contents: write", native)
        self.assertEqual(native.count("if: ${{ false"), 2)
        foundation = (directory / "foundation-ci.yml").read_text()
        self.assertIn("startsWith(github.head_ref, 'factory/auto-repair-')", foundation)
        self.assertIn("startsWith(github.ref_name, 'factory/auto-repair-')", foundation)
        self.assertLess(foundation.index("Hold reserved"), foundation.index("actions/checkout"))
