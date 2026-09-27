#!/usr/bin/env python3
"""Static validation for the candidate-specific model value task."""
from __future__ import annotations

import json
from pathlib import Path

from model_router.model_router import route_request
from value_proof.model_task import build_model_request, load_contract, make_evidence_pack, validate_evidence_pack

ROOT=Path(__file__).resolve().parents[1]

class ValueProofValidationError(ValueError):
    pass

def req(ok,msg):
    if not ok:
        raise ValueProofValidationError(msg)

def validate_value_proof():
    contract=load_contract()
    src=contract["source_candidate"]
    pack=make_evidence_pack(
      repository_full_name=src["repository_full_name"],
      repository_id=src["repository_id"],
      revision=src["revision"],
      files=[
        {"path":"quizli/quiz.py","content":"synthetic calibration body for bound source path"},
        {"path":"quizli/session.py","content":"synthetic calibration body for bound source path"},
        {"path":"tests/test_quizli.py","content":"synthetic calibration body for bound test path"},
      ],
    )
    validate_evidence_pack(pack,contract)
    request=build_model_request(contract,pack)
    route=route_request(request)
    req(route["status"]=="ROUTED","value proof builder request not routable")
    req(route["tier"]==2,"value proof builder must route Tier 2")
    req(route["provider_id"]=="openai" and route["model_id"]=="gpt-5.6-terra","value proof builder route drifted")
    req(route["max_estimated_cost_usd"]<=contract["model_contract"]["max_cost_usd"],"value proof builder route exceeds contract cost")
    req(contract["authority_class"]=="OBSERVE","value proof contract widened authority")
    req(contract["data_classification"]=="PUBLIC","value proof contract widened data boundary")
    req(contract["source_candidate"]["hunter_proof_hash"]=="sha256:acc72db61caf877308105e578e0711e34ff19ea5a44e4eb3cf35550a6ae5fb14","Hunter proof binding drifted")
    return {
      "task_id":contract["task_id"],
      "builder_tier":route["tier"],
      "builder_model":route["model_id"],
      "max_estimated_cost_usd":route["max_estimated_cost_usd"],
      "required_evidence_paths":len(contract["evidence_manifest"]["required_paths"]),
      "authority":"OBSERVE",
      "data_classification":"PUBLIC",
    }

if __name__=="__main__":
    print("portfolio-brain model value task: PASS",json.dumps(validate_value_proof(),sort_keys=True))
