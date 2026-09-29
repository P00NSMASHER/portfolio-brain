from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepairCandidateWorkflowTests(unittest.TestCase):
    def test_scheduler_remains_read_only_and_does_not_call_write_workflow(self):
        body = (ROOT / ".github/workflows/portfolio-autonomous-scheduler.yml").read_text()
        lowered = body.lower()
        self.assertIn("contents: read", lowered)
        self.assertIn("actions: read", lowered)
        self.assertNotIn("contents: write", lowered)
        self.assertNotIn("pull-requests: write", lowered)
        self.assertNotIn("repair-candidate-cycle.yml", body)
        self.assertNotIn("workflow_call", lowered)

    def test_repair_cycle_is_event_driven_from_successful_main_scheduler(self):
        body = (ROOT / ".github/workflows/repair-candidate-cycle.yml").read_text()
        self.assertIn("workflow_run:", body)
        self.assertIn('workflows: ["portfolio-autonomous-scheduler"]', body)
        self.assertIn("types: [completed]", body)
        self.assertIn('branches: ["main"]', body)
        self.assertNotIn("\n  schedule:", body)
        self.assertNotIn("\n  workflow_call:", body)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", body)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", body)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", body)

    def test_triggering_scheduler_artifact_and_source_revision_are_exactly_bound(self):
        body = (ROOT / ".github/workflows/repair-candidate-cycle.yml").read_text()
        self.assertIn("run-id: ${{ github.event.workflow_run.id }}", body)
        self.assertIn("github-token: ${{ github.token }}", body)
        self.assertIn("REPAIR_BASE_SHA: ${{ github.event.workflow_run.head_sha }}", body)
        self.assertIn("ref: ${{ env.REPAIR_BASE_SHA }}", body)
        self.assertIn("--base-sha \"$REPAIR_BASE_SHA\"", body)

    def test_no_repair_means_no_paid_planning_or_downstream_jobs(self):
        body = (ROOT / ".github/workflows/repair-candidate-cycle.yml").read_text()
        self.assertIn("has_work: ${{ steps.select.outputs.has_work }}", body)
        self.assertIn("steps.select.outputs.has_work == 'true'", body)
        self.assertIn("needs.plan-build.outputs.has_work == 'true'", body)
        select = body.index("Select one queued repair")
        cost = body.index("Reserve bounded repair-cycle wrapper")
        self.assertLess(select, cost)
        self.assertIn("Fail closed when paid admission blocks selected repair work", body)

    def test_model_planning_is_in_paid_lane_and_replay_submit_finalize_are_workload_gated(self):
        body = (ROOT / ".github/workflows/repair-candidate-cycle.yml").read_text()
        self.assertIn("group: portfolio-cost-governed-autonomy", body)
        self.assertIn("cost_governor.workflow_gate preflight", body)
        self.assertIn("cost_governor.workflow_gate finalize", body)
        for job in ("replay", "submit", "finalize"):
            self.assertIn(f"--job-id {job}", body)
        self.assertGreaterEqual(body.count("workload_control.workload_gate preflight"), 3)

    def test_write_authority_exists_only_in_isolated_submit_job(self):
        body = (ROOT / ".github/workflows/repair-candidate-cycle.yml").read_text()
        self.assertEqual(body.count("contents: write"), 1)
        submit = body.split("\n  submit:", 1)[1].split("\n  finalize-scheduler:", 1)[0]
        self.assertIn("contents: write", submit)
        self.assertNotIn("pull-requests: write", submit)
        self.assertNotIn("deployments: write", submit)
        self.assertNotIn("id-token: write", submit)
        self.assertNotIn("gh pr", submit.lower())
        self.assertNotIn("merge_pull", submit.lower())

    def test_remote_submission_does_not_claim_review_pr_merge_or_deploy(self):
        body = (ROOT / ".github/workflows/repair-candidate-cycle.yml").read_text()
        self.assertIn("software_factory.candidate_submitter", body)
        self.assertIn("software_factory.complete_repair_work", body)
        self.assertNotIn("software_factory.github_executor", body)
        policy = json.loads((ROOT / "operations/OPERATING_MODE_POLICY.json").read_text())
        event = policy["event_driven_workflows"]["repair-candidate-cycle"]
        self.assertIn("workflow_run:portfolio-autonomous-scheduler", event["trigger"])
        self.assertIn("no verification, PR, merge, or deployment", event["purpose"])
        self.assertNotIn("repair-candidate-cycle", policy["reusable_nonrecurring_workflows"])

    def test_governance_entries_cover_every_repair_cycle_lane(self):
        workload = json.loads((ROOT / "workload_control/WORKLOAD_POLICY.json").read_text())
        for key in (
            "repair-candidate-cycle::replay",
            "repair-candidate-cycle::submit",
            "repair-candidate-cycle::finalize",
        ):
            self.assertIn(key, workload["services"])
        cost = json.loads((ROOT / "cost_governor/COST_GOVERNOR_POLICY.json").read_text())
        self.assertIn("repair-candidate-cycle::plan-build", cost["workflow_job_ceilings"])
        self.assertIn("repair-candidate-cycle", cost["managed_workflow_names"])


if __name__ == "__main__":
    unittest.main()
