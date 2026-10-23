"""Network-free hostile early native auto-merge admission tests.

This tests only the reviewed original GitHub provider interface and event
binding. It does not issue checks, invoke GitHub, or change protected main.
The real protected ruleset still requires both issuer-pinned checks at MERGE.
"""
import copy
import unittest

from brain.v9 import guarded_merge as gm
from brain.v9 import guarded_merge_runner as runner
from test_brain_v9_guarded_merge import (
    BASE, HEAD, PR, ROOT, FakeProvider, EventRunnerProvider,
)


def early_fixture(cls=FakeProvider):
    f = cls()
    f.pr["mergeable_state"] = "blocked"
    f.viewer_can_enable = True
    f.viewer_merge_state = "BLOCKED"
    for index, record in enumerate(f.checks["check_runs"]):
        record["id"] = 100 + index
    independent = f.checks["check_runs"][1]
    independent["status"] = "in_progress"
    independent["conclusion"] = None
    if hasattr(f, "open_rows"):
        f.open_rows = [copy.deepcopy(f.pr)]
    return f


class ChangingChecks(FakeProvider):
    def __init__(self):
        super().__init__()
        self.on_first_check_read = None
        self.check_reads = 0

    def get(self, path):
        result = super().get(path)
        if path == ROOT + "commits/" + HEAD + "/check-runs?per_page=100":
            self.check_reads += 1
            if self.check_reads == 1 and self.on_first_check_read is not None:
                self.on_first_check_read(self)
        return result


class NativeEarlyAdmissionTests(unittest.TestCase):
    def hold(self, f, reason, *, with_runner=False):
        with self.assertRaisesRegex(gm.Denied, reason):
            gm.run(f, number=PR, expected_main=BASE, apply=True, early=True)
        self.assertEqual(f.mutations, 0, "Native write preceded completed safety check")

    def test_foundation_success_with_issuer_pending_enrolls_exact_head(self):
        f = early_fixture()
        observed = gm.run(f, number=PR, expected_main=BASE,
                          apply=False, early=True)
        self.assertEqual(observed["status"], "ADMISSIBLE")
        self.assertEqual(f.mutations, 0)
        result = gm.run(f, number=PR, expected_main=BASE, apply=True, early=True)
        self.assertEqual(result["status"], "NATIVE_AUTO_MERGE_ENROLLED")
        self.assertEqual(result["head_sha"], HEAD)
        self.assertFalse(result["merged"])
        self.assertEqual(f.mutations, 1)

    def test_independent_app_check_not_yet_issued_may_be_admitted(self):
        f = early_fixture()
        f.checks["check_runs"].pop(1)
        f.checks["total_count"] = 1
        result = gm.run(f, number=PR, expected_main=BASE, apply=False, early=True)
        self.assertEqual(result["status"], "ADMISSIBLE")
        self.assertEqual(f.mutations, 0)

    def test_both_required_checks_green_is_too_late_for_native_enrollment(self):
        f = early_fixture()
        f.checks["check_runs"][1].update(status="completed", conclusion="success")
        self.hold(f, "EARLY_SECOND_GATE_ALREADY_FINISHED_OR_FAILED")

    def test_second_required_check_failed_cancelled_or_skipped_blocks(self):
        for status, conclusion in (("completed", "failure"),
                                   ("completed", "cancelled"),
                                   ("completed", "skipped"),
                                   ("completed", "neutral"),
                                   ("queued", "failure"), ("waiting", None)):
            with self.subTest(status=status, conclusion=conclusion):
                f = early_fixture()
                f.checks["check_runs"][1].update(status=status, conclusion=conclusion)
                self.hold(f, "EARLY_SECOND_GATE_ALREADY_FINISHED_OR_FAILED")

    def test_foundation_issuer_failure_and_untrusted_check_identity_block(self):
        for key, value, reason in (
            ("app", {"id": 5121826}, "INDEPENDENT_HEAD_CHECK_FAILED"),
            ("head_sha", "f"*40, "INDEPENDENT_HEAD_CHECK_FAILED"),
            ("id", True, "INDEPENDENT_CHECK_ID_UNVERIFIED"),
            ("id", 0, "INDEPENDENT_CHECK_ID_UNVERIFIED"),
        ):
            with self.subTest(key=key, value=value):
                f = early_fixture()
                f.checks["check_runs"][0][key] = value
                self.hold(f, reason)

    def test_foundation_pending_cannot_be_enrollment_authority(self):
        f = early_fixture()
        f.checks["check_runs"][0].update(status="queued", conclusion=None)
        self.hold(f, "INDEPENDENT_HEAD_CHECK_FAILED")

    def test_incomplete_check_census_blocks_before_write(self):
        f = early_fixture()
        f.checks["total_count"] = 3
        self.hold(f, "CHECK_CENSUS_INCOMPLETE")

    def test_clean_behind_and_ambiguous_rest_merge_states_block(self):
        for status in ("clean", "behind", "unknown", "unstable"):
            with self.subTest(status=status):
                f = early_fixture()
                f.pr["mergeable_state"] = status
                self.hold(f, "PR_IDENTITY_OR_MERGEABILITY")

    def test_native_graphql_viewer_must_be_true_and_state_blocked(self):
        f = early_fixture()
        f.viewer_can_enable = False
        self.hold(f, "NATIVE_AUTOMERGE_UNAVAILABLE_ON_CURRENT_PR")
        f = early_fixture()
        f.viewer_merge_state = "CLEAN"
        self.hold(f, "EARLY_NATIVE_MERGE_STATE_NOT_BLOCKED")

    def test_independent_check_finishing_between_two_reads_aborts_write(self):
        f = early_fixture(ChangingChecks)
        f.on_first_check_read = lambda p: p.checks["check_runs"][1].update(
            status="completed", conclusion="success")
        self.hold(f, "EARLY_SECOND_GATE_ALREADY_FINISHED_OR_FAILED")
        self.assertEqual(f.check_reads, 2)

    def test_independent_check_disappearing_between_reads_aborts(self):
        f = early_fixture(ChangingChecks)
        def vanish(p):
            p.checks["check_runs"].pop()
            p.checks["total_count"] = 1
        f.on_first_check_read = vanish
        self.hold(f, "EARLY_FINAL_CHECK_REPLACED_OR_REGRESSED")

    def test_independent_check_identity_change_between_reads_aborts(self):
        f = early_fixture(ChangingChecks)
        f.on_first_check_read = lambda p: p.checks["check_runs"][1].update(id=905)
        self.hold(f, "EARLY_FINAL_CHECK_REPLACED_OR_REGRESSED")

    def test_foundation_check_reissuance_aborts(self):
        f = early_fixture(ChangingChecks)
        f.on_first_check_read = lambda p: p.checks["check_runs"][0].update(id=905)
        self.hold(f, "EARLY_FOUNDATION_CHECK_CHANGED")

    def test_phase1_queued_to_running_is_permitted_if_same_issuer_and_id(self):
        f = early_fixture(ChangingChecks)
        f.checks["check_runs"][1].update(status="queued", conclusion=None)
        f.on_first_check_read = lambda p: p.checks["check_runs"][1].update(
            status="in_progress")
        result = gm.run(f, number=PR, expected_main=BASE, apply=False, early=True)
        self.assertEqual(result["status"], "ADMISSIBLE")
        self.assertEqual(f.mutations, 0)

    def test_phase1_running_to_queued_is_regression(self):
        f = early_fixture(ChangingChecks)
        f.on_first_check_read = lambda p: p.checks["check_runs"][1].update(
            status="queued")
        self.hold(f, "EARLY_FINAL_CHECK_REPLACED_OR_REGRESSED")

    def test_runner_binds_single_matching_event_head(self):
        f = early_fixture(EventRunnerProvider)
        result = runner.dispatch_once(lambda: f, BASE, apply=True,
                                      early=True, event_head=HEAD)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["provider_writes"], 2)
        self.assertEqual(f.mutations, 1)

    def test_unrelated_labelled_pr_head_is_never_admitted(self):
        f = early_fixture(EventRunnerProvider)
        result = runner.dispatch_once(lambda: f, BASE, apply=True,
                                      early=True, event_head="e"*40)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["provider_writes"], 0)
        self.assertEqual(f.mutations, 0)

    def test_missing_or_invalid_head_event_is_denied_without_reads(self):
        for head in (None, "", True, "A"*40, "f"*39, BASE):
            with self.subTest(head=head):
                f = early_fixture(EventRunnerProvider)
                with self.assertRaises(gm.Denied):
                    runner.dispatch_once(lambda: f, BASE, apply=True,
                                         early=True, event_head=head)
                self.assertEqual(f.mutations, 0)
                self.assertEqual(f.calls, [])

    def test_ambiguous_same_head_multiple_prs_are_never_enrolled(self):
        f = early_fixture(EventRunnerProvider)
        second = copy.deepcopy(f.pr)
        second["number"] = PR + 1
        f.open_rows.append(second)
        with self.assertRaisesRegex(gm.Denied, "RUNNER_AMBIGUOUS_EVENT_HEAD"):
            runner.dispatch_once(lambda: f, BASE, apply=True,
                                 early=True, event_head=HEAD)
        self.assertEqual(f.mutations, 0)

    def test_early_mode_requires_exact_reviewed_job_scoped_permissions(self):
        from pathlib import Path
        workflow = Path(".github/workflows/v9-guarded-native-automerge.yml").read_text()
        self.assertIn('workflows: ["foundation-ci"]', workflow)
        self.assertIn("github.event.workflow_run.head_repository.full_name", workflow)
        self.assertIn("github.event.workflow_run.event == 'pull_request'", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertEqual(workflow.count("      contents: write"), 1)
        self.assertEqual(workflow.count("      pull-requests: write"), 1)
        self.assertIn("FOUNDATION_HEAD_SHA: ${{ github.event.workflow_run.head_sha }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("expectedHeadOid", gm.ENABLE_MUTATION)
        for forbidden in ("workflow_dispatch:", "schedule:", "pull_request_target:",
                          "gh pr merge", "merge_pull_request", "id-token: write",
                          "PORTFOLIO_VERIFIER_PRIVATE_KEY"):
            self.assertNotIn(forbidden, workflow)


if __name__ == "__main__":
    unittest.main()
