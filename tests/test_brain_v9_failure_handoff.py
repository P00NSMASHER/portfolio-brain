"""Verify an owner handoff cannot promote a PR check or consume unreserved reads."""
from copy import deepcopy
import json
from io import BytesIO
import unittest

from brain.v9.batch_cycle import attach_original_failure
from brain.v9.batch_provider import GitHubOriginalReader

REPO = "P00NSMASHER/portfolio-brain"
SHA = "a" * 40
URL = f"https://github.com/{REPO}/actions/runs/13/job/27"


class Response(BytesIO):
    status = 200


class OriginalJobs:
    def __init__(self):
        self.calls = []
        self.run = dict(id=13, head_sha=SHA, head_branch="main", repository={"full_name": REPO},
                        head_repository={"full_name": REPO}, event="push", run_attempt=1,
                        status="completed", conclusion="failure")
        self.job = dict(id=27, run_id=13, head_sha=SHA, head_branch="main", run_attempt=1,
                        status="completed", conclusion="failure", html_url=URL,
                        steps=[dict(number=38, name="Run regression tests",
                                    status="completed", conclusion="failure")])
        self.count = 1

    def open(self, req, *, timeout):
        self.calls.append(req.full_url)
        assert req.get_method() == "GET" and req.full_url.startswith(f"https://api.github.com/repos/{REPO}/actions/runs/13")
        data = ({"jobs": [self.job], "total_count": self.count} if req.full_url.endswith("jobs?per_page=100")
                else self.run)
        return Response(json.dumps(data).encode())


class FailureHandoffTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = dict(repository=REPO, head_sha=SHA, default_branch="main", data_kind="ACTUAL",
                             checks=[dict(status="completed", conclusion="failure", head_sha=SHA, url=URL)])
        self.work = dict(repository=REPO, source_sha=SHA, source_check_state="ADVERSE_CHECKS_OBSERVED")
        self.origin = OriginalJobs()

    def attach(self, budget=2):
        reader = GitHubOriginalReader(max_gets=2)
        reader._opener = self.origin
        job = deepcopy(self.work)
        reads = attach_original_failure([job], [self.snapshot], budget=budget, cycle=0, reader=reader)
        return job, reads

    def test_exact_original_job_and_step_corroborated_in_two_gets(self):
        job, reads = self.attach()
        self.assertEqual(reads, 2)
        evidence = job['failure_evidence']
        self.assertEqual(evidence['failed_steps'], [dict(number=38, name="Run regression tests")])
        self.assertEqual(evidence['url'], URL)
        self.assertFalse(evidence['root_cause_verified'])

    def test_same_sha_feature_branch_rerun_or_wrong_job_cannot_confirm(self):
        for obj, key, changed in ((self.origin.run, 'head_branch', 'feature'),
                                  (self.origin.run, 'event', 'pull_request'),
                                  (self.origin.run, 'run_attempt', 2),
                                  (self.origin.job, 'html_url', URL + '/moved'),
                                  (self.origin.job, 'head_sha', 'b'*40)):
            original = obj[key]
            with self.subTest(key=key):
                obj[key] = changed
                job, _ = self.attach()
                self.assertEqual(job['failure_evidence']['status'], 'ORIGINAL_MAIN_JOB_UNVERIFIED')
            obj[key] = original
        self.origin.count = 2
        self.assertEqual(self.attach()[0]['failure_evidence']['status'], 'ORIGINAL_MAIN_JOB_UNVERIFIED')

    def test_unfunded_read_keeps_pointer_and_untrusted_url_has_no_effect(self):
        job, reads = self.attach(budget=1)
        self.assertEqual(reads, 0)
        self.assertEqual(job['observed_failed_job_url'], URL)
        self.assertNotIn('failure_evidence', job)
        self.snapshot['checks'][0]['url'] = 'https://attacker.invalid/' + URL
        job, reads = self.attach()
        self.assertEqual((job, reads), (self.work, 0))
        self.assertEqual(self.origin.calls, [])
