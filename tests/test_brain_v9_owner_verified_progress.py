"""Canonical owner-work stage transitions require original protected GitHub proof."""
from pathlib import Path
import tempfile
import unittest

from brain.v9.batch_queue import BatchQueue
from brain.v9 import reviewed_owner_followthrough as follow

AT = "2026-11-05T21:51:00Z"
CANDIDATE = "d" * 40
MERGE = "c" * 40


class FakeGitHub:
    def __init__(self, *, issuer=5121826, parent=follow.SOURCE_SHA,
                 merged=True, head=CANDIDATE, bad_census=False, bad_base=False):
        self.issuer=issuer
        self.parent=parent
        self.merged=merged
        self.head=head
        self.bad_census=bad_census
        self.bad_base=bad_base
        self.reads=0

    def get(self,route):
        self.reads += 1
        if route=="pulls/873":
            return {"number":873,"state":"closed","merged":self.merged,
                    "merged_at":"2026-11-05T21:45:00Z",
                    "head":{"sha":self.head,"repo":{"full_name":follow.REPO}},
                    "base":{"ref":"feature" if self.bad_base else "main",
                            "repo":{"full_name":follow.REPO}},
                    "merge_commit_sha":MERGE}
        if route=="git/commits/"+MERGE:
            return {"sha":MERGE,"parents":[{"sha":self.parent}]}
        if route=="commits/"+self.head+"/check-runs?per_page=100":
            checks=[{"name":name,"head_sha":self.head,
                     "status":"completed","conclusion":"success",
                     "app":{"id":self.issuer if name=="portfolio-phase1-gate"
                            else app}}
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
        item=dict(project_id="portfolio-brain",repository=follow.REPO,
                  source_sha=follow.SOURCE_SHA,fingerprint=follow.FINGERPRINT,
                  path="repository-observation",owner=follow.EXPECTED_OWNER,
                  priority=2)
        self.wid=self.queue.observe(item,now="2026-11-05T21:30:00Z")
        self.assertEqual(self.wid,follow.WORK_ID)

    def stage(self):
        return self.queue.snapshot()["work"][self.wid]["stage"]

    def progress(self,api=None,budget=3,source=MERGE):
        return follow.try_progress(self.queue,source_sha=source,now=AT,
                                   budget=budget,api=api)

    def test_reviewed_protected_release_advances_three_genuine_stages_once(self):
        provider=FakeGitHub()
        old=self.queue.checkpoint()
        result=self.progress(provider)
        self.assertEqual(result["status"],
                         "REVIEWED_OWNER_REPAIR_TESTED_FROM_ORIGINAL_GITHUB")
        self.assertEqual(result["reviewed_pr"],873)
        self.assertEqual(result["protected_merge_sha"],MERGE)
        self.assertEqual(result["candidate_head_sha"],CANDIDATE)
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

    def test_missing_original_proof_preserves_observed(self):
        for kwargs in ({"merged":False},{"bad_census":True},
                       {"parent":"f"*40},{"bad_base":True},
                       {"head":"e"*40}):
            with self.subTest(kwargs=kwargs):
                # Valid-looking but another head is still a valid source if
                # independently verified. For an invalid head, use nonhex.
                if "head" in kwargs:
                    kwargs={"head":"not-a-commit"}
                out=self.progress(FakeGitHub(**kwargs))
                self.assertEqual(out["status"],"ORIGINAL_OWNER_REVIEW_NOT_VERIFIED")
                self.assertEqual(out["transitions"],0)
                self.assertEqual(self.stage(),"OBSERVED")

    def test_forged_check_issuers_denied(self):
        for app in (5121826.0, True, 9999):
            with self.subTest(app=app):
                out=self.progress(FakeGitHub(issuer=app))
                self.assertEqual(out["status"],"ORIGINAL_OWNER_REVIEW_NOT_VERIFIED")
                self.assertEqual(self.stage(),"OBSERVED")

    def test_budget_lack_or_unreleased_source_never_mutates(self):
        self.assertEqual(self.progress(FakeGitHub(),budget=2)["provider_gets"],0)
        self.assertEqual(self.progress(FakeGitHub(),source=follow.SOURCE_SHA)["transitions"],0)
        self.assertEqual(self.stage(),"OBSERVED")

    def test_active_owner_claim_cannot_be_reused(self):
        self.queue.claim(self.wid,follow.EXPECTED_OWNER,now="2026-11-05T21:50:00Z")
        out=self.progress(FakeGitHub())
        self.assertEqual(out["status"],"OWNER_WORK_CLAIM_HELD")
        self.assertEqual(out["provider_gets"],0)
        self.assertEqual(self.stage(),"OBSERVED")

    def test_unenrolled_queue_missing_skips_all_provider_reads(self):
        self.queue.close()
        other=BatchQueue(Path(self.temp.name)/"empty.sqlite")
        try:
            out=follow.try_progress(other,source_sha=MERGE,
                                    now=AT,budget=3,api=FakeGitHub())
            self.assertEqual(out["status"],"NO_REVIEWED_OWNER_WORK_IN_ACTIVE_QUEUE")
            self.assertEqual(out["provider_gets"],0)
        finally:
            other.close()

    def test_route_allowlist_rejects_arbitrary_remote(self):
        reader=follow.OriginalGitHub("x"*40)
        for path in ("repos/another/private","pulls/872",
                     "git/commits/something-invalid",
                     "commits/danger/check-runs?per_page=100"):
            with self.subTest(path=path),self.assertRaisesRegex(
                follow.OwnerProofHeld,"ROUTE_DENIED"):
                reader.get(path)
        self.assertEqual(reader.reads,0)


if __name__=="__main__":
    unittest.main()
