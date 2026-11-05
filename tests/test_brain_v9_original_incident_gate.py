"""Production original-main incident admission: no inferred or feature-only repairs."""
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from brain.v9.batch_cycle import run_cycle, _is_trusted_native_core
from brain.v9.batch_provider import GitHubOriginalReader
from brain.v9.batch_queue import BatchQueue, BatchFault


SOURCE="a"*40
TARGET="b"*40
REPO="P00NSMASHER/abvmschoolstarworld"
NOW="2026-11-05T21:00:00Z"
LATER="2026-11-05T21:30:00Z"
URL=f"https://github.com/{REPO}/actions/runs/123/job/456"


def report(check_state="ADVERSE_CHECKS_OBSERVED", requests=22, with_origin=True):
    row=dict(id="abvm",repository=REPO,repository_revision=TARGET,
             source_check_state=check_state)
    value=dict(schema_version=1,source_sha=SOURCE,canonical_pending_events=0,
               operation=dict(name="projects",requests=requests),projects=[row])
    if with_origin:
        value["repositories"]=[dict(
            repository=REPO,head_sha=TARGET,default_branch="main",
            data_kind="ACTUAL",checks=[dict(
                head_sha=TARGET,status="completed",conclusion="failure",
                url=URL)])]
    return value


class OriginalIncidentGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue=BatchQueue(Path(self.temp.name)/"state.sqlite")
        self.addCleanup(self.queue.close)

    def call(self,doc=None,*,reader=None,now=NOW):
        return run_cycle(doc or report(),self.queue,source_sha=SOURCE,cycle=2,
                         now=now,original_incident_gate=True,failure_reader=reader)

    def test_no_work_for_inconclusive_source_without_spending_gets(self):
        for state in ("SOURCE_UNOBSERVED","NO_CHECK_RUNS_OBSERVED",
                      "CHECK_EVIDENCE_UNVERIFIED",
                      "INCOMPLETE_OR_INCONCLUSIVE_CHECKS_OBSERVED",
                      "NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL"):
            with self.subTest(state=state):
                before=self.queue.checkpoint()
                result=self.call(report(state))
                self.assertEqual(result["owner_jobs"],[])
                self.assertEqual(result["original_main_incidents_queued"],0)
                self.assertEqual(result["failure_evidence_gets"],0)
                self.assertEqual(before,self.queue.checkpoint())
                self.assertEqual(len(result["nonactionable_source_signals"]),1)
                self.assertFalse(result["production_accepted"])

    def test_adverse_aggregate_without_original_failed_job_is_not_a_repair(self):
        before=self.queue.checkpoint()
        result=self.call(report(with_origin=False))
        self.assertEqual(result["owner_jobs"],[])
        self.assertEqual(result["failure_evidence_gets"],0)
        self.assertEqual(before,self.queue.checkpoint())
        self.assertEqual(result["nonactionable_source_signals"][0]["disposition"],
                         "NO_ORIGINAL_MAIN_FAILURE_PROOF_NO_WORK")

    def test_original_two_reads_admit_one_failure_not_root_cause_or_release(self):
        reader=GitHubOriginalReader(max_gets=2)
        def confirmed(instance,repo,sha,run_id,job_id):
            self.assertEqual((repo,sha,run_id,job_id),(REPO,TARGET,123,456))
            instance.used_gets+=2
            return dict(status="ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED",
                        source_sha=sha,run_id=run_id,job_id=job_id,
                        failed_steps=[dict(number=1,name="Failed real main test")],
                        root_cause_verified=False)
        with patch.object(GitHubOriginalReader,"failed_main_job",confirmed):
            result=self.call(reader=reader)
        self.assertEqual(result["failure_evidence_gets"],2)
        self.assertEqual(result["total_project_gets"],24)
        self.assertEqual(result["original_main_incidents_queued"],1)
        self.assertEqual(result["metrics"]["stages"]["OBSERVED"],1)
        self.assertEqual(len(result["owner_jobs"]),1)
        handoff=result["owner_jobs"][0]
        self.assertEqual(handoff["incident_classification"],
                         "ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED_ROOT_CAUSE_OPEN")
        self.assertFalse(handoff["automatic_execution_authority"])
        self.assertFalse(handoff["failure_evidence"]["root_cause_verified"])
        self.assertFalse(result["production_accepted"])
        # No repeated append on same source, preserving original proof.
        reader2=GitHubOriginalReader(max_gets=2)
        with patch.object(GitHubOriginalReader,"failed_main_job",confirmed):
            again=self.call(reader=reader2,now=LATER)
        self.assertEqual(len(again["owner_jobs"]),1)
        self.assertEqual(again["metrics"]["stages"]["OBSERVED"],1)
        self.assertEqual(self.queue.checkpoint()["sequence"],1)

    def test_failed_provider_or_stale_original_cannot_poison_queue(self):
        reader=GitHubOriginalReader(max_gets=2)
        def denied(instance,repo,sha,run_id,job_id):
            instance.used_gets+=2
            raise BatchFault("ORIGINAL_FAILED_MAIN_RUN_UNVERIFIED")
        with patch.object(GitHubOriginalReader,"failed_main_job",denied):
            result=self.call(reader=reader)
        self.assertEqual(result["failure_evidence_gets"],2)
        self.assertEqual(result["owner_jobs"],[])
        self.assertEqual(result["original_main_incidents_queued"],0)
        self.assertEqual(result["metrics"]["work_items"],0)
        self.assertEqual(self.queue.checkpoint()["sequence"],0)

    def test_unfunded_original_proof_never_enqueues_aggregate_adverse(self):
        outcome=self.call(report(requests=23))
        self.assertEqual(outcome["failure_evidence_gets"],0)
        self.assertEqual(outcome["owner_jobs"],[])
        self.assertEqual(outcome["total_project_gets"],23)
        self.assertEqual(self.queue.checkpoint()["sequence"],0)

    def test_reported_source_mismatch_denied_before_mutation(self):
        value=report();value["source_sha"]="f"*40
        with self.assertRaisesRegex(BatchFault,"CYCLE_SOURCE_INVALID"):
            self.call(value)
        self.assertEqual(self.queue.checkpoint()["sequence"],0)

    def test_reject_nonstrict_boolean_gate(self):
        with self.assertRaisesRegex(BatchFault,"INCIDENT_GATE_MODE_INVALID"):
            run_cycle(report(),self.queue,source_sha=SOURCE,cycle=2,
                      now=NOW,original_incident_gate=1)
        self.assertEqual(self.queue.checkpoint()["sequence"],0)

    def test_only_original_main_core_selects_new_admission_contract(self):
        args=Namespace(command="cycle",db=Path("state/state.sqlite"),
                       expected_sha=SOURCE)
        env=dict(GITHUB_WORKFLOW="brain-cycle-v2",
                 GITHUB_REPOSITORY="P00NSMASHER/portfolio-brain",
                 GITHUB_REF="refs/heads/main",
                 GITHUB_EVENT_NAME="workflow_dispatch",
                 GITHUB_RUN_ATTEMPT="1",
                 GITHUB_RUN_ID="42108594544",
                 GITHUB_SHA=SOURCE,
                 BRAIN_SOURCE_SHA=SOURCE)
        with patch.dict("os.environ",env,clear=True):
            self.assertTrue(_is_trusted_native_core(args))
        for key,invalid in [
            ("GITHUB_WORKFLOW","other-workflow"),
            ("GITHUB_REPOSITORY","elsewhere/repo"),
            ("GITHUB_REF","refs/heads/feature"),
            ("GITHUB_EVENT_NAME","pull_request"),
            ("GITHUB_RUN_ATTEMPT","2"),
            ("GITHUB_RUN_ID","anything"),
            ("GITHUB_SHA","c"*40),
            ("BRAIN_SOURCE_SHA","c"*40)
        ]:
            with self.subTest(key=key),patch.dict("os.environ",
                                                 {**env,key:invalid},clear=True):
                self.assertFalse(_is_trusted_native_core(args))


if __name__=="__main__":
    unittest.main()
