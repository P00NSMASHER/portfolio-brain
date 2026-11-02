"""Hostile original-run provenance trials for the read-only unattended intake."""
import copy
import tempfile
from pathlib import Path
import unittest

from brain.v10 import engineering_factory as factory
from brain.v11 import failure_triage as triage

MAIN = "a" * 40
RUN = 12345678
GOOD_ORIGIN = {"name": "Verify independently signed Cloudflare Cron provenance",
               "status": "completed", "conclusion": "success"}
BAD_STEP = {"name": "Bounded public code and opportunity research",
            "status": "completed", "conclusion": "failure"}


class OriginalGitHub:
    def __init__(self):
        self.calls = []
        self.current = MAIN
        self.protected = True
        self.event = "workflow_dispatch"
        self.run_attempt = 1
        self.conclusion = "failure"
        self.run_sha = MAIN
        self.run_id = RUN
        self.count = 1
        self.monitors = 1
        self.job_attempt = 1
        self.job_status = "completed"
        self.original_steps = [copy.deepcopy(GOOD_ORIGIN), copy.deepcopy(BAD_STEP)]
        self.original_repository = factory.REPOSITORY

    def request(self, method, route, payload=None):
        self.calls.append((method, route, payload))
        if method != "GET" or payload is not None:
            raise AssertionError("unexpected provider mutation")
        if route == "branches/main":
            return {"protected": self.protected, "commit": {"sha": self.current}}
        if route == "actions/runs/" + str(RUN):
            return {"id": self.run_id, "name": "brain-cycle-v2",
                    "path": ".github/workflows/brain-cycle.yml",
                    "repository": {"full_name": self.original_repository},
                    "head_sha": self.run_sha, "head_branch": "main",
                    "run_attempt": self.run_attempt, "event": self.event,
                    "status": "completed", "conclusion": self.conclusion}
        if route == "actions/runs/" + str(RUN) + "/jobs?per_page=100":
            rows = [{"id": 90000, "name": "monitor", "run_id": RUN,
                     "run_attempt": self.job_attempt, "head_sha": MAIN,
                     "status": self.job_status, "conclusion": self.conclusion,
                     "steps": copy.deepcopy(self.original_steps)}
                    for _ in range(self.monitors)]
            return {"total_count": self.count, "jobs": rows}
        raise AssertionError("unexpected route " + route)


class OriginalFailureIntakeTests(unittest.TestCase):
    def setUp(self):
        self.api = OriginalGitHub()

    def review(self):
        return triage.intake(self.api, run_id=RUN, source_sha=MAIN)

    def test_original_signed_dispatch_failure_is_classified_not_fixed(self):
        x = self.review()
        self.assertEqual(x["status"],
                         "ORIGINAL_AUTOMATIC_FAILURE_CLASSIFIED_NOT_REPAIRED")
        self.assertEqual(x["source_run_id"], RUN)
        self.assertEqual(x["source_sha"], MAIN)
        self.assertEqual(x["failed_stage_families"], ["PUBLIC_RESEARCH"])
        self.assertFalse(x["candidate_patch_prepared"])
        self.assertFalse(x["draft_pr_created"])
        self.assertFalse(x["merged"])
        self.assertEqual(x["provider_writes"], 0)
        self.assertEqual(len(x["fingerprint_sha256"]), 64)
        self.assertTrue(all(method == "GET" for method,_,_ in self.api.calls))

    def test_native_schedule_original_failure_is_legitimate_without_clock_step(self):
        self.api.event = "schedule"
        self.api.original_steps = [copy.deepcopy(BAD_STEP)]
        self.assertEqual(self.review()["original_event"], "schedule")

    def test_manual_dispatch_without_proven_signed_origin_is_denied(self):
        self.api.original_steps = [copy.deepcopy(BAD_STEP)]
        with self.assertRaisesRegex(factory.FactoryError, "AUTOMATIC_ORIGIN"):
            self.review()
        self.api.original_steps.insert(0, dict(GOOD_ORIGIN, conclusion="skipped"))
        with self.assertRaisesRegex(factory.FactoryError, "AUTOMATIC_ORIGIN"):
            self.review()

    def test_non_original_replay_or_forged_repository_denied(self):
        for field, fake in (("run_attempt", 2),
                            ("run_id", RUN+1),
                            ("original_repository", "attacker/repository"),
                            ("conclusion", "success"),
                            ("run_sha", "b"*40)):
            with self.subTest(field=field):
                self.api = OriginalGitHub()
                setattr(self.api, field, fake)
                with self.assertRaisesRegex(factory.FactoryError,
                                            "NO_ORIGINAL_FAILED_CORE"):
                    self.review()

    def test_incomplete_jobs_ambiguous_monitor_and_wrong_job_attempt_denied(self):
        for field, value, reason in (
                ("count", 2, "JOB_CENSUS"),
                ("monitors", 2, "JOB_CENSUS"),
                ("monitors", 0, "JOB_CENSUS"),
                ("job_attempt", 2, "JOB_IDENTITY"),
                ("job_status", "in_progress", "JOB_IDENTITY")):
            with self.subTest(field=field, value=value):
                self.api = OriginalGitHub()
                setattr(self.api, field, value)
                with self.assertRaisesRegex(factory.FactoryError, reason):
                    self.review()

    def test_protected_source_drift_or_unprotected_main_denied(self):
        self.api.current = "c" * 40
        with self.assertRaisesRegex(factory.FactoryError, "PROTECTED_MAIN_MOVED"):
            self.review()
        self.api = OriginalGitHub()
        self.api.protected = False
        with self.assertRaisesRegex(factory.FactoryError, "PROTECTED_MAIN_MOVED"):
            self.review()

    def test_provider_step_names_never_enter_sanitized_receipt(self):
        self.api.original_steps = [
            copy.deepcopy(GOOD_ORIGIN),
            {"name": "Failed private-data password=TOPSECRET",
             "conclusion": "failure"},
        ]
        output = factory.canonical(self.review())
        self.assertNotIn("TOPSECRET", output)
        self.assertIn("UNCLASSIFIED_ORIGINAL_STEP", output)

    def test_failed_original_absent_failed_step_never_claims_diagnosis(self):
        self.api.original_steps = [copy.deepcopy(GOOD_ORIGIN)]
        with self.assertRaisesRegex(factory.FactoryError, "NO_FAILED_STEP"):
            self.review()

    def test_explicit_output_is_exclusive_and_private_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "receipt.json"
            data = self.review()
            triage._write_exclusive(path, data)
            self.assertIn("NOT_REPAIRED", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            with self.assertRaises(FileExistsError):
                triage._write_exclusive(path, data)


if __name__ == "__main__":
    unittest.main()
