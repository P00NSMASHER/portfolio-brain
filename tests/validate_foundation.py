#!/usr/bin/env python3
"""Deterministic Step 1 foundation validator. Standard library only."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKELETON = ROOT / "FOUNDATION_SKELETON.json"
REGISTRATION = ROOT / "registry" / "PROJECT_REGISTRATION_CONTRACT.json"
CONTRACT = ROOT / "docs" / "ARCHITECTURE_CONTRACT.md"

REQUIRED_DIRS = {
    "registry","schemas","events","adapters","truth","memory","graph","hunting",
    "learning","experiments","uncertainty","allocator","agents","model_router",
    "software_factory","verification","repair","governance","runtime","reports",
    "dashboard","tests",".github/workflows"
}
REQUIRED_ADAPTERS = {
    "hunter","recoveryworks","freight","permitplate","capturebrief","starblox",
    "abvm","trading_research"
}
AUTONOMY = ["OBSERVE","EXPERIMENT","MODIFY","ACT"]
EVIDENCE = ["OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"]

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"foundation validation failed: {message}")

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> int:
    s = load(SKELETON)
    r = load(REGISTRATION)
    contract = CONTRACT.read_text(encoding="utf-8")
    require(s["schema_version"] == "1.0.0", "unexpected skeleton schema version")
    require(s["project_id"] == "PRJ-000", "wrong project identity")
    require(s["repository_target"] == "P00NSMASHER/portfolio-brain", "wrong repository target")
    require(s["materialization_status"] == "MATERIALIZED_FOUNDATION", "foundation not materialized")
    require(s["authority_change"] == "NONE", "foundation may not grant authority")
    require(REQUIRED_DIRS <= set(s["directories"]), "required directory missing")
    require(REQUIRED_ADAPTERS <= set(s["adapter_names"]), "required adapter declaration missing")
    require(r["schema_version"] == "1.0.0", "unexpected registration schema version")
    require(r["autonomy_classes"] == AUTONOMY, "autonomy classes changed")
    for key in ("adapters_enabled","autonomous_scheduling_enabled","downstream_writes_enabled","external_actions_enabled"):
        require(r["defaults"][key] is False, f"{key} must default false")
    require(any("does not grant authority" in x for x in r["invariants"]), "registration authority invariant missing")
    require(any("Missing permission is DENY" in x for x in r["invariants"]), "deny-by-default invariant missing")
    require(any("Live trading" in x for x in r["invariants"]), "trading prohibition missing")
    for value in EVIDENCE:
        require(f"`{value}`" in contract, f"evidence state missing: {value}")
    for value in AUTONOMY:
        require(value in contract, f"autonomy class missing from contract: {value}")
    require("No builder may solely certify its own consequential change." in contract, "builder/verifier separation missing")
    require("Interactive ChatGPT is an architect/operator surface, not a runtime dependency." in contract, "runtime independence missing")
    require("Explicit human approval remains required" in contract, "human ACT gate missing")
    require("live trading" in contract.lower(), "live-trading gate missing")
    print("portfolio-brain Step 1 foundation: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
