"""Offline adversarial readback tests: no GitHub network, receipts, or writes."""
import copy
import unittest
from unittest.mock import Mock

from brain.v8 import repair_core_origin as repair
from soak_v3.audit import EvidenceError, REQUIRED_STEPS
from verification import source_acceptance_verifier as observer

SOURCE = "a" * 40
CORE = "17"
ROOT = repair.ROOT
JOB_PATH = ROOT + "actions/runs/17/jobs?per_page=100"
OBS_PATH = "/actions/runs/17/jobs?filter=all&per_page=100"


def core_step_doc(names, *, job_id=101, conclusion="success"):
    return {"total_count": 1, "jobs": [{
        "id": job_id, "name": "monitor", "status": "completed",
        "conclusion": conclusion,
        "steps": [{"name": name, "conclusion": result}
                  for name, result in names.items()],
    }]}


def repair_steps():
    return {**{n: "success" for n in repair.MANDATORY},
            "Verify independently signed Cloudflare Cron provenance": "success"}


def observer_steps():
    return {n: "success" for n in REQUIRED_STEPS}


class RepairAPI:
    def __init__(self, snapshots, *, source=SOURCE, event="workflow_dispatch",
                 attempt=1, drift=False):
        self.snapshots = list(snapshots)
        self.calls = []
        self.source = source
        self.event = event
        self.attempt = attempt
        self.drift = drift
        self.jobs_seen = 0

    def __call__(self, path):
        self.calls.append(path)
        if path == ROOT + "branches/main":
            sha = "b" * 40 if self.drift and self.jobs_seen else self.source
            return {"commit": {"sha": sha}}
        if path == ROOT + "actions/runs/17":
            return {
                "name": "brain-cycle-v2",
                "path": ".github/workflows/brain-cycle.yml",
                "repository": {"full_name": repair.REPOSITORY},
                "head_branch": "main", "head_sha": self.source,
                "run_attempt": self.attempt, "status": "completed",
                "conclusion": "success", "event": self.event,
            }
        if path == JOB_PATH:
            self.jobs_seen += 1
            if not self.snapshots:
                raise AssertionError("unbounded job readback")
            return self.snapshots.pop(0)
        raise AssertionError("unreviewed API path: " + path)


class OriginalRepairReadbackTests(unittest.TestCase):
    def test_first_complete_snapshot_does_not_make_unneeded_api_reads(self):
        api = RepairAPI([core_step_doc(repair_steps())])
        pauses = []
        receipt = repair.admit(api, SOURCE, CORE, sleep=pauses.append)
        self.assertEqual(receipt["status"], "ORIGINAL_AUTOMATIC_CORE_AUTHENTICATED")
        self.assertEqual(api.calls.count(JOB_PATH), 1)
        self.assertEqual(api.calls.count(ROOT + "branches/main"), 1)
        self.assertEqual(pauses, [])

    def test_incomplete_snapshot_recovers_without_minting_token(self):
        complete = repair_steps()
        partial = dict(complete)
        partial.pop(next(iter(repair.MANDATORY)))
        api = RepairAPI([core_step_doc(partial), core_step_doc(complete)])
        pauses = []
        receipt = repair.admit(api, SOURCE, CORE, sleep=pauses.append)
        self.assertEqual(receipt["status"], "ORIGINAL_AUTOMATIC_CORE_AUTHENTICATED")
        self.assertFalse(receipt["writer_token_issued"])
        self.assertFalse(receipt["release_authority"])
        self.assertEqual(pauses, [1])
        self.assertEqual(api.calls.count(JOB_PATH), 2)
        self.assertEqual(api.calls.count(ROOT + "branches/main"), 2)

    def test_persistent_incomplete_step_is_a_denial_not_a_receipt(self):
        partial = repair_steps()
        partial.pop(next(iter(repair.MANDATORY)))
        api = RepairAPI([core_step_doc(partial) for _ in range(4)])
        pauses = []
        with self.assertRaisesRegex(repair.OriginError, "MANDATORY_CORE_STEP_INCOMPLETE"):
            repair.admit(api, SOURCE, CORE, sleep=pauses.append)
        self.assertEqual(api.calls.count(JOB_PATH), 4)
        self.assertEqual(pauses, [1, 2, 3])
        self.assertEqual(api.calls.count(ROOT + "branches/main"), 1)

    def test_explicit_adverse_step_never_retries(self):
        adverse = repair_steps()
        adverse[next(iter(repair.MANDATORY))] = "failure"
        api = RepairAPI([core_step_doc(adverse), core_step_doc(repair_steps())])
        pauses = []
        with self.assertRaisesRegex(repair.OriginError, "MANDATORY_CORE_STEP_FAILED"):
            repair.admit(api, SOURCE, CORE, sleep=pauses.append)
        self.assertEqual(pauses, [])
        self.assertEqual(api.calls.count(JOB_PATH), 1)

    def test_changed_original_job_identity_fails_closed(self):
        partial = repair_steps()
        partial.pop(next(iter(repair.MANDATORY)))
        api = RepairAPI([core_step_doc(partial, job_id=101),
                         core_step_doc(repair_steps(), job_id=102)])
        with self.assertRaisesRegex(repair.OriginError, "ORIGINAL_JOB_ID_CHANGED"):
            repair.admit(api, SOURCE, CORE, sleep=lambda _: None)

    def test_source_moved_during_rereads_is_rejected(self):
        incomplete = repair_steps()
        incomplete.pop(next(iter(repair.MANDATORY)))
        api = RepairAPI([core_step_doc(incomplete),
                         core_step_doc(repair_steps())], drift=True)
        with self.assertRaisesRegex(repair.OriginError, "PROTECTED_MAIN_SOURCE_CHANGED"):
            repair.admit(api, SOURCE, CORE, sleep=lambda _: None)

    def test_wrong_attempt_and_push_never_read_job_steps(self):
        for config in ({"attempt": 2}, {"event": "push"}):
            api = RepairAPI([core_step_doc(repair_steps())], **config)
            with self.subTest(config=config), self.assertRaises(repair.OriginError):
                repair.admit(api, SOURCE, CORE, sleep=lambda _: None)
            self.assertNotIn(JOB_PATH, api.calls)


class ObservationAPI:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = []

    def json(self, path):
        self.calls.append(path)
        if path != OBS_PATH or not self.snapshots:
            raise AssertionError("unreviewed or unbounded original API call")
        value = self.snapshots.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class OriginalObserverReadbackTests(unittest.TestCase):
    def test_partial_original_steps_recover_after_one_bounded_reread(self):
        partial = observer_steps()
        partial.pop(next(iter(REQUIRED_STEPS)))
        api = ObservationAPI([core_step_doc(partial),
                              core_step_doc(observer_steps())])
        pauses = []
        job = observer._one_job(api, 17, sleep=pauses.append)
        self.assertEqual(job["id"], 101)
        self.assertEqual(pauses, [1])
        self.assertEqual(api.calls, [OBS_PATH, OBS_PATH])

    def test_explicit_skipped_required_step_does_not_retry(self):
        adverse = observer_steps()
        adverse[next(iter(REQUIRED_STEPS))] = "skipped"
        api = ObservationAPI([core_step_doc(adverse),
                              core_step_doc(observer_steps())])
        pauses = []
        with self.assertRaisesRegex(observer.SourceAcceptanceError,
                                    "required production step failed"):
            observer._one_job(api, 17, sleep=pauses.append)
        self.assertEqual(pauses, [])
        self.assertEqual(len(api.calls), 1)

    def test_persistent_partial_original_denied_after_three_snapshots(self):
        partial = observer_steps()
        partial.pop(next(iter(REQUIRED_STEPS)))
        api = ObservationAPI([core_step_doc(partial) for _ in range(3)])
        pauses = []
        with self.assertRaisesRegex(observer.SourceAcceptanceError,
                                    "still incomplete after bounded rereads"):
            observer._one_job(api, 17, sleep=pauses.append)
        self.assertEqual(pauses, [1, 2])
        self.assertEqual(len(api.calls), 3)

    def test_temporary_unavailability_recovers_without_bypassing_evidence(self):
        api = ObservationAPI([EvidenceError("GITHUB_API_UNAVAILABLE"),
                              core_step_doc(observer_steps())])
        pauses = []
        observer._one_job(api, 17, sleep=pauses.append)
        self.assertEqual(pauses, [1])
        self.assertEqual(len(api.calls), 2)

    def test_exhausted_unavailable_original_fails_closed(self):
        api = ObservationAPI([EvidenceError("GITHUB_API_UNAVAILABLE")
                              for _ in range(3)])
        pauses = []
        with self.assertRaisesRegex(EvidenceError, "GITHUB_API_UNAVAILABLE"):
            observer._one_job(api, 17, sleep=pauses.append)
        self.assertEqual(pauses, [1, 2])
        self.assertEqual(len(api.calls), 3)

    def test_quota_or_forbidden_error_never_retried(self):
        api = ObservationAPI([EvidenceError("GITHUB_API_QUOTA_OR_FORBIDDEN")])
        pauses = []
        with self.assertRaisesRegex(EvidenceError, "GITHUB_API_QUOTA_OR_FORBIDDEN"):
            observer._one_job(api, 17, sleep=pauses.append)
        self.assertEqual(pauses, [])
        self.assertEqual(len(api.calls), 1)

    def test_changed_original_job_id_never_becomes_a_pass(self):
        partial = observer_steps()
        partial.pop(next(iter(REQUIRED_STEPS)))
        api = ObservationAPI([core_step_doc(partial, job_id=101),
                              core_step_doc(observer_steps(), job_id=102)])
        with self.assertRaisesRegex(observer.SourceAcceptanceError,
                                    "original monitor ID changed"):
            observer._one_job(api, 17, sleep=lambda _: None)

    def test_job_failure_is_not_a_transient_readback(self):
        api = ObservationAPI([core_step_doc(observer_steps(), conclusion="failure")])
        with self.assertRaisesRegex(observer.SourceAcceptanceError,
                                    "monitor job failed"):
            observer._one_job(api, 17, sleep=lambda _: None)


if __name__ == "__main__":
    unittest.main()
