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

    def test_legacy_ready_without_verified_usability_is_normalized_unknown(self):
        snapshot = build_sentinel_snapshot(
            cost_policy={"portfolio_ceiling":{"cost_usd":10}},
            cost_state={"reservations":[]},
            provider_registry={"providers":[]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            provider_health={
                "schema_version":"1.0.0","status":"READY",
                "cost_gate_status":"COMMITTED",
            },
            at="2026-09-30T14:00:00Z",
        )
        readiness=snapshot["provider_readiness"]
        self.assertEqual(readiness["status"],"UNKNOWN")
        self.assertIsNone(readiness["configured"])
        self.assertIsNone(readiness["enabled"])
        self.assertIsNone(readiness["credential_ready"])
        self.assertIsNone(readiness["call_verified"])
        self.assertEqual(snapshot["allocation"]["next_paid_action"],"RESTORE_PROVIDER_READINESS_BEFORE_PAID_WORK")

    def test_ready_requires_complete_verified_usability_vector(self):
        common = dict(
            cost_policy={"portfolio_ceiling":{"cost_usd":10}},
            cost_state={"reservations":[]},
            provider_registry={"providers":[]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            at="2026-09-30T14:00:00Z",
        )
        config_only=build_sentinel_snapshot(
            **common,
            provider_health={
                "status":"READY","configured":True,"enabled":True,
                "credential_ready":True,"call_verified":False,
                "last_successful_at":"2026-09-30T13:55:00Z",
            },
        )
        self.assertEqual(config_only["provider_readiness"]["status"],"UNKNOWN")
        self.assertEqual(config_only["allocation"]["next_paid_action"],"RESTORE_PROVIDER_READINESS_BEFORE_PAID_WORK")
        verified=build_sentinel_snapshot(
            **common,
            provider_health={
                "status":"READY","configured":True,"enabled":True,
                "credential_ready":True,"call_verified":True,
                "last_successful_at":"2026-09-30T13:55:00Z",
            },
        )
        self.assertEqual(verified["provider_readiness"]["status"],"READY")
        self.assertEqual(verified["allocation"]["next_paid_action"],"ONE_BOUNDED_TERRA_DAILY_ANALYSIS")

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

    def test_durable_verified_feedback_is_attributed_per_model_not_globally(self):
        feedback={
            "schema_version":"1.0.0",
            "state_id":"portfolio-model-feedback-state",
            "sequence":2,
            "updated_at":"2026-09-27T03:45:00Z",
            "calls":[
                {"invocation_id":"INV-TERRA","provider_id":"openai","model_id":"gpt-5.6-terra","cost_usd":0.01177},
                {"invocation_id":"INV-SOL","provider_id":"openai","model_id":"gpt-5.6-sol","cost_usd":0.026428},
            ],
            "outcomes":[
                {"feedback_id":"FB-TERRA","invocation_id":"INV-TERRA","outcome_event_id":"MVOUT-1","evidence_state":"VERIFIED","outcome_value":1.0},
                {"feedback_id":"FB-SOL","invocation_id":"INV-SOL","outcome_event_id":"MVOUT-1","evidence_state":"VERIFIED","outcome_value":1.0},
            ],
            "routing_task_summaries":{
                "OPPORTUNITY_REASONING":{"T2::openai::gpt-5.6-terra":{"verified_outcomes":1}},
                "PROMOTION_VERIFICATION":{"T3::openai::gpt-5.6-sol":{"verified_outcomes":1}},
            },
        }
        snapshot=build_sentinel_snapshot(
            cost_policy={"portfolio_ceiling":{
                "cost_usd":10,"input_tokens":1000000,"output_tokens":250000,
                "model_calls":40,"api_calls":80,"github_job_starts":120,"github_runner_minutes":600,
            }},
            cost_state={"reservations":[]},
            provider_registry={"providers":[{"provider_id":"openai","enabled":True,"models":[
                {"model_id":"gpt-5.6-luna","tier":1,"enabled":True,"pricing":{"input_usd_per_million_tokens":0.2,"output_usd_per_million_tokens":1.2}},
                {"model_id":"gpt-5.6-terra","tier":2,"enabled":True,"pricing":{"input_usd_per_million_tokens":2,"output_usd_per_million_tokens":12}},
                {"model_id":"gpt-5.6-sol","tier":3,"enabled":True,"pricing":{"input_usd_per_million_tokens":4,"output_usd_per_million_tokens":20}},
            ]}]},
            model_feedback_state=feedback,
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            provider_health={"status":"READY"},
            at="2026-09-27T04:00:00Z",
        )
        self.assertEqual(snapshot["model_efficiency"]["feedback_source"],"DURABLE_VERIFIED_FEEDBACK")
        self.assertEqual(snapshot["model_efficiency"]["verified_feedback_records"],2)
        self.assertEqual(snapshot["model_efficiency"]["verified_value_events"],1)
        rows={row["model_id"]:row for row in snapshot["model_efficiency"]["models"]}
        self.assertEqual(rows["gpt-5.6-terra"]["verified_outcomes_recorded"],1)
        self.assertEqual(rows["gpt-5.6-sol"]["verified_outcomes_recorded"],1)
        self.assertEqual(rows["gpt-5.6-luna"]["verified_outcomes_recorded"],0)
        self.assertEqual(rows["gpt-5.6-terra"]["value_signal"],"VERIFIED_VALUE_EVIDENCE")
        self.assertEqual(rows["gpt-5.6-sol"]["value_signal"],"VERIFIED_VALUE_EVIDENCE")
        self.assertEqual(rows["gpt-5.6-luna"]["value_signal"],"NO_SUCCESSFUL_CALL_BASELINE")
        self.assertEqual(rows["gpt-5.6-terra"]["spend_per_verified_outcome_usd"],0.01177)
        self.assertEqual(rows["gpt-5.6-sol"]["spend_per_verified_outcome_usd"],0.026428)

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

    def test_expired_reservation_is_included_in_effective_budget_usage(self):
        usage={
            "cost_usd":1.5,"input_tokens":2000,"output_tokens":400,
            "model_calls":1,"api_calls":1,
            "github_job_starts":0,"github_runner_minutes":0,
        }
        snapshot = build_sentinel_snapshot(
            cost_policy={"portfolio_ceiling":{
                "cost_usd":10,"input_tokens":10000,"output_tokens":5000,
                "model_calls":5,"api_calls":5,
                "github_job_starts":10,"github_runner_minutes":50,
            }},
            cost_state={"reservations":[{
                "created_at":"2026-09-26T10:00:00Z","expires_at":"2026-09-26T10:30:00Z",
                "status":"EXPIRED","resource_kind":"MODEL_CALL",
                "provider_id":"openai","model_id":"gpt-5.6-terra",
                "actual_usage":None,"estimated_usage":usage,"evidence_refs":[],
            }]},
            provider_registry={"providers":[]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            provider_health={"status":"READY"},
            at="2026-09-26T20:00:00Z",
        )
        budget=snapshot["budget"]
        self.assertEqual(budget["committed_usage"]["cost_usd"],0)
        self.assertEqual(budget["active_reserved_usage"]["cost_usd"],0)
        self.assertEqual(budget["fail_closed_expired_usage"]["cost_usd"],1.5)
        self.assertEqual(budget["effective_budget_usage"]["cost_usd"],1.5)
        self.assertEqual(budget["remaining_headroom"]["cost_usd"],8.5)

    def test_elapsed_active_reservation_is_classified_as_fail_closed(self):
        usage={
            "cost_usd":0,"input_tokens":0,"output_tokens":0,
            "model_calls":0,"api_calls":0,
            "github_job_starts":1,"github_runner_minutes":5,
        }
        snapshot = build_sentinel_snapshot(
            cost_policy={"portfolio_ceiling":usage},
            cost_state={"reservations":[{
                "created_at":"2026-09-26T10:00:00Z","expires_at":"2026-09-26T10:30:00Z",
                "status":"RESERVED","resource_kind":"GITHUB_JOB",
                "provider_id":None,"model_id":None,
                "actual_usage":None,"estimated_usage":usage,"evidence_refs":[],
            }]},
            provider_registry={"providers":[]},
            model_ledger={"calls":[],"outcomes":[]},
            action_policy={"allowed_actions":{"CUSTOMER_EMAIL":{"max_per_utc_day":25}}},
            action_ledger={"executions":[]},
            provider_health={"status":"READY"},
            at="2026-09-26T20:00:00Z",
        )
        self.assertEqual(snapshot["budget"]["active_reserved_usage"]["github_job_starts"],0)
        self.assertEqual(snapshot["budget"]["fail_closed_expired_usage"]["github_job_starts"],1)
        self.assertEqual(snapshot["budget"]["remaining_headroom"]["github_job_starts"],0)

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
        self.assertEqual(overhead["nominal_max_runner_minutes_per_day"],192)

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
