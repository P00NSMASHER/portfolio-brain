#!/usr/bin/env python3
"""Controlled live proof for read-only repository observation -> exact-once project forwarding."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adapters.github_readonly import GitHubReadOnlyClient, observe_repository
from runtime.project_forwarding import forward_observations, seed_state

ROOT=Path(__file__).resolve().parents[1]
TARGET_REPOSITORY_ID="REPO-003"
TARGET_PROJECT_ID="PRJ-006"

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def load_adapter()->dict[str,Any]:
    registry=json.loads((ROOT/"adapters/ADAPTER_REGISTRY.json").read_text(encoding="utf-8"))
    matches=[row for row in registry["adapters"] if row["repository_id"]==TARGET_REPOSITORY_ID]
    if len(matches)!=1:
        raise SystemExit("live forwarding proof requires exactly one target adapter")
    adapter=matches[0]
    if adapter["project_ids"]!=[TARGET_PROJECT_ID]:
        raise SystemExit("live forwarding proof target routing changed")
    if adapter["authority_class"]!="OBSERVE" or adapter["enabled"] is not True:
        raise SystemExit("live forwarding proof target adapter is not enabled OBSERVE-only")
    return adapter

def live_fetcher():
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    authed=GitHubReadOnlyClient(token=token)
    public=GitHubReadOnlyClient(token=None)
    def fetch(url:str)->dict[str,Any]:
        try:
            return authed.get_json(url)
        except urllib.error.HTTPError as exc:
            if token and exc.code in {401,403,404}:
                return public.get_json(url)
            raise
    return fetch

def run_proof(*,observed_at:str)->dict[str,Any]:
    adapter=load_adapter()
    observation=observe_repository(adapter,None,fetch_json=live_fetcher(),observed_at=observed_at)
    if observation["status"]!="INITIALIZED":
        raise SystemExit("live target did not yield an initialized exact-head observation")
    if observation["network_reads"]!=1:
        raise SystemExit("initial live observation performed unexpected reads")

    state1,first=forward_observations(
        seed_state(),[observation,observation],at=observed_at,cycle_id="LIVE-FORWARD-1",
        cycle_receipt_hash=observation["receipt_hash"]
    )
    if len(first["deliveries"])!=1:
        raise SystemExit("duplicate live observation did not produce exactly one delivery")
    delivery=first["deliveries"][0]
    if delivery["project_id"]!=TARGET_PROJECT_ID or delivery["repository_id"]!=TARGET_REPOSITORY_ID:
        raise SystemExit("live observation routed to the wrong project or repository")
    if delivery["source_revision"]!=observation["current_sha"]:
        raise SystemExit("forwarded delivery lost exact source revision")
    if delivery["evidence_scope"]!=["REPOSITORY_OBSERVATION"]:
        raise SystemExit("repository observation was mislabeled as stronger evidence")
    if any(delivery[k] for k in (
        "authority_granted","mutation_performed","deploy_authority","external_action_authority",
        "child_facing_mutation_authority","school_content_publication_authority")):
        raise SystemExit("live forwarding gained forbidden authority")
    if len(first["duplicate_delivery_keys"])!=1:
        raise SystemExit("same-cycle duplicate was not recorded exactly once")

    state2,second=forward_observations(
        state1,[observation],at=observed_at,cycle_id="LIVE-FORWARD-2",
        cycle_receipt_hash=observation["receipt_hash"]
    )
    if second["deliveries"] or len(second["duplicate_delivery_keys"])!=1:
        raise SystemExit("replayed live observation was not suppressed exactly once")
    if state2["sequence"]!=state1["sequence"] or len(state2["recent_deliveries"])!=1:
        raise SystemExit("replay mutated exact-once forwarding state")

    body={
      "schema_version":"1.0.0","status":"PASS","proof_id":"worker4-step13-live-forwarding",
      "observed_at":observed_at,"repository_id":TARGET_REPOSITORY_ID,"project_id":TARGET_PROJECT_ID,
      "adapter_id":adapter["adapter_id"],"source_repository":adapter["repository_full_name"],
      "source_ref":observation["source_ref"],"source_revision":observation["current_sha"],
      "observation_receipt_hash":observation["receipt_hash"],"network_reads":observation["network_reads"],
      "first_cycle_delivery_count":len(first["deliveries"]),
      "same_cycle_duplicate_count":len(first["duplicate_delivery_keys"]),
      "replay_delivery_count":len(second["deliveries"]),
      "replay_duplicate_count":len(second["duplicate_delivery_keys"]),
      "forwarding_state_sequence":state2["sequence"],
      "delivery_key":delivery["delivery_key"],"delivery_id":delivery["delivery_id"],
      "evidence_scope":delivery["evidence_scope"],"payload_scope":delivery["payload_scope"],
      "authority_granted":False,"mutation_performed":False,"deploy_authority":False,
      "external_action_authority":False,"child_facing_mutation_authority":False,
      "school_content_publication_authority":False,
    }
    return body

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",default="verification/out/project_forwarding_live_proof.json")
    args=ap.parse_args()
    result=run_proof(observed_at=now_iso())
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
