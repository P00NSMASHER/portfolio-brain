"""Evidence-only V7 automatic sidecar contracts."""
import json
import tempfile
import unittest
from pathlib import Path
from brain.sidecar import validate_delivery, prepare, summarize, finalize

SOURCE = "a" * 40
STATE = "b" * 40
PARENT = "c" * 40
RUN = "38343224685"

def delivery(**overrides):
    d = {"schema_version": 2, "source_sha": SOURCE,
         "state_parent": PARENT, "state_commit": STATE,
         "run_id": RUN, "run_attempt": "1",
         "workflow": "brain-cycle-v2", "publication_verified": True,
         "execution_boundary": "READ_ONLY_PUBLIC_METADATA", "soak_completed": False}
    d.update(overrides)
    return d

def observation(**overrides):
    d = {"schema_version": 1, "scope": "READ_ONLY_AUTONOMOUS_CHECK_REVALIDATION",
         "source_sha": SOURCE, "state_sequence": 16, "status": "READ_ONLY_REVALIDATION_COMPLETE",
         "eligible_count": 1, "deferred_count": 0, "requests_used": 4,
         "execution_authority": False, "root_cause_verified": False,
         "github_mutations": 0, "events_written": 0, "paid_calls": 0,
         "investigations": [{"repository": "P00NSMASHER/portfolio-brain",
                             "outcome": "OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE",
                             "checks": [{"name": "<script>*evil*", "outcome": "STILL_ADVERSE"}]}]}
    d.update(overrides)
    return d

class SidecarTests(unittest.TestCase):
    def test_exact_delivery_only(self):
        self.assertEqual(validate_delivery(delivery(), SOURCE, RUN, "1"), STATE)
        for bad in ({"state_commit": "../state"}, {"source_sha": PARENT},
                    {"publication_verified": 1}, {"run_id": "2"},
                    {"workflow": "other"}, {"soak_completed": True},
                    {"run_attempt": "2"}, {"schema_version": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_delivery(delivery(**bad), SOURCE, RUN, "1")

    def test_prepare_writes_only_pinned_sha_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src, out = root / "delivery.json", root / "GITHUB_OUTPUT"
            src.write_text(json.dumps(delivery()))
            out.write_text("")
            self.assertEqual(prepare(src, SOURCE, RUN, "1", out), STATE)
            self.assertEqual(out.read_text(), "state_sha=" + STATE + "\n" + "delivery_sha256=" + __import__("hashlib").sha256(src.read_bytes()).hexdigest() + "\n")
            self.assertEqual(json.loads(src.read_text()), delivery())

    def test_sanitized_advisory_outcome_not_incident_or_secret(self):
        result = summarize(observation(), SOURCE, "success", "success", "success", "success")
        self.assertEqual(result["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["observed_outcomes"]["STILL_ADVERSE"], 1)
        self.assertNotIn("evil", json.dumps(result))
        self.assertIs(result["root_cause_verified"], False)
        self.assertEqual(result["github_mutations"], 0)

    def test_any_failed_stage_is_not_complete(self):
        for index in range(4):
            stages = ["success"] * 4
            stages[index] = "failure"
            with self.subTest(stage=index):
                self.assertNotEqual(summarize(observation(), SOURCE, *stages)["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(summarize(None, SOURCE, "failure", "skipped", "skipped", "skipped")["status"],
                         "BLOCKED_NO_VERIFIED_INVESTIGATION")

    def test_deferred_is_partial_and_tampered_is_blocked(self):
        row = observation(status="BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED",
                          eligible_count=3, deferred_count=2)
        self.assertEqual(summarize(row, SOURCE, "success", "success", "success", "failure")["status"],
                         "PARTIAL_READ_ONLY")
        for bad in ({"source_sha": PARENT}, {"execution_authority": True},
                    {"root_cause_verified": True}, {"github_mutations": 1},
                    {"paid_calls": 1}, {"github_mutations": False},
                    {"events_written": False}, {"paid_calls": False}, {"requests_used": 25},
                    {"investigations": [{}] * 4}, {"status": "REVENUE_VERIFIED"}):
            with self.subTest(bad=bad):
                self.assertEqual(summarize(observation(**bad), SOURCE, *["success"] * 4)["status"],
                                 "BLOCKED_NO_VERIFIED_INVESTIGATION")

    def test_finalize_writes_only_sanitized_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_file, out = root / "report.json", root / "sidecar-status.json"
            input_file.write_text(json.dumps(observation()))
            original = input_file.read_bytes()
            result = finalize(input_file, out, SOURCE, *["success"] * 4)
            self.assertEqual(result["status"], "OBSERVED_READ_ONLY")
            self.assertEqual(json.loads(out.read_text()), result)
            self.assertEqual(input_file.read_bytes(), original)
            self.assertNotIn("script", out.read_text())
            input_file.write_text("not json")
            self.assertEqual(finalize(input_file, out, SOURCE, *["success"] * 4)["status"],
                             "BLOCKED_NO_VERIFIED_INVESTIGATION")

class SidecarCliTests(unittest.TestCase):
    def test_real_cli_prepare_and_finalize_are_one_shot_and_sanitized(self):
        import contextlib
        import io
        from brain.sidecar import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivery_file = root / "delivery.json"
            github_output = root / "GITHUB_OUTPUT"
            delivery_file.write_text(json.dumps(delivery()))
            github_output.write_text("")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["prepare", "--delivery", str(delivery_file),
                             "--source-sha", SOURCE, "--run-id", RUN, "--run-attempt", "1",
                             "--github-output", str(github_output)])
            self.assertEqual(code, 0)
            self.assertEqual(github_output.read_text(), "state_sha=" + STATE + "\n" + "delivery_sha256=" + __import__("hashlib").sha256(delivery_file.read_bytes()).hexdigest() + "\n")
            receipt = root / "report.json"
            receipt.write_text(json.dumps(observation()))
            status_file = root / "sidecar-status.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["finalize", "--receipt", str(receipt), "--output", str(status_file),
                             "--source-sha", SOURCE, "--downloaded", "success",
                             "--proven", "success", "--state", "success", "--investigated", "success"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(status_file.read_text())["status"], "OBSERVED_READ_ONLY")
class WorkflowContractTests(unittest.TestCase):
    def test_original_core_writer_bytes_remain_identical(self):
        import hashlib
        src = (Path(__file__).resolve().parents[1] / ".github/workflows/brain-cycle.yml").read_text()
        prefix = src.split("  readonly_investigation:\n", 1)[0].rstrip("\n") + "\n"
        self.assertEqual(hashlib.sha256(prefix.encode()).hexdigest(),
                         "32b92383ccbaeb9b1b2e14ac1ad78418ffd72775724e5784c67dc1ad001df2d4")
    def test_isolated_sidecar_job_does_not_change_parent_writer(self):
        src = (Path(__file__).resolve().parents[1] / ".github/workflows/brain-cycle.yml").read_text()
        self.assertIn('cron: "7,27,47 * * * *"', src)
        self.assertIn("group: brain-v2-state", src)
        self.assertIn("cancel-in-progress: false", src)
        self.assertIn("STATE_DELIVERY_UNVERIFIED", src)
        self.assertIn("  readonly_investigation:\n", src)
        child = src.split("  readonly_investigation:\n", 1)[1]
        self.assertIn("needs: monitor", child)
        self.assertIn("continue-on-error: true", child)
        self.assertIn("contents: read", child)
        self.assertIn("actions: read", child)
        self.assertNotIn("contents: write", child)
        self.assertNotIn("actions: write", child)
        self.assertIn("actions/download-artifact@v4", child)
        self.assertIn("python -m brain.sidecar prepare", child)
        self.assertIn("ref: ${{ steps.source.outputs.state_sha }}", child)
        self.assertIn("python -m brain.investigate", child)
        self.assertIn("timeout --signal=TERM", child)
        self.assertIn("python -m brain.sidecar finalize", child)
        self.assertIn("path: /tmp/brain-v7/sidecar-status.json", child)
        self.assertNotIn("path: /tmp/brain-v7/investigation", child)
        self.assertGreater(src.index("  readonly_investigation:\n"),
                           src.index("      - name: Preserve verifiable execution evidence"))

if __name__ == "__main__":
    unittest.main()
