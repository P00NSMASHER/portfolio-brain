import copy, unittest
from model_router.model_router import ModelRouterError, hashv, make_tier0_receipt, route_request, validate_call_receipt, validate_feedback, value_summary

def request(kind="ARCHITECTURE",det=False,independent=False,builder=None,cost=5.0,classification="SANITIZED"):
    return {"schema_version":"1.0.0","request_id":"MRQ-TEST-00000001","project_ids":["PRJ-000"],"task_kind":kind,"deterministic_sufficient":det,
            "consequence":"HIGH","data_classification":classification,"authority_class":"OBSERVE","requires_independent_adversarial":independent,
            "builder_independence_group":builder,"max_cost_usd":cost,"max_input_tokens":1000,"max_output_tokens":1000,
            "provider_allowlist":[],"evidence_refs":["test:step13"]}

def registry():
    return {"schema_version":"1.0.0","providers":[
      {"provider_id":"deterministic","adapter_kind":"DETERMINISTIC_LOCAL","enabled":True,"credential_env_var":None,"base_url_env_var":None,
       "models":[{"model_id":"NONE","tier":0,"enabled":True,"independence_group":"deterministic","supported_data_classifications":["PUBLIC","SANITIZED","PRIVATE_REFERENCE_ONLY"],"max_input_tokens":0,"max_output_tokens":0,"pricing":{"basis":"ZERO_TIER0","input_usd_per_million_tokens":0.0,"output_usd_per_million_tokens":0.0,"fixed_call_usd":0.0}}]},
      {"provider_id":"api","adapter_kind":"OPENAI_COMPATIBLE_API","enabled":True,"credential_env_var":"X","base_url_env_var":"Y","models":[
        {"model_id":"cheap","tier":1,"enabled":True,"independence_group":"cheap-g","supported_data_classifications":["PUBLIC","SANITIZED"],"max_input_tokens":10000,"max_output_tokens":5000,"pricing":{"basis":"CONFIGURED_RATE","input_usd_per_million_tokens":1.0,"output_usd_per_million_tokens":2.0,"fixed_call_usd":0.0}},
        {"model_id":"strong","tier":2,"enabled":True,"independence_group":"strong-g","supported_data_classifications":["PUBLIC","SANITIZED"],"max_input_tokens":10000,"max_output_tokens":5000,"pricing":{"basis":"CONFIGURED_RATE","input_usd_per_million_tokens":3.0,"output_usd_per_million_tokens":6.0,"fixed_call_usd":0.0}},
        {"model_id":"red","tier":3,"enabled":True,"independence_group":"red-g","supported_data_classifications":["PUBLIC","SANITIZED"],"max_input_tokens":10000,"max_output_tokens":5000,"pricing":{"basis":"CONFIGURED_RATE","input_usd_per_million_tokens":4.0,"output_usd_per_million_tokens":8.0,"fixed_call_usd":0.0}}
      ]},
      {"provider_id":"second","adapter_kind":"SELF_HOSTED","enabled":True,"credential_env_var":None,"base_url_env_var":"Z","models":[
        {"model_id":"red2","tier":3,"enabled":True,"independence_group":"second-red","supported_data_classifications":["PUBLIC","SANITIZED","PRIVATE_REFERENCE_ONLY"],"max_input_tokens":10000,"max_output_tokens":5000,"pricing":{"basis":"CONFIGURED_RATE","input_usd_per_million_tokens":5.0,"output_usd_per_million_tokens":5.0,"fixed_call_usd":0.0}}
      ]}
    ]}

class ModelRouterTests(unittest.TestCase):
    def test_deterministic_sufficient_forces_tier0(self):
        r=request(kind="ARCHITECTURE",det=True,cost=0.0);r["max_input_tokens"]=0;r["max_output_tokens"]=0
        route=route_request(r,registry())
        self.assertEqual((route["tier"],route["provider_id"],route["model_id"]),(0,"deterministic","NONE"))

    def test_hashing_is_tier0(self):
        r=request(kind="HASHING",det=False,cost=0.0);r["max_input_tokens"]=0;r["max_output_tokens"]=0
        self.assertEqual(route_request(r,registry())["tier"],0)

    def test_low_cost_task_routes_tier1(self):
        r=request(kind="EXTRACTION")
        route=route_request(r,registry());self.assertEqual((route["tier"],route["model_id"]),(1,"cheap"))

    def test_architecture_routes_tier2(self):
        route=route_request(request(kind="ARCHITECTURE"),registry())
        self.assertEqual((route["tier"],route["model_id"]),(2,"strong"))

    def test_tier3_requires_independence_context(self):
        with self.assertRaises(ModelRouterError):route_request(request(kind="PROMOTION_VERIFICATION",independent=True,builder=None),registry())

    def test_tier3_excludes_builder_independence_group(self):
        r=request(kind="PROMOTION_VERIFICATION",independent=True,builder="red-g")
        route=route_request(r,registry())
        self.assertEqual(route["tier"],3)
        self.assertEqual(route["independence_group"],"second-red")
        self.assertNotEqual(route["independence_group"],r["builder_independence_group"])

    def test_budget_blocks_model_route(self):
        r=request(kind="ARCHITECTURE",cost=0.0001)
        route=route_request(r,registry())
        self.assertEqual(route["status"],"BLOCKED_NO_ELIGIBLE_PROVIDER")

    def test_private_reference_only_requires_compatible_provider(self):
        r=request(kind="ARCHITECTURE",classification="PRIVATE_REFERENCE_ONLY")
        self.assertEqual(route_request(r,registry())["status"],"BLOCKED_NO_ELIGIBLE_PROVIDER")

    def test_provider_allowlist_is_honored(self):
        r=request(kind="ARCHITECTURE");r["provider_allowlist"]=["second"]
        self.assertEqual(route_request(r,registry())["status"],"BLOCKED_NO_ELIGIBLE_PROVIDER")

    def test_tier0_receipt_has_zero_cost_and_no_authority(self):
        r=request(kind="SCHEMA_VALIDATION",det=True,cost=0.0);r["max_input_tokens"]=0;r["max_output_tokens"]=0
        route=route_request(r,registry())
        rec=make_tier0_receipt(route,r,input_hash="sha256:"+"a"*64,output_hash="sha256:"+"b"*64,started_at="2026-09-25T19:00:00Z",completed_at="2026-09-25T19:00:01Z")
        validate_call_receipt(rec,route,r)
        self.assertEqual(rec["cost_usd"],0)
        self.assertFalse(rec["authority_granted"]);self.assertFalse(rec["evidence_upgraded"])

    def test_receipt_cannot_grant_authority(self):
        r=request(kind="SCHEMA_VALIDATION",det=True,cost=0.0);r["max_input_tokens"]=0;r["max_output_tokens"]=0
        route=route_request(r,registry())
        rec=make_tier0_receipt(route,r,input_hash="sha256:"+"a"*64,output_hash="sha256:"+"b"*64,started_at="2026-09-25T19:00:00Z",completed_at="2026-09-25T19:00:01Z")
        rec["authority_granted"]=True
        body=dict(rec);body.pop("receipt_hash");rec["receipt_hash"]=hashv(body)
        with self.assertRaises(ModelRouterError):validate_call_receipt(rec,route,r)

    def test_only_verified_feedback_affects_value_summary(self):
        r=request(kind="SCHEMA_VALIDATION",det=True,cost=0.0);r["max_input_tokens"]=0;r["max_output_tokens"]=0
        route=route_request(r,registry())
        rec=make_tier0_receipt(route,r,input_hash="sha256:"+"a"*64,output_hash="sha256:"+"b"*64,started_at="2026-09-25T19:00:00Z",completed_at="2026-09-25T19:00:01Z")
        observed={"schema_version":"1.0.0","feedback_id":"MFB-OBSERVED-0001","invocation_id":rec["invocation_id"],"outcome_event_id":"EVT-OUTCOME-0001","evidence_state":"OBSERVED","value_class":"TECHNICAL","outcome_value":1.0,"provenance_refs":["test:o"]}
        verified={**observed,"feedback_id":"MFB-VERIFIED-0001","evidence_state":"VERIFIED","outcome_event_id":"EVT-OUTCOME-0002","outcome_value":0.5}
        summary=value_summary([rec],[observed,verified])
        bucket=next(iter(summary.values()))
        self.assertEqual(bucket["verified_outcomes"],1)
        self.assertEqual(bucket["mean_verified_outcome_value"],0.5)

if __name__=="__main__":unittest.main()
