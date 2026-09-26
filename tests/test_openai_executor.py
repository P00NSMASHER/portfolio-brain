import copy,io,os,unittest
from email.message import Message
from urllib.error import HTTPError
from unittest.mock import patch
from cost_governor.cost_governor import load_state
from model_router.model_router import provider_registry,route_request
from model_router.openai_executor import OpenAIExecutorError,_parse_http_error,execute_openai

def req(kind="ARCHITECTURE",builder=None):
    return {
      "schema_version":"1.0.0","request_id":"MRQ-OPENAI-TEST","project_ids":["PRJ-000"],
      "task_kind":kind,"deterministic_sufficient":False,"consequence":"HIGH","data_classification":"SANITIZED",
      "authority_class":"OBSERVE","requires_independent_adversarial":kind=="PROMOTION_VERIFICATION",
      "builder_independence_group":builder,"max_cost_usd":1.0,"max_input_tokens":1000,"max_output_tokens":1000,
      "provider_allowlist":["openai"],"evidence_refs":["test:openai"]
    }

class OpenAIExecutorTests(unittest.TestCase):
    def test_checked_in_routes_are_luna_terra_sol(self):
        reg=provider_registry()
        p=next(x for x in reg["providers"] if x["provider_id"]=="openai")
        self.assertTrue(p["enabled"])
        self.assertEqual([(m["tier"],m["model_id"]) for m in p["models"]],[
          (1,"gpt-5.6-luna"),(2,"gpt-5.6-terra"),(3,"gpt-5.6-sol")])

    def test_architecture_routes_terra(self):
        r=route_request(req(),provider_registry())
        self.assertEqual((r["status"],r["provider_id"],r["model_id"]),("ROUTED","openai","gpt-5.6-terra"))

    def test_adversarial_routes_sol_independent_of_terra(self):
        r=route_request(req("PROMOTION_VERIFICATION","openai-terra"),provider_registry())
        self.assertEqual(r["model_id"],"gpt-5.6-sol")
        self.assertNotEqual(r["independence_group"],"openai-terra")

    def test_missing_secret_fails_before_network(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(OpenAIExecutorError):
                execute_openai(req(),"hello",load_state(),transport=lambda *a: self.fail("network called"))

    def test_fake_response_commits_usage_and_receipt(self):
        response={"id":"resp_test","output":[{"content":[{"type":"output_text","text":"result"}]}],
                  "usage":{"input_tokens":100,"output_tokens":20}}
        def fake(url,headers,payload,timeout):
            self.assertIn("/v1/responses",url)
            self.assertTrue(headers["Authorization"].startswith("Bearer "))
            return response
        with patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"}):
            state,out=execute_openai(req(),"hello",load_state(),at="2026-09-25T20:00:00Z",transport=fake)
        self.assertEqual(out["receipt"]["status"],"SUCCESS")
        self.assertEqual(out["receipt"]["model_id"],"gpt-5.6-terra")
        self.assertEqual(out["receipt"]["input_tokens"],100)
        self.assertEqual(out["receipt"]["output_tokens"],20)
        self.assertEqual(out["output_text"],"result")
        self.assertEqual(state["reservations"][-1]["status"],"COMMITTED")


    def test_temporary_slow_down_429_is_retryable_and_honors_retry_after(self):
        headers=Message();headers["Retry-After"]="7"
        body=io.BytesIO(b'{"error":{"type":"rate_limit_error","code":"slow_down"}}')
        exc=HTTPError("https://api.openai.com/v1/responses",429,"Too Many Requests",headers,body)
        code,typ,retry_after,retryable=_parse_http_error(exc)
        self.assertEqual((code,typ,retry_after,retryable),("slow_down","rate_limit_error",7.0,True))

    def test_quota_429_is_not_retryable(self):
        headers=Message()
        body=io.BytesIO(b'{"error":{"type":"insufficient_quota","code":"credit_balance_exhausted"}}')
        exc=HTTPError("https://api.openai.com/v1/responses",429,"Too Many Requests",headers,body)
        code,typ,retry_after,retryable=_parse_http_error(exc)
        self.assertEqual(code,"credit_balance_exhausted")
        self.assertEqual(typ,"insufficient_quota")
        self.assertFalse(retryable)

    def test_short_context_pricing_boundary_is_enforced(self):
        r=req();r["max_input_tokens"]=272001
        self.assertEqual(route_request(r,provider_registry())["status"],"BLOCKED_NO_ELIGIBLE_PROVIDER")

if __name__=="__main__":unittest.main()
