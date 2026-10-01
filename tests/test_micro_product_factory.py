import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load():
    return json.loads((ROOT / "operations" / "MICRO_PRODUCT_FACTORY.json").read_text(encoding="utf-8"))

def test_factory_is_retired_plan_only_and_zero_budget():
    doc = load()
    assert doc["authority_class"] == "PLAN_ONLY"
    assert doc["status"] == "RETIRED"
    assert doc["north_star"] == "VERIFIED_ENGINEERING_IMPROVEMENT"
    assert doc["build_caps"]["max_hours_per_sku"] == 0
    assert doc["build_caps"]["max_paid_ai_spend_usd_per_sku"] == 0
    assert doc["first_launch_batch"] == []
    assert doc["launch_batch_state"] == "RETIRED_NO_FURTHER_COMMERCIAL_WORK"
    assert doc["factory_guardrails"]["status"] == "RETIRED"

def test_historical_skus_remain_unique_but_cannot_authorize_new_work():
    doc = load()
    skus = doc["skus"]
    ids = [row["sku_id"] for row in skus]
    ranks = [row["rank"] for row in skus]
    assert len(ids) == len(set(ids))
    assert len(ranks) == len(set(ranks))
    assert min(ranks) == 1
    assert all(row["buyer_problem"] and row["reuse_source"] and row["reuse_boundary"] for row in skus)
    assert all("Retired historical SKU" in row["build_prompt"] for row in skus)
    assert all("Do not build, publish, market, expand" in row["build_prompt"] for row in skus)

def test_historical_outcomes_are_preserved_without_future_revenue_assumption():
    doc = load()
    assert doc["verified_revenue_usd"] >= 0
    assert doc["verified_sales_count"] >= 0
    assert doc["published_count"] >= 0
    assert any("historical evidence only" in rule.lower() for rule in doc["portfolio_rules"])
