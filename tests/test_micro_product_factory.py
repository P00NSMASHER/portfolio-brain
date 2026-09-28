import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load():
    return json.loads((ROOT / "operations" / "MICRO_PRODUCT_FACTORY.json").read_text(encoding="utf-8"))

def test_factory_is_bounded_and_plan_only():
    doc = load()
    assert doc["authority_class"] == "PLAN_ONLY"
    assert doc["status"] == "ACTIVE"
    assert doc["market"] == "Roblox Creator Store"
    assert doc["build_caps"]["max_hours_per_sku"] <= 4
    assert doc["build_caps"]["max_paid_ai_spend_usd_per_sku"] <= 10
    assert doc["build_caps"]["initial_price_min_usd"] >= 2.99
    assert doc["build_caps"]["initial_price_max_usd"] <= 9.99

def test_skus_are_unique_ranked_and_bounded():
    doc = load()
    skus = doc["skus"]
    ids = [row["sku_id"] for row in skus]
    ranks = [row["rank"] for row in skus]
    assert len(ids) == len(set(ids))
    assert len(ranks) == len(set(ranks))
    assert min(ranks) == 1
    assert all(row["status"] in {"CANDIDATE","BACKLOG","READY","PUBLISHED","HOLD","KILL"} for row in skus)
    assert all(doc["build_caps"]["initial_price_min_usd"] <= row["price_usd"] <= doc["build_caps"]["initial_price_max_usd"] for row in skus)
    assert all(row["buyer_problem"] and row["reuse_source"] and row["reuse_boundary"] and row["build_prompt"] for row in skus)

def test_outcomes_start_from_explicit_verified_state():
    doc = load()
    assert doc["verified_revenue_usd"] >= 0
    assert doc["verified_sales_count"] >= 0
    assert doc["published_count"] >= 0
    assert doc["verified_sales_count"] <= doc["published_count"] or doc["published_count"] == 0
