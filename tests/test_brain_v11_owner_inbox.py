"""Owner inbox never turns research, forged provider evidence or green CI into work."""
import json
from pathlib import Path
import tempfile
import unittest

from brain.v11.owner_inbox import build, strict_load, write_atomic, InboxError

SOURCE = "a" * 40
PROJECT = "permitplate"
REPOSITORY = "P00NSMASHER/permitplate-nyc"
TARGET = "b" * 40


def job():
    run_id, job_id = 42102005351, 127506921271
    return {
        "automatic_execution_authority": False,
        "durable_claim_required_before_mutation": True,
        "failure_evidence": {
            "event": "schedule",
            "failed_steps": [{"name": "Run no-send scoring promotion canary", "number": 6}],
            "job_id": job_id,
            "root_cause_verified": False,
            "run_id": run_id,
            "source_sha": TARGET,
            "status": "ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED",
            "url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/job/{job_id}",
        },
        "incident_classification": "ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED_ROOT_CAUSE_OPEN",
        "owner": "retally-product",
        "path": "repository-observation",
        "priority": 1,
        "project_id": PROJECT,
        "repository": REPOSITORY,
        "source_check_state": "ADVERSE_CHECKS_OBSERVED",
        "source_reobservation_required": True,
        "source_sha": TARGET,
        "stage": "OBSERVED",
        "verifier": "retally-qa",
        "work_id": "c" * 64,
    }


def report():
    return {
        "schema_version": 1,
        "status": "DURABLE_OWNER_QUEUE_UPDATED_NOT_RELEASED",
        "incident_gate": "ORIGINAL_MAIN_FAILURE_PROOF_REQUIRED",
        "source_sha": SOURCE,
        "production_accepted": False,
        "automatic_execution_authority": False,
        "provider_writes": 0,
        "queue_checkpoint": {
            "chain_hash": "d" * 64, "work_hash": "e" * 64, "sequence": 729
        },
        "metrics": {"stages": {"OBSERVED": 151}},
        "owner_jobs": [job()]
    }


class OwnerInboxTests(unittest.TestCase):
    def test_real_original_failure_is_one_nonprivileged_repro_handoff(self):
        result = build(report(), expected_source=SOURCE)
        self.assertEqual(result["observed_not_necessarily_actionable"], 151)
        self.assertEqual(len(result["original_failure_handoffs"]), 1)
        selected = result["original_failure_handoffs"][0]
        self.assertEqual(selected["repository"], REPOSITORY)
        self.assertEqual(selected["run_id"], 42102005351)
        self.assertEqual(selected["failed_steps"][0]["number"], 6)
        self.assertFalse(selected["technical_repair_verified"])
        self.assertFalse(selected["cross_project_code_write_authorized"])
        self.assertTrue(selected["source_recheck_required"])
        self.assertEqual(result["general_cross_project_executor"],
                         "AUTHORIZED_OWNER_WORKER_CONFIGURED")
        self.assertEqual(result, build(report(), expected_source=SOURCE))
        self.assertEqual(len(result["packet_sha256"]), 64)

    def test_no_original_incident_means_no_owner_job(self):
        source = report()
        source["owner_jobs"] = []
        value = build(source, expected_source=SOURCE)
        self.assertEqual(value["original_failure_handoffs"], [])
        self.assertEqual(value["next_action"], "NO_CONFIRMED_INCIDENT_FOR_OWNER")
        self.assertEqual(value["observed_not_necessarily_actionable"], 151)

    def test_reject_untrusted_source_checks_and_fabricated_stage(self):
        for key, value in [
            ("incident_classification", "ADVERSE_CHECK_HISTORY_PRODUCTION_UNVERIFIED"),
            ("automatic_execution_authority", True),
            ("stage", "TESTED"),
            ("priority", True),
            ("durable_claim_required_before_mutation", False),
        ]:
            with self.subTest(key=key):
                source = report()
                source["owner_jobs"][0][key] = value
                with self.assertRaises(InboxError):
                    build(source, expected_source=SOURCE)

    def test_reject_forged_provider_source_url_and_status(self):
        for key, value in [
            ("source_sha", SOURCE),
            ("url", "https://evil.example.invalid/attack"),
            ("status", "SYNTHETIC_FAILURE"),
            ("root_cause_verified", True),
            ("job_id", 0),
        ]:
            with self.subTest(key=key):
                source = report()
                source["owner_jobs"][0]["failure_evidence"][key] = value
                with self.assertRaises(InboxError):
                    build(source, expected_source=SOURCE)

    def test_reject_duplicate_handoff_and_source_report_drift(self):
        source = report()
        source["owner_jobs"].append(job())
        with self.assertRaisesRegex(InboxError, "INBOX_DUPLICATE_INCIDENT"):
            build(source, expected_source=SOURCE)
        source = report()
        source["source_sha"] = TARGET
        with self.assertRaisesRegex(InboxError, "INBOX_NOT_AUTHENTICATED"):
            build(source, expected_source=SOURCE)

    def test_private_atomic_output_restart_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "owner.json"
            first = build(report(), expected_source=SOURCE)
            write_atomic(path, first)
            self.assertEqual(strict_load(path), first)
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            with self.assertRaisesRegex(InboxError, "INBOX_OUTPUT_UNSAFE"):
                write_atomic(path, first)
            self.assertEqual(strict_load(path), first)

    def test_reject_duplicate_json_and_nonfinite_without_writes(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.json"
            path.write_text('{"owner_jobs":[],"owner_jobs":[]}', encoding="utf-8")
            with self.assertRaisesRegex(InboxError, "INBOX_DUPLICATE_KEY"):
                strict_load(path)
            path.write_text('{"x":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(InboxError, "INBOX_NONFINITE"):
                strict_load(path)


if __name__ == "__main__":
    unittest.main()
