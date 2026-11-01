"""Uncertain remote write recovery tests. No network, no provider writes."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from brain.v10 import engineering_factory as f
from brain.v10 import reconciliation as rec
from test_brain_v10_factory import FakeProvider, manifest, ORIGINAL

class ReadbackProvider(FakeProvider):
    def __init__(self, candidate):
        super().__init__()
        self.candidate = candidate
        self.branch = candidate["branch"]
        self.final_content = candidate["changes"][0]["updated_bytes"]
        self.pr_body = ("BRAIN_V10_OPERATION_ID: " + candidate["operation_id"]
                        + "\nOriginal run: 12345678")
        self.pr_draft = True
        self.pr_merged = False
        self.pr_head_sha = self.final_sha
        self.pr_base_sha = manifest()["base_sha"]
        self.matches = 1
        self.list_omits_merged = False
        self.detail_omits_merged = False
        self.mutate_after_initial = False
        self.main_requests = 0

    def _pr(self):
        return {
            "number": self.pr_number, "state": "open",
            "draft": self.pr_draft, "merged": self.pr_merged,
            "body": self.pr_body,
            "head": {"ref": self.branch, "sha": self.pr_head_sha,
                     "repo": {"full_name": f.REPOSITORY}},
            "base": {"ref": "main", "sha": self.pr_base_sha,
                     "repo": {"full_name": f.REPOSITORY}},
        }

    def request(self, method, route, payload=None):
        if method == "GET":
            self.calls.append((method,route,payload))
            if route.startswith("pulls?head="):
                rows = [self._pr() for _ in range(self.matches)]
                if self.list_omits_merged:
                    for row in rows:
                        row.pop("merged")
                        row["merged_at"] = None
                return rows
            if route == "pulls/" + str(self.pr_number):
                row = self._pr()
                if self.detail_omits_merged:
                    row.pop("merged")
                return row
            if route == "branches/main":
                self.main_requests += 1
                return {"commit": {"sha":
                    "f"*40 if self.mutate_after_initial and self.main_requests > 1
                    else self.main}}
        return super().request(method,route,payload)

def intent(candidate):
    return dict(operation_id=candidate["operation_id"],
                source_sha=manifest()["base_sha"],
                branch=candidate["branch"], repository=f.REPOSITORY,
                failure_run_id=manifest()["failure_run_id"],
                test_receipt_sha256="d"*64,
                original_run_verdict="ORIGINAL_FAILED_CORE_REPRODUCED_NOT_DIAGNOSED",
                status="EXTERNAL_WRITE_INTENT_MUST_RECONCILE")

class UncertainDraftReadbackTests(unittest.TestCase):
    def setUp(self):
        self.spec=manifest()
        self.candidate=f.prepare(self.spec,{"brain/demo.py": ORIGINAL})
        self.api=ReadbackProvider(self.candidate)

    def test_original_draft_is_resolved_by_two_pr_reads_exact_bytes_and_branch(self):
        actual=rec.reconcile_draft(self.api,self.spec,self.candidate,
                                   intent(self.candidate))
        self.assertEqual(actual["status"],
                         "ORIGINAL_GITHUB_DRAFT_RECONCILED_NOT_RELEASED")
        self.assertEqual(actual["pr_number"],self.api.pr_number)
        self.assertEqual(actual["candidate_sha"],self.api.final_sha)
        self.assertEqual(actual["provider_writes"],0)
        self.assertFalse(actual["merged"])
        self.assertFalse(actual["deployed"])
        self.assertFalse(actual["production_accepted"])
        self.assertFalse(actual["independent_gate_passed"])
        calls=[(m,p) for m,p,_ in self.api.calls]
        self.assertTrue(any(q.startswith("pulls?head=") for m,q in calls))
        self.assertIn(("GET","pulls/"+str(self.api.pr_number)),calls)
        self.assertFalse(any(method!="GET" for method,_,_ in self.api.calls))

    def test_native_github_pr_list_omits_merged_but_detail_is_verified(self):
        # GitHub's actual GET /pulls list omits 'merged'; GET /pulls/N
        # supplies merged=False. Both raw provider shapes must be honored.
        self.api.list_omits_merged = True
        observed = rec.reconcile_draft(self.api, self.spec,
                                       self.candidate, intent(self.candidate))
        self.assertEqual(observed["status"],
                         "ORIGINAL_GITHUB_DRAFT_RECONCILED_NOT_RELEASED")
        self.assertEqual(observed["provider_writes"], 0)

        # A detail endpoint lacking the required explicit merged=False must
        # still fail closed instead of accepting an ambiguous PR identity.
        self.api = ReadbackProvider(self.candidate)
        self.api.list_omits_merged = True
        self.api.detail_omits_merged = True
        with self.assertRaisesRegex(
                f.FactoryError, "FACTORY_RECONCILED_DRAFT_IDENTITY_INVALID"):
            rec.reconcile_draft(self.api, self.spec, self.candidate,
                                intent(self.candidate))
        self.assertFalse(any(method != "GET" for method, _, _ in self.api.calls))

    def test_missing_or_multiple_open_drafts_never_trigger_retry(self):
        for count in (0,2):
            with self.subTest(count=count):
                self.api=ReadbackProvider(self.candidate)
                self.api.matches=count
                with self.assertRaisesRegex(
                    f.FactoryError,"FACTORY_DRAFT_PR_NOT_UNIQUELY_OBSERVED"):
                    rec.reconcile_draft(self.api,self.spec,self.candidate,
                                        intent(self.candidate))
                self.assertFalse(any(method!="GET"
                                     for method,_,_ in self.api.calls))

    def test_wrong_head_base_draft_state_or_marker_is_rejected(self):
        for key,value in (
                ("pr_head_sha","e"*40),
                ("pr_base_sha","f"*40),
                ("pr_draft",False),
                ("pr_merged",True),
                ("pr_body","attacker counterfeit"),
                ("branch","auto-repair/v10-"+"a"*16)):
            with self.subTest(key=key):
                self.api=ReadbackProvider(self.candidate)
                setattr(self.api,key,value)
                with self.assertRaisesRegex(
                    f.FactoryError,"FACTORY_RECONCILED_DRAFT_IDENTITY_INVALID"):
                    rec.reconcile_draft(self.api,self.spec,self.candidate,
                                        intent(self.candidate))
                self.assertFalse(any(method!="GET"
                                     for method,_,_ in self.api.calls))

    def test_main_drift_between_readbacks_prevents_resolved_claim(self):
        self.api.mutate_after_initial=True
        with self.assertRaisesRegex(
                f.FactoryError,"FACTORY_SOURCE_MOVED_DURING_RECONCILIATION"):
            rec.reconcile_draft(self.api,self.spec,self.candidate,
                                intent(self.candidate))
        self.assertFalse(any(method!="GET" for method,_,_ in self.api.calls))

    def test_wrong_file_bytes_and_intent_never_become_reconciled_drafts(self):
        self.api.final_content=b"attacker-modified candidate"
        with self.assertRaisesRegex(
                f.FactoryError,"FACTORY_DRAFT_SOURCE_READBACK_MISMATCH"):
            rec.reconcile_draft(self.api,self.spec,self.candidate,
                                intent(self.candidate))
        for key,value in (("operation_id","a"*64),
                          ("test_receipt_sha256",True),
                          ("source_sha","e"*40)):
            bad=intent(self.candidate)
            bad[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(
                f.FactoryError,"FACTORY_INTENT_IDENTITY_INVALID"):
                rec.reconcile_draft(ReadbackProvider(self.candidate),
                                    self.spec,self.candidate,bad)

    def test_intent_file_is_private_size_bounded_and_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"intent.json"
            path.write_text(json.dumps(intent(self.candidate)))
            self.assertEqual(rec.load_intent(path)["branch"],
                             self.candidate["branch"])
            path.write_text('{"operation_id":"a","operation_id":"b"}')
            with self.assertRaises(f.FactoryError):
                rec.load_intent(path)
            path.write_text("x"*9000)
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_INTENT_INVALID"):
                rec.load_intent(path)
            original=Path(tmp)/"original.json"
            original.write_text(json.dumps(intent(self.candidate)))
            path.unlink()
            path.symlink_to(original)
            with self.assertRaisesRegex(f.FactoryError,
                                        "FACTORY_INTENT_INVALID"):
                rec.load_intent(path)

if __name__=="__main__":
    unittest.main()
