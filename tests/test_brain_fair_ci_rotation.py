"""Source-pinned fairness: irregular canonical event increments cannot starve PRs."""
import unittest

from brain.core import BrainError
from brain.fair_ci_rotation import rotation_counter
from brain.pr_intelligence import _candidate_from_list
from test_brain_focus_prs import RET, SHA_A, SHA_B, pr


class FairCiRotationTests(unittest.TestCase):
    def test_real_workflow_runs_advance_independently_of_event_count(self):
        chosen=[]
        rows=[
            pr(RET,329,SHA_A,"first","main",
               title="RETALLY first-customer onboarding"),
            pr(RET,343,SHA_B,"invoice","main",
               title="Review cross-shipment invoice reuse"),
            pr(RET,460,"c"*40,"m55","research/m54",
               title="RETALLY journal replay"),
        ]
        for index, sequence in enumerate((1000,1003,1006,1009,1012,1015)):
            result=rotation_counter(sequence,real_adapter=True,environment={
                "GITHUB_ACTIONS":"true",
                "GITHUB_WORKFLOW":"brain-cycle-v2",
                "GITHUB_RUN_NUMBER":str(101+index),
            })
            self.assertEqual(result["basis"],"GITHUB_WORKFLOW_RUN_SEQUENCE")
            self.assertEqual(result["extra_provider_requests"],0)
            selected=_candidate_from_list(rows,RET,"retally","main",
                                          check_rank=result["index"])
            chosen.append(selected["pr_number"])
        self.assertEqual(set(chosen),{329,343,460})
        self.assertEqual(chosen[:3],chosen[3:])

    def test_fake_or_non_cycle_context_cannot_inject_run_number(self):
        for env in (
            {"GITHUB_ACTIONS":"false","GITHUB_WORKFLOW":"brain-cycle-v2",
             "GITHUB_RUN_NUMBER":"999"},
            {"GITHUB_ACTIONS":"true","GITHUB_WORKFLOW":"foundation-ci",
             "GITHUB_RUN_NUMBER":"999"},
            {"GITHUB_ACTIONS":"true","GITHUB_WORKFLOW":"brain-cycle-v2",
             "GITHUB_RUN_NUMBER":"999"},
        ):
            with self.subTest(env=env):
                inject=env["GITHUB_ACTIONS"]=="true" and env["GITHUB_WORKFLOW"]=="brain-cycle-v2"
                output=rotation_counter(22,environment=env,real_adapter=not inject)
                self.assertEqual(output["index"],22)
                self.assertEqual(output["basis"],"CANONICAL_STATE_SEQUENCE")

    def test_invalid_run_number_falls_back_and_never_gains_authority(self):
        base={"GITHUB_ACTIONS":"true","GITHUB_WORKFLOW":"brain-cycle-v2"}
        for number in ("0","-1","1.1","not-a-run","9999999999999999999999",
                       "", "１２",None):
            with self.subTest(number=number):
                x=rotation_counter(42,environment=dict(base,GITHUB_RUN_NUMBER=number),
                                   real_adapter=True)
                self.assertEqual(x["index"],42)
                self.assertEqual(x["basis"],"INVALID_RUN_ID_FALLBACK_CANONICAL")
                self.assertEqual(x["extra_provider_requests"],0)

    def test_bad_source_types_are_refused(self):
        for state in (True,-1,2**63,"99",None):
            with self.subTest(state=state),self.assertRaises(BrainError):
                rotation_counter(state)
        with self.assertRaises(BrainError):
            rotation_counter(1,real_adapter=1)
        with self.assertRaises(BrainError):
            rotation_counter(1,environment=[])


if __name__=="__main__":
    unittest.main()
