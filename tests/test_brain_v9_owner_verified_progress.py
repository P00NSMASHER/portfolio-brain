"""Canonical owner-work transitions require original GitHub App/merge evidence."""
from pathlib import Path
import tempfile
import unittest

from brain.v9.batch_queue import BatchQueue, BatchFault, digest
from brain.v9 import reviewed_owner_followthrough as follow


AT = "2026-11-05T21:31:00Z"


class FakeGitHub:
    def __init__(self, *, issuer=5121826, parent=follow.SOURCE_SHA,
                 merged=True, head=follow.CANDIDATE_SHA, bad_census=False):
        self.issuer=issuer
        self.parent=parent
        self.merged=merged
        self.head=head
        self.bad_census=bad_census
        self.reads=0

    def get(self,route):
        self.reads += 1
        if route=="pulls/871":
            return {"number":871,"state":"closed","merged":self.merged,
                    "merged_at":"2026-11-05T21:16:19Z",
                    "head":{"sha":self.head,"repo":{"full_name":follow.REPO}},
                    "base":{"ref":"main","repo":{"full_name":follow.REPO}},
                    "merge_commit_sha":follow.MERGE_SHA}
        if route=="git/commits/"+follow.MERGE_SHA:
            return {"sha":follow.MERGE_SHA,"parents":[{"sha":self.parent}]}
        if route=="commits/"+follow.CANDIDATE_SHA+"/check-runs?per_page=100":
            checks=[{"name":name,"head_sha":follow.CANDIDATE_SHA,
                     "status":"completed","conclusion":"success",
                     "app":{"id":self.issuer if name=="portfolio-phase1-gate" else app}}
                    for name,app in follow.REQUIRED_APPS.items()]
            return {"total_count":3 if self.bad_census else 2,
                    "check_runs":checks}
        raise AssertionError(route)


class OriginalOwnerProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue=BatchQueue(Path(self.temp.name)/"queue.sqlite")
        self.addCleanup(self.queue.close)
        item=dict(project_id="portfolio-brain",
                  repository=follow.REPO,
                  source_sha=follow.SOURCE_SHA,
                  fingerprint=follow.FINGERPRINT,
                  path="repository-observation",
                  owner=follow.EXPECTED_OWNER,
                  priority=2)
        self.wid=self.queue.observe(item,now="2026-11-05T21:00:00Z")
        self.assertEqual(self.wid,follow.WORK_ID)

    def stage(self):
        return self.queue.snapshot()["work"][self.wid]["stage"]

    def progress(self,api=None,budget=3,source=follow.MERGE_SHA):
        return follow.try_progress(self.queue,source_sha=source,now=AT,
                                   budget=budget,api=api)

    def test_reviewed_protected_release_advances_three_genuine_stages_once(self):
        provider=FakeGitHub()
        old=self.queue.checkpoint()
        result=self.progress(provider)
        self.assertEqual(result["status"],
                         "REVIEWED_OWNER_REPAIR_TESTED_FROM_ORIGINAL_GITHUB")
        self.assertEqual(result["transitions"],3)
        self.assertEqual(result["provider_gets"],3)
        self.assertEqual(provider.reads,3)
        self.assertEqual(self.stage(),"TESTED")
        row=self.queue.snapshot()["work"][self.wid]
        self.assertEqual(len(row["evidence"]),3)
        self.assertNotEqual(old,self.queue.checkpoint())
        self.queue.close()
        self.queue=BatchQueue(Path(self.temp.name)/"queue.sqlite")
        second=self.progress(FakeGitHub())
        self.assertEqual(second["status"],"REVIEWED_WORK_ALREADY_TESTED")
        self.assertEqual(second["provider_gets"],0)
        self.assertEqual(second["transitions"],0)
        self.assertEqual(self.stage(),"TESTED")
        self.assertFalse(result["real_world_functionality_verified"])
        self.assertFalse(result["production_accepted"])

    def test_provider_did_not_release_or_report_census_partial(self):
        for kwargs in ({"merged":False},{"bad_census":True},
                       {"parent":"f"*40},{"head":"e"*40}):
            with self.subTest(kwargs=kwargs):
                out=self.progress(FakeGitHub(**kwargs))
                self.assertEqual(out["status"],"ORIGINAL_OWNER_REVIEW_NOT_VERIFIED")
                self.assertEqual(out["transitions"],0)
                self.assertEqual(self.stage(),"OBSERVED")

    def test_float_bool_or_forged_app_does_not_credit_tested(self):
        for app in (5121826.0,True,9999):
            with self.subTest(app=app):
                provider=FakeGitHub(issuer=app)
                out=self.progress(provider)
                self.assertEqual(out["status"],"ORIGINAL_OWNER_REVIEW_NOT_VERIFIED")
                self.assertEqual(self.stage(),"OBSERVED")

    def test_budget_lack_or_same_unreleased_source_preserves_original(self):
        self.assertEqual(self.progress(FakeGitHub(),budget=2)["provider_gets"],0)
        self.assertEqual(self.progress(FakeGitHub(),source=follow.SOURCE_SHA)["transitions"],0)
        self.assertEqual(self.stage(),"OBSERVED")

    def test_active_owner_claim_cannot_be_stolen(self):
        self.queue.claim(self.wid,follow.EXPECTED_OWNER,now="2026-11-05T21:30:00Z")
        out=self.progress(FakeGitHub())
        self.assertEqual(out["status"],"OWNER_WORK_CLAIM_HELD")
        self.assertEqual(out["provider_gets"],0)
        self.assertEqual(self.stage(),"OBSERVED")

    def test_unenrolled_work_missing_is_no_provider_read(self):
        self.queue.close()
        other=BatchQueue(Path(self.temp.name)/"empty.sqlite")
        try:
            out=follow.try_progress(other,source_sha=follow.MERGE_SHA,
                                    now=AT,budget=3,api=FakeGitHub())
            self.assertEqual(out["status"],"NO_REVIEWED_OWNER_WORK_IN_ACTIVE_QUEUE")
            self.assertEqual(out["provider_gets"],0)
        finally:
            other.close()

    def test_credential_transport_has_fixed_route_allowlist(self):
        reader=follow.OriginalGitHub("x"*40)
        with self.assertRaisesRegex(follow.OwnerProofHeld,"ROUTE_DENIED"):
            reader.get("repos/another/private")
        self.assertEqual(reader.reads,0)


if __name__=="__main__":
    unittest.main()
