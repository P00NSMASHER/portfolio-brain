import hashlib
import json
import unittest

from model_router.model_router import hashv, route_request
from value_proof.model_task import (
    ModelTaskError,
    build_model_request,
    execute_task,
    load_contract,
    make_evidence_pack,
    parse_and_validate_output,
    validate_evidence_pack,
)


def valid_output():
    return {
      "summary":"The exact revision exposes a compact quiz/session separation worth bounded review.",
      "recommendation":"DEEPER_BOUNDED_REVIEW",
      "evidence_paths":["quizli/quiz.py","tests/test_quizli.py"],
      "proposed_pattern":"Separate quiz item selection from session progression while keeping scoring deterministic.",
      "risks":["License/reuse rights remain unresolved.","The candidate is not a drop-in StarBlox implementation."],
      "rights_state":"UNKNOWN_REQUIRES_REVIEW",
      "confidence":0.78,
    }


class FakeExecutor:
    def __call__(self,request,input_text,cost_state,attempt=1,reasoning_effort="medium",at=None):
        route=route_request(request)
        output_text=json.dumps(valid_output(),sort_keys=True)
        input_hash="sha256:"+hashlib.sha256(input_text.encode()).hexdigest()
        output_hash="sha256:"+hashlib.sha256(output_text.encode()).hexdigest()
        core={
          "schema_version":"1.0.0",
          "invocation_id":"MINV-FAKEVALUEPROOF0001",
          "request_id":request["request_id"],
          "route_id":route["route_id"],
          "tier":route["tier"],
          "provider_id":route["provider_id"],
          "model_id":route["model_id"],
          "independence_group":route["independence_group"],
          "status":"SUCCESS",
          "started_at":"2026-09-27T03:10:00Z",
          "completed_at":"2026-09-27T03:10:01Z",
          "input_tokens":300,
          "output_tokens":120,
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
        return cost_state,{"route":route,"receipt":receipt,"output_text":output_text,"response_id":"resp_fake"}


class ModelTaskContractTests(unittest.TestCase):
    def setUp(self):
        self.contract=load_contract()
        src=self.contract["source_candidate"]
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

    def test_contract_is_candidate_specific_and_routes_to_terra_tier2(self):
        request=build_model_request(self.contract,self.pack)
        route=route_request(request)
        self.assertEqual(route["status"],"ROUTED")
        self.assertEqual(route["tier"],2)
        self.assertEqual(route["provider_id"],"openai")
        self.assertEqual(route["model_id"],"gpt-5.6-terra")
        self.assertLessEqual(route["max_estimated_cost_usd"],self.contract["model_contract"]["max_cost_usd"])

    def test_evidence_pack_binds_exact_revision_and_required_paths(self):
        validate_evidence_pack(self.pack,self.contract)
        bad=json.loads(json.dumps(self.pack))
        bad["revision"]="0"*40
        body=dict(bad);body.pop("pack_hash")
        from value_proof.model_task import digest
        bad["pack_hash"]=digest(body)
        with self.assertRaises(ModelTaskError):
            validate_evidence_pack(bad,self.contract)

    def test_model_output_must_preserve_rights_uncertainty(self):
        good=json.dumps(valid_output())
        parsed=parse_and_validate_output(good,self.contract)
        self.assertEqual(parsed["rights_state"],"UNKNOWN_REQUIRES_REVIEW")
        bad=valid_output();bad["rights_state"]="LICENSE_VERIFIED"
        with self.assertRaises(ModelTaskError):
            parse_and_validate_output(json.dumps(bad),self.contract)

    def test_execution_emits_separate_model_success_receipt_without_value_claim(self):
        _,result=execute_task(contract=self.contract,pack=self.pack,cost_state={},executor=FakeExecutor())
        self.assertEqual(result["status"],"MODEL_CALL_SUCCESS")
        receipt=result["execution_receipt"]
        self.assertEqual(receipt["status"],"MODEL_CALL_SUCCESS")
        self.assertEqual(receipt["tier"],2)
        self.assertEqual(receipt["model_id"],"gpt-5.6-terra")
        self.assertFalse(receipt["authority_granted"])
        self.assertFalse(receipt["evidence_upgraded"])
        self.assertEqual(receipt["downstream_outcome_ids"],[])
        self.assertTrue(receipt["provider_receipt_hash"].startswith("sha256:"))
        self.assertTrue(receipt["parsed_output_hash"].startswith("sha256:"))

    def test_model_cannot_cite_unbound_evidence_path(self):
        bad=valid_output();bad["evidence_paths"]=["quizli/quiz.py","README.md"]
        with self.assertRaises(ModelTaskError):
            parse_and_validate_output(json.dumps(bad),self.contract)


if __name__=="__main__":
    unittest.main()
