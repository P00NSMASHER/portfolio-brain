import copy
import json
import unittest
from pathlib import Path

from hunting.autonomous_hunter import load_seed_state as hunter_seed
from learning.live_observations import load_seed_state as learning_seed
from learning.outcome_ingestion import OutcomeIngestionError, ingest_verified_outcome
from model_router.feedback_state import load_seed_state as model_seed
from value_proof.model_task import digest, load_contract
from value_proof.verifier import load_verifier_contract

ROOT = Path(__file__).resolve().parents[1]


def call_receipt(*, invocation_id, tier, model_id, group, request_id, route_id):
    core = {
        "schema_version": "1.0.0",
        "invocation_id": invocation_id,
        "request_id": request_id,
        "route_id": route_id,
        "tier": tier,
        "provider_id": "openai",
        "model_id": model_id,
        "independence_group": group,
        "status": "SUCCESS",
        "started_at": "2026-09-27T03:44:00Z",
        "completed_at": "2026-09-27T03:44:10Z",
        "input_tokens": 100,
        "output_tokens": 20,
        "cost_usd": 0.01,
        "cost_basis": "CONFIGURED_RATE_CONSERVATIVE_INPUT",
        "latency_ms": 1000,
        "input_hash": "sha256:" + "1" * 64,
        "output_hash": "sha256:" + "2" * 64,
        "authority_granted": False,
        "evidence_upgraded": False,
        "downstream_outcome_ids": [],
    }
    from model_router.model_router import hashv
    return {**core, "receipt_hash": hashv(core)}


def value_outcome(task, builder, verifier):
    source = task["source_candidate"]
    core = {
        "schema_version": "1.0.0",
        "outcome_id": "MVOUT-STEP10-CONTROLLED",
        "task_id": task["task_id"],
        "project_ids": task["project_ids"],
        "hunter_finding_id": source["finding_id"],
        "hunter_experiment_proposal_id": source["experiment_proposal_id"],
        "repository_full_name": source["repository_full_name"],
        "revision": source["revision"],
        "evidence_pack_hash": "sha256:" + "3" * 64,
        "builder_execution_receipt_hash": "sha256:" + "4" * 64,
        "builder_provider_receipt_hash": builder["receipt_hash"],
        "builder_model_id": builder["model_id"],
        "deterministic_verification_receipt_hash": "sha256:" + "5" * 64,
        "independent_verification_receipt_hash": "sha256:" + "6" * 64,
        "verifier_provider_receipt_hash": verifier["receipt_hash"],
        "verifier_model_id": verifier["model_id"],
        "value_status": "VALUE_OUTCOME_VERIFIED",
        "value_class": "TECHNICAL_RESEARCH_DECISION_UTILITY",
        "decision": "PROCEED_TO_BOUNDED_INTEGRATION_REVIEW",
        "decision_basis": {
            "builder_recommendation": "DEEPER_BOUNDED_REVIEW",
            "builder_confidence": 0.8,
            "verifier_confidence": 0.9,
            "evidence_supported": True,
            "contract_compliant": True,
            "useful_for_bounded_followup": True,
        },
        "evidence_state": "VERIFIED",
        "useful_outcome": True,
        "external_customer_value_claimed": False,
        "rights_state": "OPERATOR_ASSUMED",
        "capability_verification_claimed": False,
        "deployment_authorized": False,
        "authority_granted": False,
        "evidence_upgraded": False,
        "provenance_refs": ["test:step10-controlled"],
    }
    return {**core, "outcome_hash": digest(core)}


class VerifiedOutcomeIngestionTests(unittest.TestCase):
    def setUp(self):
        self.task = load_contract()
        self.verifier_contract = load_verifier_contract()
        self.builder = call_receipt(
            invocation_id="MINV-STEP10-B", tier=2, model_id="gpt-5.6-terra",
            group="openai-terra", request_id="MRQ-STEP10-B", route_id="MRT-STEP10-B"
        )
        self.verifier = call_receipt(
            invocation_id="MINV-STEP10-V", tier=3, model_id="gpt-5.6-sol",
            group="openai-sol", request_id="MRQ-STEP10-V", route_id="MRT-STEP10-V"
        )
        self.outcome = value_outcome(self.task, self.builder, self.verifier)
        self.cases = json.loads((ROOT / "hunting" / "CONTROLLED_PROOF_CASES.json").read_text())

    def apply(self, hunter, model, learning, outcome=None):
        return ingest_verified_outcome(
            task_contract=self.task,
            verifier_contract=self.verifier_contract,
            outcome=outcome or self.outcome,
            builder_provider_receipt=self.builder,
            verifier_provider_receipt=self.verifier,
            hunter_state=hunter,
            model_feedback_state=model,
            learning_state=learning,
            controlled_cases=self.cases,
            at="2026-09-30T14:00:00Z",
        )

    def test_same_verified_outcome_consumed_twice_is_one_logical_ingestion(self):
        hunter, model, learning = hunter_seed(), model_seed(), learning_seed()
        h1, m1, l1, _, first = self.apply(hunter, model, learning)
        h2, m2, l2, _, second = self.apply(h1, m1, l1)
        self.assertEqual(first["status"], "INGESTED")
        self.assertTrue(first["logical_ingestion_applied"])
        self.assertEqual(second["status"], "ALREADY_INGESTED")
        self.assertFalse(second["logical_ingestion_applied"])
        self.assertEqual(h1, h2)
        self.assertEqual(m1, m2)
        self.assertEqual(l1, l2)
        self.assertEqual(len(l2["applied_source_keys"]), 1)
        self.assertEqual(len(l2["observations"]), 3)

    def test_unverified_or_malformed_outcome_rejected_without_mutation(self):
        hunter, model, learning = hunter_seed(), model_seed(), learning_seed()
        before = copy.deepcopy((hunter, model, learning))
        bad = copy.deepcopy(self.outcome)
        bad["evidence_state"] = "OBSERVED"
        body = dict(bad)
        body.pop("outcome_hash")
        bad["outcome_hash"] = digest(body)
        with self.assertRaises(Exception):
            self.apply(hunter, model, learning, bad)
        self.assertEqual((hunter, model, learning), before)

    def test_same_outcome_id_with_different_hash_fails_closed(self):
        hunter, model, learning = hunter_seed(), model_seed(), learning_seed()
        h1, m1, l1, _, _ = self.apply(hunter, model, learning)
        conflict = copy.deepcopy(self.outcome)
        conflict["provenance_refs"] = ["test:conflicting-identity"]
        body = dict(conflict)
        body.pop("outcome_hash")
        conflict["outcome_hash"] = digest(body)
        with self.assertRaises(OutcomeIngestionError):
            self.apply(h1, m1, l1, conflict)

    def test_verified_outcome_updates_existing_intended_projections_only(self):
        hunter, model, learning = hunter_seed(), model_seed(), learning_seed()
        h1, m1, l1, feedback, receipt = self.apply(hunter, model, learning)
        strategy = feedback["hunter_strategy_id"]
        self.assertEqual(h1["strategy_stats"][strategy]["verified_value_outcomes"], 1)
        self.assertEqual(m1["sequence"], 2)
        self.assertEqual(l1["sequence"], 1)
        self.assertEqual(receipt["projections"]["learning"]["added_observations"], 3)
        self.assertFalse(receipt["static_checked_in_knowledge_mutated"])
        self.assertFalse(receipt["market_verified"])
        self.assertFalse(receipt["revenue_verified"])


if __name__ == "__main__":
    unittest.main()
