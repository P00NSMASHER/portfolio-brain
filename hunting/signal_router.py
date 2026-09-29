#!/usr/bin/env python3
"""Keep Hunter supply discovery separate from market demand evidence."""
from __future__ import annotations
import json
from operations.value_loop import build_signal_snapshot, digest


def build_hunter_signal_snapshot(hunter_proposal_state: dict) -> dict:
    base=build_signal_snapshot(hunter_proposal_state=hunter_proposal_state)
    body={
        "schema_version":"1.0.0",
        "signal_router_id":"portfolio-hunter-supply-demand-v1",
        "supply_sensor":"PUBLIC_GITHUB",
        "demand_sensor":"PORTFOLIO_SANITIZED_MARKET_EVIDENCE",
        "supply_signals":base["supply_signals"],
        "demand_signals":base["demand_signals"],
        "verified_demand_count":base["verified_demand_count"],
        "investment_credit_signal_count":base["investment_credit_signal_count"],
        "github_supply_creates_demand":False,
        "commercial_build_authorized_by_supply_only":False,
    }
    return {**body,"snapshot_hash":digest(body)}


if __name__=="__main__":
    from hunting.proposal_state import load_seed_state
    print(json.dumps(build_hunter_signal_snapshot(load_seed_state()),sort_keys=True))
