import hashlib
import json
import unittest

from model_router.model_router import hashv, route_request
from value_proof.end_to_end import build_value_outcome
from value_proof.model_task import execute_task, load_contract, make_evidence_pack
from value_proof.verifier import load_verifier_contract, verify_output


def builder_output():
    return {
      "summary":"The exact revision exposes a small quiz/session separation worth a bounded integration review.",
      "recommendation":"DEEPER_BOUNDED_REVIEW",
      "evidence_paths":["quizli/quiz.py","quizli/session.py","tests/test_quizli.py"],
      "proposed_pattern":"Keep quiz item selection/state separate from session progression and scoring.",
      "risks":["Reuse rights remain unresolved.","Python implementation details do not directly map to Roblox."],
      "rights_state":"OPERATOR_ASSUMED",
      "confidence":0.81,
    }


def verifier_output():
    return {
      "verdict":"PASS",
      "evidence_supported":True,
      "contract_compliant":True,
      "useful_for_bounded_followup":True,
      "reason":"The recommendation is narrow, evidence-bound, and useful for deciding whether to perform a separate integration review.",
      "risks":["No reuse-rights conclusion is established.","Applicability to StarBlox must still be tested separately."],
      "confidence":0.86,
    }


def provider_result(request,input_text,output_obj,cost=0.001):
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
      "started_at":"2026-09-27T03:30:00Z",
      "completed_at":"2026-09-27T03:30:01Z",
      "input_tokens":400,
      "output_tokens":150,
      "cost_usd":cost,
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
        return cost_state,provider_result(request,input_text,builder_output())


class VerifierExecutor:
    def __call__(self,request,input_text,cost_state,attempt=1,reasoning_effort="high",at=None):
        return cost_state,provider_result(request,input_text,verifier_output())


class EndToEndValueProofTests(unittest.TestCase):
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
        _,self.built=execute_task(
          contract=self.task,pack=self.pack,cost_state={},executor=BuilderExecutor()
        )
        _,self.verified=verify_output(
          task_contract=self.task,
          verifier_contract=self.verifier,
          pack=self.pack,
          builder_output=self.built["parsed_output"],
          execution_receipt=self.built["execution_receipt"],
          builder_provider_receipt=self.built["provider_receipt"],
          cost_state={},
          executor=VerifierExecutor(),
        )

    def test_verified_output_becomes_distinct_verified_value_outcome(self):
        outcome=build_value_outcome(
          task_contract=self.task,
          verifier_contract=self.verifier,
          pack=self.pack,
          builder_output=self.built["parsed_output"],
          builder_execution_receipt=self.built["execution_receipt"],
          builder_provider_receipt=self.built["provider_receipt"],
          deterministic_receipt=self.verified["deterministic_receipt"],
          verifier_output=self.verified["verifier_output"],
          verifier_receipt=self.verified["verification_receipt"],
          verifier_provider_receipt=self.verified["verifier_provider_receipt"],
        )
        self.assertEqual(self.built["status"],"MODEL_CALL_SUCCESS")
        self.assertEqual(self.verified["status"],"OUTPUT_VERIFIED")
        self.assertEqual(outcome["value_status"],"VALUE_OUTCOME_VERIFIED")
        self.assertEqual(outcome["value_class"],"TECHNICAL_RESEARCH_DECISION_UTILITY")
        self.assertEqual(outcome["decision"],"PROCEED_TO_BOUNDED_INTEGRATION_REVIEW")
        self.assertTrue(outcome["useful_outcome"])
        self.assertEqual(outcome["evidence_state"],"VERIFIED")
        self.assertFalse(outcome["external_customer_value_claimed"])
        self.assertFalse(outcome["capability_verification_claimed"])
        self.assertFalse(outcome["deployment_authorized"])
        self.assertFalse(outcome["authority_granted"])
        self.assertFalse(outcome["evidence_upgraded"])
        self.assertEqual(outcome["rights_state"],"OPERATOR_ASSUMED")
        self.assertTrue(outcome["outcome_hash"].startswith("sha256:"))

    def test_tampered_verification_receipt_cannot_create_value_outcome(self):
        tampered=json.loads(json.dumps(self.verified["verification_receipt"]))
        tampered["status"]="OUTPUT_REJECTED"
        with self.assertRaises(Exception):
            build_value_outcome(
              task_contract=self.task,
              verifier_contract=self.verifier,
              pack=self.pack,
              builder_output=self.built["parsed_output"],
              builder_execution_receipt=self.built["execution_receipt"],
              builder_provider_receipt=self.built["provider_receipt"],
              deterministic_receipt=self.verified["deterministic_receipt"],
              verifier_output=self.verified["verifier_output"],
              verifier_receipt=tampered,
              verifier_provider_receipt=self.verified["verifier_provider_receipt"],
            )


if __name__=="__main__":
    unittest.main()
