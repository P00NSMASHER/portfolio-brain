import copy
import unittest

from cost_governor.sentinel import build_sentinel_snapshot
from dashboard.publication_gate import should_publish

class CostSentinelTests(unittest.TestCase):
    def test_provider_and_budget_domains_are_distinct(self):
        common = dict(
            cost_policy={"portfolio_ceiling":{"cost_usd":10}},
            cost_state={"reservations":[]},
            provider_registry={"providers":[]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            at="2026-09-26T20:00:00Z",
        )
        provider = build_sentinel_snapshot(
            **common,
            provider_health={"status":"BILLING_NOT_ACTIVE","cost_gate_status":None},
        )
        self.assertTrue(provider["provider_readiness"]["provider_domain_blocked"])
        self.assertFalse(provider["provider_readiness"]["budget_domain_blocked"])
        budget = build_sentinel_snapshot(
            **common,
            provider_health={"status":"BUDGET_BLOCKED","cost_gate_status":"BLOCKED_BUDGET"},
        )
        self.assertFalse(budget["provider_readiness"]["provider_domain_blocked"])
        self.assertTrue(budget["provider_readiness"]["budget_domain_blocked"])

    def test_gmail_is_separate_and_reports_headroom(self):
        snapshot = build_sentinel_snapshot(
            cost_policy={"portfolio_ceiling":{"cost_usd":10}},
            cost_state={"reservations":[]},
            provider_registry={"providers":[]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[
                {"status":"SENT","sent_at":"2026-09-26T12:00:00Z","idempotency_key":"a"},
                {"status":"SENT","sent_at":"2026-09-26T13:00:00Z","idempotency_key":"b"},
            ]},
            provider_health={"status":"UNKNOWN"},
            at="2026-09-26T20:00:00Z",
        )
        self.assertFalse(snapshot["gmail_gateway"]["included_in_model_or_github_spend"])
        self.assertEqual(snapshot["gmail_gateway"]["daily_headroom"],23)
        self.assertEqual(snapshot["gmail_gateway"]["duplicate_receipt_count"],0)
        self.assertEqual(snapshot["budget"]["portfolio_ceiling"]["cost_usd"],10)
        self.assertTrue(snapshot["allocation"]["cash_ceiling_unchanged"])

    def test_model_efficiency_starts_without_invented_value(self):
        snapshot = build_sentinel_snapshot(
            cost_policy={"portfolio_ceiling":{"cost_usd":10}},
            cost_state={"reservations":[]},
            provider_registry={"providers":[{"provider_id":"openai","enabled":True,"models":[{
                "model_id":"gpt-5.6-terra","tier":2,"enabled":True,
                "pricing":{"input_usd_per_million_tokens":2,"output_usd_per_million_tokens":12},
            }]}]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            provider_health={"status":"READY"},
            at="2026-09-26T20:00:00Z",
        )
        row=snapshot["model_efficiency"]["models"][0]
        self.assertEqual(row["successful_calls"],0)
        self.assertEqual(row["value_signal"],"NO_SUCCESSFUL_CALL_BASELINE")
        self.assertIsNone(row["spend_per_verified_outcome_usd"])

    def test_daily_budget_and_model_metrics_ignore_retained_prior_days(self):
        def reservation(created_at, *, cost, model_calls, status="COMMITTED", evidence_refs=None):
            usage={
                "cost_usd":cost,"input_tokens":100,"output_tokens":20,
                "model_calls":model_calls,"api_calls":1,
                "github_job_starts":0,"github_runner_minutes":0,
            }
            return {
                "created_at":created_at,"status":status,"resource_kind":"MODEL_CALL",
                "provider_id":"openai","model_id":"gpt-5.6-terra",
                "actual_usage":usage,"estimated_usage":usage,
                "evidence_refs":evidence_refs or [],
            }

        snapshot = build_sentinel_snapshot(
            cost_policy={"portfolio_ceiling":{"cost_usd":10}},
            cost_state={"reservations":[
                reservation("2026-09-25T23:59:00Z",cost=7,model_calls=1,
                            evidence_refs=["provider-attempt:nonretryable:billing"]),
                reservation("2026-09-26T00:01:00Z",cost=0.25,model_calls=1),
            ]},
            provider_registry={"providers":[{"provider_id":"openai","enabled":True,"models":[{
                "model_id":"gpt-5.6-terra","tier":2,"enabled":True,
                "pricing":{"input_usd_per_million_tokens":2,"output_usd_per_million_tokens":12},
            }]}]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            provider_health={"status":"READY"},
            at="2026-09-26T20:00:00Z",
        )
        self.assertEqual(snapshot["budget"]["committed_usage"]["cost_usd"],0.25)
        row=snapshot["model_efficiency"]["models"][0]
        self.assertEqual(row["successful_calls"],1)
        self.assertEqual(row["failed_provider_attempts"],0)

    def test_watchdog_hourly_cadence_reports_reduced_control_plane_overhead(self):
        snapshot = build_sentinel_snapshot(
            cost_policy={"portfolio_ceiling":{"cost_usd":10}},
            cost_state={"reservations":[]},
            provider_registry={"providers":[]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            provider_health={"status":"UNKNOWN"},
            at="2026-09-26T20:00:00Z",
        )
        overhead=snapshot["github"]["watchdog_control_plane_overhead"]
        self.assertEqual(overhead["cron"],"53 * * * *")
        self.assertEqual(overhead["nominal_runs_per_day"],24)
        self.assertEqual(overhead["nominal_max_runner_minutes_per_day"],72)

    def test_publication_gate_ignores_volatile_metadata_only(self):
        current={"x":1,"snapshot_hash":"a","state_sources":{"sources":{"cost":{"source_run_id":1,"state_sequence":4}}}}
        previous=copy.deepcopy(current)
        previous["snapshot_hash"]="b"
        previous["state_sources"]["sources"]["cost"]["source_run_id"]=2
        self.assertFalse(should_publish(current,previous))
        previous["state_sources"]["sources"]["cost"]["state_sequence"]=5
        self.assertTrue(should_publish(current,previous))

if __name__=="__main__":
    unittest.main()
