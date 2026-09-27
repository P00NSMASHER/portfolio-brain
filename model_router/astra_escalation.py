"""Explicit, fail-closed advisory admission for the disabled Astra pilot.

This module produces a bounded route request, never an authority decision. The
ordinary model router cannot select Astra because the checked-in model is disabled.
"""
from __future__ import annotations

import copy
import math
import os
import re

from model_router.model_router import ModelRouterError, load, provider_registry, required_tier, route_request

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FIELDS = {
    "request_id", "project_ids", "task_kind", "consequence", "data_classification",
    "authority_class", "builder_independence_group", "source_commit_shas",
    "context_hash", "evidence_refs", "cheaper_route_receipt_ref",
    "cheaper_route_outcome", "decision_outcome_ref", "max_cost_usd",
    "max_input_tokens", "max_output_tokens", "reasoning_effort",
}


def configuration():
    return load("model_router/ASTRA_ESCALATION_POLICY.json")


def validate_astra_configuration():
    p = configuration()
    k = load("model_router/ASTRA_KILL_SWITCH.json")
    registry = provider_registry()
    models = [m for provider in registry["providers"] if provider["provider_id"] == "openai"
              for m in provider["models"] if m["model_id"] == p["model_id"]]
    if len(models) != 1 or models[0]["enabled"] is not False or models[0]["tier"] != 3:
        raise ModelRouterError("Astra must be registered once as a disabled Tier 3 route")
    m = models[0]
    if p["enabled"] is not False or k != {"schema_version": "1.0.0", "disabled": True,
                                     "reason": "Pilot requires reviewed enablement and explicit runtime opt-in."}:
        raise ModelRouterError("Astra checked-in pilot must be disabled")
    if (p["max_calls_per_utc_day"], p["max_daily_cost_usd"], p["max_call_cost_usd"]) != (2, 2.5, 1.25):
        raise ModelRouterError("Astra spend policy widened")
    if (p["max_input_tokens"], p["max_output_tokens"]) != (40000, 12000):
        raise ModelRouterError("Astra context policy widened")
    if (p["mode"] != "ADVISORY_ESCALATION_ONLY" or p["repository_enable_variable"] != "PORTFOLIO_ASTRA_ENABLED"
            or p["allowed_reasoning_efforts"] != ["medium", "high"]
            or p["allowed_data_classifications"] != ["PUBLIC", "SANITIZED"]
            or p["allowed_authority_classes"] != ["NONE", "OBSERVE"]
            or set(p["allowed_task_kinds"]) != {"ADVERSARIAL_REVIEW", "PROMOTION_VERIFICATION", "SELF_IMPROVEMENT_VERIFICATION", "HIGH_IMPACT_AUDIT"}
            or p["minimum_verified_outcomes_for_routing_adaptation"] < 3
            or p["retry_policy"] != "NO_AUTOMATIC_RETRY_AFTER_UNCERTAIN_OUTCOME"):
        raise ModelRouterError("Astra safety policy weakened")
    if (m["pricing"]["input_usd_per_million_tokens"], m["pricing"]["output_usd_per_million_tokens"]) != (10, 50):
        raise ModelRouterError("Astra pricing changed; re-review before enabling")
    cap = load("cost_governor/COST_GOVERNOR_POLICY.json")["provider_model_overrides"]["openai::gpt-6-astra"]
    if cap["cost_usd"] > p["max_daily_cost_usd"] or cap["model_calls"] > p["max_calls_per_utc_day"] or cap["api_calls"] > p["max_calls_per_utc_day"] or cap["input_tokens"] > 80000 or cap["output_tokens"] > 24000:
        raise ModelRouterError("Astra cost-governor ceiling widened")
    return True


def admit_escalation(candidate, *, policy_data=None, kill_data=None, environment=None):
    """Return (reason, route request). A disabled pilot returns no executable request.

    Candidate contains reference metadata only; no source text, prompts or secrets.
    The caller must verify that referenced evidence exists before acting on advice.
    """
    p = policy_data if policy_data is not None else configuration()
    k = kill_data if kill_data is not None else load("model_router/ASTRA_KILL_SWITCH.json")
    env = environment if environment is not None else os.environ
    if not isinstance(candidate, dict) or set(candidate) != _FIELDS:
        return "INVALID_CONTEXT_PACK", None
    if p.get("enabled") is not True or k.get("disabled") is not False or env.get(p.get("repository_enable_variable")) != "1":
        return "DISABLED", None
    refs = candidate["evidence_refs"]
    shas = candidate["source_commit_shas"]
    if (not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x and len(x) <= 256 for x in refs)
            or not isinstance(shas, list) or not shas or not all(isinstance(x, str) and _SHA.fullmatch(x) for x in shas)
            or not isinstance(candidate["context_hash"], str) or not _DIGEST.fullmatch(candidate["context_hash"])
            or not isinstance(candidate["cheaper_route_receipt_ref"], str) or not candidate["cheaper_route_receipt_ref"]
            or not isinstance(candidate["decision_outcome_ref"], str) or not candidate["decision_outcome_ref"]):
        return "MISSING_EVIDENCE", None
    if candidate["cheaper_route_outcome"] not in {"INSUFFICIENT", "BLOCKED"}:
        return "CHEAPER_ROUTE_NOT_EXHAUSTED", None
    if candidate["consequence"] not in {"HIGH", "CRITICAL"} or candidate["task_kind"] not in p["allowed_task_kinds"]:
        return "NOT_ESCALATION_WORK", None
    if candidate["data_classification"] not in p["allowed_data_classifications"] or candidate["authority_class"] not in p["allowed_authority_classes"]:
        return "PRIVACY_OR_AUTHORITY_BLOCKED", None
    if not candidate["builder_independence_group"] or candidate["builder_independence_group"] == "openai-astra":
        return "INDEPENDENCE_BLOCKED", None
    if candidate["reasoning_effort"] not in p["allowed_reasoning_efforts"]:
        return "EFFORT_BLOCKED", None
    cost = candidate["max_cost_usd"]
    inp = candidate["max_input_tokens"]
    out = candidate["max_output_tokens"]
    if (type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0 or cost > p["max_call_cost_usd"]
            or type(inp) is not int or inp <= 0 or inp > p["max_input_tokens"]
            or type(out) is not int or out <= 0 or out > p["max_output_tokens"]
            or (inp * 10 + out * 50) / 1_000_000 > cost):
        return "COST_OR_CONTEXT_BLOCKED", None
    request = {
        "schema_version": "1.0.0", "request_id": candidate["request_id"],
        "project_ids": candidate["project_ids"], "task_kind": candidate["task_kind"],
        "deterministic_sufficient": False, "consequence": candidate["consequence"],
        "data_classification": candidate["data_classification"],
        "authority_class": candidate["authority_class"], "requires_independent_adversarial": True,
        "builder_independence_group": candidate["builder_independence_group"],
        "max_cost_usd": cost, "max_input_tokens": inp, "max_output_tokens": out,
        "provider_allowlist": ["openai"], "evidence_refs": refs + [candidate["cheaper_route_receipt_ref"], candidate["decision_outcome_ref"], candidate["context_hash"]] + shas,
    }
    try:
        if required_tier(request) != 3:
            return "TIER_BLOCKED", None
    except (ModelRouterError, TypeError, KeyError):
        return "INVALID_CONTEXT_PACK", None
    return "ADMITTED_ADVISORY_ONLY", request


def route_admitted_escalation(candidate, *, policy_data=None, kill_data=None, environment=None):
    """Select Astra only after explicit admission; cost reservation still required."""
    status, request = admit_escalation(candidate, policy_data=policy_data, kill_data=kill_data, environment=environment)
    if request is None:
        return status, None, None
    registry = _admitted_registry()
    route = route_request(request, registry)
    if route["status"] != "ROUTED" or route["model_id"] != "gpt-6-astra":
        return "ROUTE_BLOCKED", None, None
    return status, request, route


def _admitted_registry():
    registry = copy.deepcopy(provider_registry())
    for provider in registry["providers"]:
        for model in provider["models"]:
            if model["tier"] > 0:
                model["enabled"] = provider["provider_id"] == "openai" and model["model_id"] == "gpt-6-astra"
    return registry
