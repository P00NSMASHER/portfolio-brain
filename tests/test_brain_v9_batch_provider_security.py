"""Security regressions for original-provider exact PR and check readback."""
from copy import deepcopy
import unittest

from brain.v9.batch_provider import (
    ProviderProofError, read_original_draft_pr, read_original_check_gate,
)

REPO="P00NSMASHER/portfolio-brain"
BASE="a"*40
HEAD="b"*40
OP="c"*64
PR=123
WHEN="2026-10-22T06:20:00Z"


def pr():
    return dict(
        number=PR, state="open", draft=True, updated_at=WHEN,
        user={"login":"P00NSMASHER"},
        head={"sha":HEAD,"repo":{"full_name":REPO}},
        base={"ref":"main","sha":BASE,"repo":{"full_name":REPO}},
        body="safe marker BRAIN_OPERATION_ID:"+OP,
    )


def checks():
    return dict(total_count=2,check_runs=[
        {"name":"validate","head_sha":HEAD,"app":{"id":15368},
         "status":"completed","conclusion":"success"},
        {"name":"portfolio-phase1-gate","head_sha":HEAD,"app":{"id":5121826},
         "status":"completed","conclusion":"success"},
    ])


class OriginalProviderEvidenceTests(unittest.TestCase):
    def test_provider_pr_two_identical_reads_confirm_only_draft(self):
        calls=[]
        def get(url):
            calls.append(url)
            return deepcopy(pr())
        evidence=read_original_draft_pr(
            get, repository=REPO, pr_number=PR, base_sha=BASE,
            head_sha=HEAD, operation_id=OP, observed_at=WHEN,
        )
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0],calls[1])
        self.assertTrue(calls[0].endswith("/pulls/123"))
        self.assertEqual(evidence["status"],"EXACT_DRAFT_PR_READBACK_CONFIRMED")
        self.assertEqual(evidence["operation_id"],OP)
        self.assertFalse(evidence["merge_authority"])
        self.assertFalse(evidence["production_accepted"])
        self.assertFalse(evidence["authenticated_unattended_acceptance"])

    def test_pr_revision_changed_during_double_read_is_unknown(self):
        snapshot=pr()
        def get(url):
            updated=deepcopy(snapshot)
            if get.calls:
                updated["updated_at"]="2026-10-22T06:20:01Z"
            get.calls+=1
            return updated
        get.calls=0
        with self.assertRaisesRegex(ProviderProofError,"PR_READBACK_CHANGED"):
            read_original_draft_pr(
                get,repository=REPO,pr_number=PR,base_sha=BASE,
                head_sha=HEAD,operation_id=OP,observed_at=WHEN)

    def test_wrong_source_marker_author_or_state_refused(self):
        for value in [
            {"body":"unrelated"},
            {"base":{"ref":"main","sha":"f"*40,"repo":{"full_name":REPO}}},
            {"head":{"sha":"f"*40,"repo":{"full_name":REPO}}},
            {"user":{"login":"unknown"}},
            {"draft":False},
            {"state":"closed"},
        ]:
            row=pr();row.update(value)
            with self.subTest(value=value), self.assertRaisesRegex(
                    ProviderProofError,"PR_IDENTITY_INVALID"):
                read_original_draft_pr(
                    lambda url:deepcopy(row),repository=REPO,pr_number=PR,
                    base_sha=BASE,head_sha=HEAD,
                    operation_id=OP,observed_at=WHEN)

    def test_original_gate_both_distinct_issuer_pinned_checks(self):
        calls=[]
        def get(url):
            calls.append(url)
            return deepcopy(checks())
        evidence=read_original_check_gate(
            get, repository=REPO, head_sha=HEAD, observed_at=WHEN)
        self.assertEqual(len(calls),2)
        self.assertEqual(evidence["status"],"EXACT_HEAD_CHECKS_READBACK_CONFIRMED")
        self.assertEqual(evidence["issuer_app_ids"],[15368,5121826])
        self.assertFalse(evidence["production_accepted"])
        self.assertFalse(evidence["independent_six_hour_acceptance"])

    def test_wrong_app_incomplete_duplicate_or_adverse_is_refused(self):
        for mutated in [
            lambda x: x["check_runs"][1]["app"].update(id=15368),
            lambda x: x["check_runs"][1].update(conclusion="failure"),
            lambda x: x["check_runs"][0].update(status="in_progress",conclusion=None),
            lambda x: x["check_runs"][1].update(head_sha="f"*40),
            lambda x: x["check_runs"].append(deepcopy(x["check_runs"][0])),
            lambda x: x.update(total_count=4),
        ]:
            row=checks();mutated(row)
            with self.subTest(check_rows=row),self.assertRaisesRegex(
                    ProviderProofError,"CHECK_GATE_INCOMPLETE"):
                read_original_check_gate(
                    lambda url:deepcopy(row),repository=REPO,
                    head_sha=HEAD,observed_at=WHEN)

    def test_check_run_changes_between_reads_are_not_false_green(self):
        once=checks()
        second=checks()
        second["check_runs"][1]["status"]="in_progress"
        times=[]
        def get(url):
            times.append(url)
            return deepcopy(once if len(times)==1 else second)
        with self.assertRaisesRegex(ProviderProofError,"CHECK_READBACK_CHANGED"):
            read_original_check_gate(
                get,repository=REPO,head_sha=HEAD,observed_at=WHEN)

    def test_bad_inputs_fail_before_network(self):
        def forbidden(_):
            raise AssertionError("should not call network")
        with self.assertRaises(ProviderProofError):
            read_original_check_gate(
                forbidden,repository="attacker/other",head_sha=HEAD,
                observed_at=WHEN)
        with self.assertRaises(ProviderProofError):
            read_original_draft_pr(
                forbidden,repository=REPO,pr_number=True,base_sha=BASE,
                head_sha=HEAD,operation_id=OP,observed_at=WHEN)


if __name__=="__main__":
    unittest.main()
