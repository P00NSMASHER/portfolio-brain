#!/usr/bin/env python3
"""Cross-file validator for Step 4 read-only repository adapters."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SHA=re.compile(r"^[0-9a-f]{40}$")

class AdapterRegistryError(ValueError):
    pass

def require(ok: bool, message: str) -> None:
    if not ok:
        raise AdapterRegistryError(message)

def load(path: str):
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def validate_adapter_bundle() -> dict[str,int]:
    schema=load("schemas/ADAPTER_SCHEMA.json")
    registry=load("adapters/ADAPTER_REGISTRY.json")
    cursors=load("adapters/cursors/repositories.json")
    observation=load("adapters/observations/INITIAL_STEP4_OBSERVATION.json")
    projects=load("registry/projects.json")["projects"]

    require(schema.get("additionalProperties") is False, "ADAPTER_SCHEMA must be closed")
    require(registry.get("schema_version")=="1.0.0", "adapter registry schema_version mismatch")
    require(cursors.get("schema_version")=="1.0.0", "cursor schema_version mismatch")
    require(observation.get("schema_version")=="1.0.0", "observation schema_version mismatch")
    require(observation.get("authority_class")=="OBSERVE", "initial observation must be OBSERVE-only")
    require(observation.get("unchanged_content_rereads")==0, "unchanged repositories must not be reread")
    require(observation.get("blocked_repository_reads")==0, "blocked repositories must not be read")

    project_ids={p["project_id"] for p in projects}
    repo_bindings={}
    for p in projects:
        for binding in p["repository_bindings"]:
            rid=binding["repository_id"]
            repo_bindings.setdefault(rid,binding["full_name"])
            require(repo_bindings[rid]==binding["full_name"], f"conflicting project repository binding for {rid}")

    adapters=registry.get("adapters")
    require(isinstance(adapters,list) and len(adapters)==8, "Step 4 requires exactly eight durable repository adapters")
    adapter_ids=set()
    repo_ids=set()
    for adapter in adapters:
        require(set(adapter)=={
            "schema_version","adapter_id","adapter_name","adapter_type","repository_id",
            "repository_full_name","project_ids","authority_class","enabled",
            "source_ref_policy","data_classification","cursor_policy","blocked_by"
        }, f"unexpected adapter fields: {adapter.get('adapter_id')}")
        require(adapter["adapter_id"] not in adapter_ids, "duplicate adapter_id")
        require(adapter["repository_id"] not in repo_ids, "duplicate repository adapter")
        adapter_ids.add(adapter["adapter_id"])
        repo_ids.add(adapter["repository_id"])
        require(adapter["schema_version"]=="1.0.0", "adapter schema_version mismatch")
        require(adapter["adapter_type"]=="GITHUB_REPOSITORY", "adapter type must be GitHub repository")
        require(adapter["authority_class"]=="OBSERVE", "adapter authority must be OBSERVE")
        require(all(pid in project_ids for pid in adapter["project_ids"]), "adapter references missing project")
        require(adapter["repository_id"] in repo_bindings, "adapter repository missing from project registry")
        require(repo_bindings[adapter["repository_id"]]==adapter["repository_full_name"], "adapter full_name disagrees with project registry")
        require(adapter["source_ref_policy"]["ref"]=="main", "Step 4 adapters require explicit main ref")
        require(adapter["cursor_policy"]=={
            "persist_exact_sha":True,
            "skip_unchanged":True,
            "compare_changed_only":True,
        }, "cursor policy must remain exact/delta-only")
        if adapter["enabled"]:
            require(adapter["blocked_by"] is None, "enabled adapter cannot carry blocker")
        else:
            require(isinstance(adapter["blocked_by"],str) and adapter["blocked_by"], "disabled adapter must be blocked")

    require(repo_ids=={f"REPO-{i:03d}" for i in range(1,9)}, "durable adapter repository set changed")

    cursor_map=cursors.get("repositories")
    require(set(cursor_map)==repo_ids, "cursor repository set must match adapter set")
    for rid,cursor in cursor_map.items():
        require(cursor["source_ref"]=="main", f"{rid} cursor ref must be main")
        require(SHA.fullmatch(cursor["cursor_sha"]) is not None, f"{rid} cursor must be exact SHA")
        require(cursor["status"] in {"CURRENT","BLOCKED_HISTORICAL_ONLY"}, f"{rid} invalid cursor status")
    require(cursor_map["REPO-006"]["status"]=="BLOCKED_HISTORICAL_ONLY", "REPO-006 must retain historical-only cursor")

    observations=observation.get("observations")
    require(isinstance(observations,list) and len(observations)==8, "initial observation must cover eight repositories")
    obs_by_repo={o["repository_id"]:o for o in observations}
    require(set(obs_by_repo)==repo_ids, "observation repository set mismatch")
    require(len(obs_by_repo)==len(observations), "duplicate repository observation")

    changed=unchanged=blocked=initialized=0
    for rid,obs in obs_by_repo.items():
        require(obs["repository_full_name"]==repo_bindings[rid], f"{rid} observation full_name mismatch")
        status=obs["status"]
        if status=="CHANGED":
            changed+=1
            require(obs["compare"] is not None, f"{rid} changed observation requires compare")
            require(obs["compare"]["changed_file_count"]==len(obs["compare"]["changed_files"]), f"{rid} changed-file count mismatch")
            require(cursor_map[rid]["cursor_sha"]==obs["current_sha"], f"{rid} cursor did not advance to observed head")
        elif status=="UNCHANGED":
            unchanged+=1
            require(obs["compare"] is None, f"{rid} unchanged observation must skip compare")
            require(obs["prior_sha"]==obs["current_sha"], f"{rid} unchanged SHA mismatch")
            require(cursor_map[rid]["cursor_sha"]==obs["current_sha"], f"{rid} unchanged cursor mismatch")
        elif status=="BLOCKED":
            blocked+=1
            require(rid=="REPO-006", "only REPO-006 is blocked in durable Step 4 set")
            require(obs.get("blocked_by")=="BLK-001", "REPO-006 must remain blocked by BLK-001")
            require(obs.get("network_reads")==0, "blocked repository must have zero reads")
            require(obs["current_sha"] is None, "blocked repository cannot claim refreshed head")
        elif status=="INITIALIZED":
            initialized+=1
            require(obs["prior_sha"] is None and obs["compare"] is None, "initialization must not invent prior delta")
            require(cursor_map[rid]["cursor_sha"]==obs["current_sha"], f"{rid} initialized cursor mismatch")
        else:
            raise AdapterRegistryError(f"invalid observation status: {status}")

    require((changed,unchanged,blocked,initialized)==(3,3,1,1), "unexpected initial observation classification")
    return {
        "adapters":len(adapters),
        "changed":changed,
        "unchanged":unchanged,
        "blocked":blocked,
        "initialized":initialized,
        "changed_files":sum(o["compare"]["changed_file_count"] for o in observations if o["status"]=="CHANGED"),
    }

if __name__=="__main__":
    print("portfolio-brain Step 4 adapters: PASS",json.dumps(validate_adapter_bundle(),sort_keys=True))
