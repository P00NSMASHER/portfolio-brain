import hashlib
import json
import unittest

from model_router.model_router import hashv, route_request
from value_proof.model_task import execute_task, load_contract, make_evidence_pack
from value_proof.verifier import (
    VerifierError,
    deterministic_verify,
    load_verifier_contract,
    verify_output,
)


def builder_output():
    return {
      "summary":"The candidate has a compact quiz/session architecture suitable for bounded follow-up review.",
      "recommendation":"DEEPER_BOUNDED_REVIEW",
      "evidence_paths":["quizli/quiz.py","tests/test_quizli.py"],
      "proposed_pattern":"Separate quiz selection/state from session progression and preserve deterministic scoring boundaries.",
      "risks":["Reuse rights are unresolved.","The library is not a direct Roblox implementation."],
      "rights_state":"UNKNOWN_REQUIRES_REVIEW",
      "confidence":0.8,
    }


def verifier_output():
    return {
      "verdict":"PASS",
      "evidence_supported":True,
      "contract_compliant":True,
      "useful_for_bounded_followup":True,
      "reason":"The builder recommendation is narrow, supported by the bound implementation/test paths, and preserves rights uncertainty.",
      "risks":["No reuse-rights conclusion is established.","Applicability to Roblox still requires a separate bounded integration review."],
      "confidence":0.84,
    }


def make_provider_result(request,input_text,output_obj):
    route=route_request(request)
    output_text=json.dumps(output_obj,sort_keys=True)
    input_hash="sha256:"+hashlib.sha256(input_text.encode()).hexdigest()
    output_hash="sha256:"+hashlib.sha256(output_text.encode()).hexdigest()
    core={
      "schema_version":"1.0.0",
      "invocation_id":"MINV-"+hashlib.sha256((request["request_id"]+output_hash).encode()).hexdigest()[:20].upper(),
      "request_id":request["request_id"],
      "route_id":route["route_id"],
      "tier":route["tier"],
      "provider_id":route["provider_id"],
      "model_id":route["model_id"],
      "independence_group":route["independence_group"],
      "status":"SUCCESS",
      "started_at":"2026-09-27T03:20:00Z",
      "completed_at":"2026-09-27T03:20:01Z",
      "input_tokens":400,
      "output_tokens":140,
      "cost_usd":0.001,
      "cost_basis":"TEST_CONFIGURED_RATE",
      "latency_ms":1000,
      "input_hash":input_hash,
      "output_hash":output_hash,
      "authority_granted":False,
      "evidence_upgraded":False,
      "downstream_outcome_ids":[],
    }
    receipt={**core,"receipt_hash":hashv(core)}
    return {"route":route,"receipt":receipt,"output_text":output_text,"response_id":"resp_test"}


class BuilderExecutor:
    def __call__(self,request,input_text,cost_state,attempt=1,reasoning_effort="medium",at=None):
        return cost_state,make_provider_result(request,input_text,builder_output())


class VerifierExecutor:
    def __call__(self,request,input_text,cost_state,attempt=1,reasoning_effort="high",at=None):
        return cost_state,make_provider_result(request,input_text,verifier_output())


class IndependentVerifierTests(unittest.TestCase):
    def setUp(self):
        self.task=load_contract()
        self.verifier=load_verifier_contract()
        src=self.task["source_candidate"]
        self.pack=make_evidence_pack(
          repository_full_name=src["repository_full_name"],
          repository_id=src["repository_id"],
          revision=src["revision"],
          files=[
            {"path":"quizli/quiz.py","content":"class Quiz:\n    def next_question(self): return None\n"},
            {"path":"quizli/session.py","content":"class Session:\n    def advance(self): return None\n"},
            {"path":"tests/test_quizli.py","content":"def test_quiz_advances(): assert True\n"},
          ],
        )
        _,built=execute_task(contract=self.task,pack=self.pack,cost_state={},executor=BuilderExecutor())
        self.built=built

    def test_deterministic_verifier_revalidates_all_builder_artifacts(self):
        receipt=deterministic_verify(
          task_contract=self.task,
          verifier_contract=self.verifier,
          pack=self.pack,
          builder_output=self.built["parsed_output"],
          execution_receipt=self.built["execution_receipt"],
          provider_receipt=self.built["provider_receipt"],
        )
        self.assertEqual(receipt["status"],"DETERMINISTIC_CHECKS_PASSED")
        self.assertTrue(all(receipt["checks"].values()))
        self.assertFalse(receipt["authority_granted"])
        self.assertFalse(receipt["evidence_upgraded"])

    def test_verifier_routes_to_independent_sol_tier3(self):
        _,result=verify_output(
          task_contract=self.task,
          verifier_contract=self.verifier,
          pack=self.pack,
          builder_output=self.built["parsed_output"],
          execution_receipt=self.built["execution_receipt"],
          builder_provider_receipt=self.built["provider_receipt"],
          cost_state={},
          executor=VerifierExecutor(),
        )
        receipt=result["verification_receipt"]
        self.assertEqual(result["status"],"OUTPUT_VERIFIED")
        self.assertEqual(receipt["verifier_tier"],3)
        self.assertEqual(receipt["verifier_model_id"],"gpt-5.6-sol")
        self.assertNotEqual(receipt["verifier_independence_group"],"openai-terra")
        self.assertFalse(receipt["value_outcome_claimed"])
        self.assertFalse(receipt["authority_granted"])
        self.assertFalse(receipt["evidence_upgraded"])

    def test_tampered_builder_output_fails_before_independent_model(self):
        tampered=json.loads(json.dumps(self.built["parsed_output"]))
        tampered["rights_state"]="LICENSE_VERIFIED"
        with self.assertRaises(Exception):
            deterministic_verify(
              task_contract=self.task,
              verifier_contract=self.verifier,
              pack=self.pack,
              builder_output=tampered,
              execution_receipt=self.built["execution_receipt"],
              provider_receipt=self.built["provider_receipt"],
            )

    def test_tampered_execution_receipt_fails_before_independent_model(self):
        tampered=json.loads(json.dumps(self.built["execution_receipt"]))
        tampered["parsed_output_hash"]="sha256:"+"0"*64
        with self.assertRaises(Exception):
            deterministic_verify(
              task_contract=self.task,
              verifier_contract=self.verifier,
              pack=self.pack,
              builder_output=self.built["parsed_output"],
              execution_receipt=tampered,
              provider_receipt=self.built["provider_receipt"],
            )

    def test_verifier_pass_cannot_be_internally_inconsistent(self):
        class BadVerifierExecutor:
            def __call__(self,request,input_text,cost_state,attempt=1,reasoning_effort="high",at=None):
                bad=verifier_output();bad["evidence_supported"]=False
                return cost_state,make_provider_result(request,input_text,bad)
        with self.assertRaises(VerifierError):
            verify_output(
              task_contract=self.task,
              verifier_contract=self.verifier,
              pack=self.pack,
              builder_output=self.built["parsed_output"],
              execution_receipt=self.built["execution_receipt"],
              builder_provider_receipt=self.built["provider_receipt"],
              cost_state={},
              executor=BadVerifierExecutor(),
            )


if __name__=="__main__":
    unittest.main()
