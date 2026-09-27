import copy
import os
import unittest
from unittest.mock import patch

from cost_governor.cost_governor import load_state
from model_router.astra_escalation import admit_escalation, configuration, route_admitted_escalation, validate_astra_configuration
from model_router.model_router import provider_registry, route_request
from model_router.openai_executor import OpenAIExecutorError, execute_openai


def candidate():
    return {
        "request_id": "MRQ-ASTRA-TEST", "project_ids": ["PRJ-000"],
        "task_kind": "ADVERSARIAL_REVIEW", "consequence": "HIGH",
        "data_classification": "SANITIZED", "authority_class": "OBSERVE",
        "builder_independence_group": "openai-terra", "source_commit_shas": ["a" * 40],
        "context_hash": "sha256:" + "b" * 64, "evidence_refs": ["proof:test"],
        "cheaper_route_receipt_ref": "MINV-CHEAPER", "cheaper_route_outcome": "INSUFFICIENT",
        "decision_outcome_ref": "outcome:test", "max_cost_usd": 1.25,
        "max_input_tokens": 40000, "max_output_tokens": 12000,
        "reasoning_effort": "medium",
    }


class AstraEscalationTests(unittest.TestCase):
    def test_configuration_and_default_denial(self):
        self.assertTrue(validate_astra_configuration())
        self.assertEqual(admit_escalation(candidate())[0], "DISABLED")
        normal = {
            "schema_version": "1.0.0", "request_id": "MRQ-NORMAL", "project_ids": ["PRJ-000"],
            "task_kind": "ADVERSARIAL_REVIEW", "deterministic_sufficient": False,
            "consequence": "HIGH", "data_classification": "SANITIZED", "authority_class": "OBSERVE",
            "requires_independent_adversarial": True, "builder_independence_group": "openai-terra",
            "max_cost_usd": 1.25, "max_input_tokens": 40000, "max_output_tokens": 12000,
            "provider_allowlist": ["openai"], "evidence_refs": ["test:evidence"],
        }
        self.assertEqual(route_request(normal, provider_registry())["model_id"], "gpt-5.6-sol")

    def test_escalation_gates(self):
        policy = copy.deepcopy(configuration()); policy["enabled"] = True
        kill = {"disabled": False}
        opts = {"policy_data": policy, "kill_data": kill, "environment": {"PORTFOLIO_ASTRA_ENABLED": "1"}}
        item = candidate()
        status, request, route = route_admitted_escalation(item, **opts)
        self.assertEqual((status, route["model_id"], route["tier"]), ("ADMITTED_ADVISORY_ONLY", "gpt-6-astra", 3))
        self.assertEqual((route["can_grant_authority"], route["can_upgrade_evidence"]), (False, False))
        for changes, expected in [
            ({"cheaper_route_outcome": "SUFFICIENT"}, "CHEAPER_ROUTE_NOT_EXHAUSTED"),
            ({"authority_class": "ACT"}, "PRIVACY_OR_AUTHORITY_BLOCKED"),
            ({"data_classification": "PRIVATE_REFERENCE_ONLY"}, "PRIVACY_OR_AUTHORITY_BLOCKED"),
            ({"consequence": "LOW"}, "NOT_ESCALATION_WORK"),
            ({"reasoning_effort": "xhigh"}, "EFFORT_BLOCKED"),
            ({"max_cost_usd": 0.99}, "COST_OR_CONTEXT_BLOCKED"),
            ({"builder_independence_group": "openai-astra"}, "INDEPENDENCE_BLOCKED"),
        ]:
            bad = dict(item, **changes)
            self.assertEqual(admit_escalation(bad, **opts)[0], expected)
        self.assertEqual(admit_escalation(item, policy_data=policy, kill_data=kill, environment={})[0], "DISABLED")
        self.assertEqual(admit_escalation(item, policy_data=policy, kill_data={"disabled": True}, environment=opts["environment"])[0], "DISABLED")

    def test_executor_blocks_before_reservation_when_disabled(self):
        with self.assertRaisesRegex(OpenAIExecutorError, "Astra admission blocked"):
            execute_openai({}, "input", load_state(), astra_candidate=candidate(), transport=lambda *args: self.fail("network called"))

    def test_pilot_uses_existing_cost_reservation_and_receipt(self):
        policy = copy.deepcopy(configuration()); policy["enabled"] = True
        item = candidate()
        with patch("model_router.astra_escalation.configuration", return_value=policy), patch("model_router.astra_escalation.load", return_value={"disabled": False}), patch.dict(os.environ, {"PORTFOLIO_ASTRA_ENABLED": "1", "PORTFOLIO_MODEL_API_KEY": "test-key"}):
            status, req, route = route_admitted_escalation(item)
            self.assertEqual(status, "ADMITTED_ADVISORY_ONLY")
            state, out = execute_openai(req, "sanitized", load_state(), astra_candidate=item, at="2026-09-25T20:00:00Z", transport=lambda *args: {"id": "resp_astra", "output_text": "advice", "usage": {"input_tokens": 100, "output_tokens": 20}})
            self.assertEqual(out["receipt"]["model_id"], "gpt-6-astra")
            self.assertFalse(out["receipt"]["authority_granted"])
            self.assertEqual(state["reservations"][-1]["status"], "COMMITTED")
            with self.assertRaisesRegex(OpenAIExecutorError, "retry"):
                execute_openai(req, "sanitized", load_state(), astra_candidate=item, attempt=2, transport=lambda *args: self.fail("network called"))


if __name__ == "__main__":
    unittest.main()
