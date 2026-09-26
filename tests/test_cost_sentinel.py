import copy,unittest
from cost_governor.sentinel import build_sentinel_snapshot
from model_router.provider_health_state import _normalize
from dashboard.publication_gate import should_publish

class CostSentinelTests(unittest.TestCase):
    def test_provider_domains_are_distinct(self):
        p=_normalize({"schema_version":"1.0.0","mode":"daily","status":"BLOCKED_PROVIDER_BILLING","provider_attempt":1,"provider_code":"billing_not_active","provider_type":"billing_not_active","retryable":False,"reason_codes":[]},artifact_id=7,created_at="2026-09-26T00:00:00Z")
        self.assertEqual(p["readiness"],"BILLING_NOT_ACTIVE");self.assertTrue(p["provider_domain_blocked"]);self.assertFalse(p["budget_domain_blocked"])
        b=_normalize({"status":"BLOCKED_COST_BUDGET","reason_codes":["PORTFOLIO_COST_USD"]},artifact_id=8,created_at="2026-09-26T00:00:00Z")
        self.assertEqual(b["readiness"],"BUDGET_BLOCKED");self.assertFalse(b["provider_domain_blocked"]);self.assertTrue(b["budget_domain_blocked"])

    def test_gmail_is_separate_and_reports_headroom(self):
        action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}}
        action_ledger={"executions":[{"status":"SENT","sent_at":"2026-09-26T12:00:00Z","idempotency_key":"a"},{"status":"SENT","sent_at":"2026-09-26T13:00:00Z","idempotency_key":"b"}]}
        s=build_sentinel_snapshot(cost_policy={"portfolio_ceiling":{"cost_usd":10},"workflow_job_ceilings":{}},cost_state={"reservations":[]},provider_registry={"providers":[]},model_ledger={"calls":[],"outcomes":[]},action_policy=action_policy,action_ledger=action_ledger,provider_health={"readiness":"UNPROBED"},at="2026-09-26T20:00:00Z")
        self.assertFalse(s["gmail_gateway"]["included_in_model_or_github_spend"])
        self.assertEqual(s["gmail_gateway"]["daily_headroom"],23)
        self.assertEqual(s["budget"]["portfolio_ceiling"]["cost_usd"],10)

    def test_publication_gate_ignores_only_volatile_metadata(self):
        a={"x":1,"snapshot_hash":"a","state_sources":{"sources":{"cost":{"source_run_id":1,"state_sequence":4}}}}
        b=copy.deepcopy(a);b["snapshot_hash"]="b";b["state_sources"]["sources"]["cost"]["source_run_id"]=2
        self.assertFalse(should_publish(a,b))
        b["state_sources"]["sources"]["cost"]["state_sequence"]=5
        self.assertTrue(should_publish(a,b))

if __name__=="__main__":unittest.main()
