#!/usr/bin/env python3
"""External-value operating loop for Portfolio Brain.

This module is deliberately deterministic and advisory. It converts existing,
sanitized portfolio evidence into the small set of external milestones that can
justify work, business allocation, or an owner checkpoint.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class ValueLoopError(ValueError):
    pass


def req(ok: bool, message: str) -> None:
    if not ok:
        raise ValueLoopError(message)


def load(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def policy() -> dict:
    return load("operations/VALUE_LOOP_POLICY.json")


def classify_technical_outcome(outcome: dict) -> str | None:
    if (
        isinstance(outcome, dict)
        and outcome.get("value_status") == "VALUE_OUTCOME_VERIFIED"
        and outcome.get("evidence_state") == "VERIFIED"
    ):
        return "TECHNICAL_VERIFIED"
    return None


def classify_market_observation(observation: dict) -> str | None:
    if not isinstance(observation, dict):
        return None
    if observation.get("evidence_state") != "VERIFIED":
        return None
    if observation.get("source_kind") in {
        "CHATGPT_GMAIL_CONNECTOR_SANITIZED_OBSERVATION",
        "CHATGPT_STRIPE_CONNECTOR_SANITIZED_OBSERVATION",
    }:
        return "MARKET_VERIFIED"
    return None


def classify_factory_revenue(factory: dict) -> str | None:
    sales = factory.get("verified_sales_count")
    revenue = factory.get("verified_revenue_usd")
    req(type(sales) is int and sales >= 0, "verified_sales_count invalid")
    req(type(revenue) in {int, float} and float(revenue) >= 0, "verified_revenue_usd invalid")
    return "REVENUE_VERIFIED" if sales > 0 or float(revenue) > 0 else None


def investment_credit_allowed(evidence_class: str | None) -> bool:
    return evidence_class in set(policy()["investment_credit_classes"])


def technical_routing_credit_allowed(evidence_class: str | None) -> bool:
    return evidence_class in set(policy()["technical_routing_credit_classes"])


def _action_id(source_ref: str, milestone: str) -> str:
    seed = canon({"source_ref": source_ref, "milestone": milestone})
    return "OACT-" + hashlib.sha256(seed.encode()).hexdigest()[:20].upper()


def _owner_action_for_publish(sku: dict) -> dict:
    action = {
        "action_id": _action_id(sku["sku_id"], "PUBLISH_PRODUCT"),
        "status": "WAITING_FOR_OWNER",
        "authority": "HUMAN_APPROVAL_REQUIRED",
        "external_milestone": "PUBLISH_PRODUCT",
        "source_ref": sku["sku_id"],
        "title": f"Publish {sku['sku_id']}",
        "instruction": (
            f"OWNER ACTION REQUIRED: Publish {sku['sku_id']} ({sku['name']}) at "
            f"${float(sku['price_usd']):.2f} using {sku['bundle_name']}."
        ),
        "price_usd": float(sku["price_usd"]),
        "package": sku["bundle_name"],
        "resume_evidence": [
            f"{sku['sku_id']}.publication_status=PUBLISHED",
            "verified marketplace listing observation",
        ],
    }
    action["action_hash"] = digest(action)
    return action


def _publish_ready(factory: dict) -> list[dict]:
    if factory.get("status") != "ACTIVE":
        return []
    return sorted(
        [
            sku for sku in factory.get("skus", [])
            if sku.get("status") == "READY_FOR_PUBLISH"
            and sku.get("publication_status") == "NOT_PUBLISHED"
        ],
        key=lambda sku: (sku.get("rank", 999), sku.get("sku_id", "")),
    )


def _qa_blockers(factory: dict) -> list[dict]:
    if factory.get("status") != "ACTIVE":
        return []
    rows = []
    for sku in sorted(factory.get("skus", []), key=lambda row: (row.get("rank", 999), row.get("sku_id", ""))):
        if sku.get("status") != "READY_FOR_RUNTIME_QA":
            continue
        rows.append({
            "source_ref": sku["sku_id"],
            "external_milestone": "PUBLISH_PRODUCT",
            "value_lane": "INTERNAL_BLOCKER",
            "work_type": "TEST",
            "assigned_agent_id": "AGT-TESTER",
            "agent_goal_type": "REGRESSION_VALIDATION",
            "required_authority": "EXPERIMENT",
            "project_ids": ["PRJ-000"],
            "reason": f"Runtime QA is the remaining technical blocker before {sku['sku_id']} can be published.",
            "evidence_refs": [
                "operations/MICRO_PRODUCT_FACTORY.json",
                f"sku:{sku['sku_id']}",
                "external-milestone:PUBLISH_PRODUCT",
            ],
        })
    return rows


def build_signal_snapshot(*, hunter_proposal_state: dict | None = None, commercial: dict | None = None, factory: dict | None = None) -> dict:
    commercial = commercial or load("commercial_evidence/CURRENT_SANITIZED_OBSERVATION.json")
    factory = factory or load("operations/MICRO_PRODUCT_FACTORY.json")
    supply = []
    if isinstance(hunter_proposal_state, dict):
        for proposal in hunter_proposal_state.get("proposals", []):
            supply.append({
                "signal_role": "SUPPLY",
                "source_kind": "PUBLIC_GITHUB",
                "source_ref": proposal.get("proposal_id"),
                "evidence_class": None,
                "investment_credit": False,
            })
    market_class = classify_market_observation(commercial)
    demand = [{
        "signal_role": "DEMAND",
        "source_kind": commercial["source_kind"],
        "source_ref": commercial["observation_id"],
        "evidence_state": commercial["evidence_state"],
        "evidence_class": market_class,
        "investment_credit": investment_credit_allowed(market_class),
        "threads_observed": commercial.get("threads_observed"),
        "threads_with_human_reply": commercial.get("threads_with_human_reply"),
    }]
    revenue_class = classify_factory_revenue(factory)
    if revenue_class is not None:
        demand.append({
            "signal_role": "DEMAND",
            "source_kind": "VERIFIED_MARKETPLACE_REVENUE",
            "source_ref": factory["factory_id"],
            "evidence_state": "VERIFIED",
            "evidence_class": revenue_class,
            "investment_credit": True,
            "verified_sales_count": factory["verified_sales_count"],
            "verified_revenue_usd": factory["verified_revenue_usd"],
        })
    return {
        "schema_version": "1.0.0",
        "supply_signals": supply,
        "demand_signals": demand,
        "github_supply_creates_demand": False,
        "verified_demand_count": sum(1 for row in demand if row.get("evidence_class") in {"MARKET_VERIFIED", "REVENUE_VERIFIED"}),
        "investment_credit_signal_count": sum(1 for row in demand if row.get("investment_credit") is True),
    }


def build_value_loop_snapshot(*, hunter_proposal_state: dict | None = None, commercial: dict | None = None, factory: dict | None = None) -> dict:
    p = policy()
    factory = factory or load("operations/MICRO_PRODUCT_FACTORY.json")
    commercial = commercial or load("commercial_evidence/CURRENT_SANITIZED_OBSERVATION.json")
    signals = build_signal_snapshot(hunter_proposal_state=hunter_proposal_state, commercial=commercial, factory=factory)
    ready = _publish_ready(factory)
    owner_actions = [_owner_action_for_publish(ready[0])] if ready else []
    blockers = _qa_blockers(factory)

    if factory.get("status") != "ACTIVE":
        active = None
        closest = None
        blocker = None
    elif ready:
        active = {
            "experiment_id": f"EXT-{ready[0]['sku_id']}-PUBLISH-PRICE-DEMAND",
            "kind": "PRICE_AND_DEMAND_TEST",
            "source_ref": ready[0]["sku_id"],
            "status": "WAITING_FOR_OWNER",
            "external_milestone": "PUBLISH_PRODUCT",
            "description": f"Publish {ready[0]['name']} at ${float(ready[0]['price_usd']):.2f} and measure real buyer response.",
        }
        closest = "PUBLISH_PRODUCT"
        blocker = "OWNER_PUBLISH_REQUIRED"
    elif factory.get("published_count", 0) > 0 and factory.get("verified_sales_count", 0) == 0:
        active = {
            "experiment_id": "EXT-MARKETPLACE-DEMAND-OBSERVATION",
            "kind": "MARKET_DEMAND_OBSERVATION",
            "source_ref": factory["factory_id"],
            "status": "ACTIVE",
            "external_milestone": "VALIDATE_DEMAND",
            "description": "Observe published products for verified buyer, review, support, and price-response signals.",
        }
        closest = "VALIDATE_DEMAND"
        blocker = "WAITING_FOR_VERIFIED_MARKET_SIGNAL"
    elif factory.get("verified_sales_count", 0) > 0:
        active = {
            "experiment_id": "EXT-POST-SALE-FEEDBACK",
            "kind": "CUSTOMER_SIGNAL",
            "source_ref": factory["factory_id"],
            "status": "ACTIVE",
            "external_milestone": "GET_BUYER_RESPONSE",
            "description": "Use verified sales/support evidence to decide which adjacent product to build next.",
        }
        closest = "GET_BUYER_RESPONSE"
        blocker = None
    else:
        active = None
        closest = blockers[0]["external_milestone"] if blockers else "VALIDATE_DEMAND"
        blocker = blockers[0]["reason"] if blockers else "NO_ACTIVE_EXTERNAL_EXPERIMENT"

    verified_market = [
        row for row in signals["demand_signals"]
        if row.get("evidence_class") in {"MARKET_VERIFIED", "REVENUE_VERIFIED"}
    ]
    last_verified = verified_market[-1] if verified_market else None
    out = {
        "schema_version": "1.0.0",
        "policy_id": p["policy_id"],
        "money_earned_usd": float(factory["verified_revenue_usd"]),
        "verified_sales_count": int(factory["verified_sales_count"]),
        "active_external_experiment": active,
        "closest_external_milestone": closest,
        "current_blocker": blocker,
        "owner_action_queue": owner_actions,
        "blocking_work": blockers,
        "last_verified_market_signal": last_verified,
        "latest_market_observation": {
            "source_ref": commercial["observation_id"],
            "evidence_state": commercial["evidence_state"],
            "threads_observed": commercial["threads_observed"],
            "threads_with_human_reply": commercial["threads_with_human_reply"],
        },
        "signals": signals,
        "business_investment_evidence_classes": list(p["investment_credit_classes"]),
        "technical_only_evidence_class": "TECHNICAL_VERIFIED",
    }
    out["snapshot_hash"] = digest(out)
    return out


def primary_operator_view(snapshot: dict | None = None) -> dict:
    snapshot = snapshot or build_value_loop_snapshot()
    actions = snapshot["owner_action_queue"]
    return {
        "money_earned": f"${snapshot['money_earned_usd']:.2f}",
        "active_external_experiment": None if snapshot["active_external_experiment"] is None else snapshot["active_external_experiment"]["description"],
        "closest_external_milestone": snapshot["closest_external_milestone"],
        "current_blocker": snapshot["current_blocker"],
        "action_required_from_owner": None if not actions else actions[0]["instruction"],
        "last_verified_customer_or_market_signal": snapshot["last_verified_market_signal"],
    }


if __name__ == "__main__":
    print(json.dumps(build_value_loop_snapshot(), sort_keys=True))
