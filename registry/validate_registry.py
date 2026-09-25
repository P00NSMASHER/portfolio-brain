#!/usr/bin/env python3
"""Cross-file Step 2 registry validator. Standard library only."""
from __future__ import annotations
import json
from pathlib import Path
from registry.validate_project import validate_project_record
from registry.validate_contracts import validate_autonomy_profile, validate_objective, validate_metric

ROOT=Path(__file__).resolve().parents[1]

class RegistryValidationError(ValueError):
    pass

def require(ok: bool, message: str) -> None:
    if not ok:
        raise RegistryValidationError(message)

def load(path: str):
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def unique_map(items, key, label):
    out={}
    for item in items:
        value=item[key]
        require(value not in out, f"duplicate {label}: {value}")
        out[value]=item
    return out

def validate_registry_bundle() -> dict[str,int]:
    project_doc=load("registry/projects.json")
    autonomy_doc=load("registry/autonomy_profiles.json")
    objective_doc=load("registry/objectives.json")
    metric_doc=load("registry/metrics.json")
    coverage_doc=load("registry/PORTFOLIO_COVERAGE.json")

    for name,doc in [
        ("projects",project_doc),("autonomy_profiles",autonomy_doc),
        ("objectives",objective_doc),("metrics",metric_doc),("coverage",coverage_doc)
    ]:
        require(doc.get("schema_version")=="1.0.0", f"{name} wrapper schema_version must be 1.0.0")

    projects=unique_map(project_doc["projects"],"project_id","project_id")
    profiles=unique_map(autonomy_doc["profiles"],"autonomy_profile_id","autonomy_profile_id")
    objectives=unique_map(objective_doc["objectives"],"objective_id","objective_id")
    metrics=unique_map(metric_doc["metrics"],"metric_id","metric_id")

    for p in projects.values():
        validate_project_record(p)
        require(p["registration_state"]=="REGISTERED", f"{p['project_id']} must be REGISTERED in Step 2")
        require(p["autonomy_profile_id"] in profiles, f"{p['project_id']} missing autonomy profile")
        require(profiles[p["autonomy_profile_id"]]["project_id"]==p["project_id"], f"{p['project_id']} autonomy profile points to another project")
        for oid in p["objective_ids"]:
            require(oid in objectives, f"{p['project_id']} missing objective {oid}")
            require(objectives[oid]["project_id"]==p["project_id"], f"{oid} belongs to wrong project")
        for mid in p["metric_ids"]:
            require(mid in metrics, f"{p['project_id']} missing metric {mid}")
            require(metrics[mid]["project_id"]==p["project_id"], f"{mid} belongs to wrong project")

    for profile in profiles.values():
        validate_autonomy_profile(profile)
        require(profile["project_id"] in projects, f"{profile['autonomy_profile_id']} references missing project")

    for obj in objectives.values():
        validate_objective(obj)
        require(obj["project_id"] in projects, f"{obj['objective_id']} references missing project")

    for metric in metrics.values():
        validate_metric(metric)
        require(metric["project_id"] in projects, f"{metric['metric_id']} references missing project")

    # Parent graph: every parent resolves and no cycle is permitted.
    for pid,p in projects.items():
        parent=p["parent_project_id"]
        require(parent is None or parent in projects, f"{pid} parent is missing")
        seen={pid}
        while parent is not None:
            require(parent not in seen, f"project parent cycle at {pid}")
            seen.add(parent)
            parent=projects[parent]["parent_project_id"]

    # Repository IDs must map to one canonical full_name everywhere.
    repo_names={}
    for p in projects.values():
        for binding in p["repository_bindings"]:
            rid=binding["repository_id"]
            full=binding["full_name"]
            if rid in repo_names:
                require(repo_names[rid]==full, f"{rid} maps to conflicting repository names")
            repo_names[rid]=full

    # Step 2 registers contracts only; no downstream adapter activation yet.
    for p in projects.values():
        for binding in p["repository_bindings"]:
            require(binding["integration_status"] in {"DECLARED","BLOCKED"}, f"{p['project_id']} prematurely enabled repository integration")

    # Market-surveillance authority must remain fail-closed.
    market=projects["PRJ-007"]
    market_profile=profiles[market["autonomy_profile_id"]]
    for boundary in {"NO_AUTONOMOUS_TRADING","NO_BROKER_ORDER_EXECUTION"}:
        require(boundary in market["hard_boundaries"], f"PRJ-007 missing {boundary}")
        require(boundary in market_profile["hard_prohibitions"], f"PRJ-007 autonomy missing {boundary}")
    require(market_profile["permissions"]["ACT"]["decision"]=="PROHIBITED", "PRJ-007 ACT must be PROHIBITED")

    # The known sensitive state repository remains blocked at registration.
    permit=projects["PRJ-003"]
    state_binding=next((b for b in permit["repository_bindings"] if b["repository_id"]=="REPO-006"),None)
    require(state_binding is not None, "PRJ-003 missing REPO-006 declaration")
    require(state_binding["integration_status"]=="BLOCKED" and state_binding.get("blocker_id")=="BLK-001", "REPO-006 must remain blocked by BLK-001")

    # Coverage maps owner-named portfolio items to canonical stable projects;
    # it does not invent execution authority or validation status.
    items=coverage_doc.get("items")
    require(isinstance(items,list) and items, "coverage items missing")
    names=set()
    for item in items:
        require(set(item)=={"name","canonical_project_id","item_kind","coverage_status"}, "invalid coverage item fields")
        require(isinstance(item["name"],str) and item["name"], "coverage name missing")
        require(item["name"] not in names, f"duplicate coverage name: {item['name']}")
        names.add(item["name"])
        require(item["canonical_project_id"] in projects, f"coverage item maps to missing project: {item['name']}")
        require(item["coverage_status"]=="REGISTERED_COVERAGE_ONLY", "coverage must not claim independent validation")

    return {
        "projects":len(projects),
        "autonomy_profiles":len(profiles),
        "objectives":len(objectives),
        "metrics":len(metrics),
        "coverage_items":len(items),
        "repository_ids":len(repo_names),
    }

if __name__=="__main__":
    counts=validate_registry_bundle()
    print("portfolio-brain Step 2 registry: PASS", json.dumps(counts,sort_keys=True))
