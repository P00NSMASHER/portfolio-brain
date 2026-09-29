#!/usr/bin/env python3
"""Fail-closed champion/challenger promotion-review pipeline.

The pipeline connects Hunter discovery, rights evidence, isolated adapter proof,
historical policy replay, transparent challenger metrics, and a forward shadow
canary. It can only make a candidate eligible for *human promotion review*.
It cannot mutate active policy, grant authority, merge, deploy, or promote.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from hunting.rights_gate import validate_rights_record
from hunting.license_admission import admission as license_admission
from policy_replay.policy_backtester import validate_replay_receipt, verify_replay_inputs
from verification.evidence import canonical, resolve_claim, exact_sha, EvidenceResolver

ROOT = Path(__file__).resolve().parents[1]

class ChallengerError(ValueError):
    pass

def _req(ok: bool, msg: str) -> None:
    if not ok:
        raise ChallengerError(msg)

def _canon(value: Any) -> str:
    return canonical(value)

def _hash(value: Any) -> str:
    return "sha256:"+hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()

def policy() -> dict[str,Any]:
    return json.loads((ROOT/"challenger"/"CHALLENGER_POLICY.json").read_text(encoding="utf-8"))

def _validate_discovery(discovery: dict[str,Any]) -> None:
    required={"finding_id","candidate_fingerprint","repository_full_name","revision","project_ids","provenance_refs"}
    _req(isinstance(discovery,dict) and set(discovery)==required,"challenger discovery fields changed")
    _req(isinstance(discovery["finding_id"],str) and discovery["finding_id"],"finding_id required")
    _req(isinstance(discovery["candidate_fingerprint"],str) and len(discovery["candidate_fingerprint"]) == 71 and discovery["candidate_fingerprint"].startswith("sha256:") and all(c in "0123456789abcdef" for c in discovery["candidate_fingerprint"][7:]),"candidate_fingerprint invalid")
    _req(isinstance(discovery["repository_full_name"],str) and "/" in discovery["repository_full_name"],"repository_full_name invalid")
    rev=discovery["revision"]
    _req(isinstance(rev,str) and len(rev)==40 and all(c in "0123456789abcdef" for c in rev),"exact revision required")
    _req(isinstance(discovery["project_ids"],list) and discovery["project_ids"],"project_ids required")
    _req(all(isinstance(x,str) and x.startswith("PRJ-") for x in discovery["project_ids"]),"invalid project_id")
    _req(isinstance(discovery["provenance_refs"],list) and discovery["provenance_refs"],"discovery provenance required")

def _validate_adapter_receipt(receipt: dict[str,Any], discovery: dict[str,Any]) -> None:
    required={
      "schema_version","adapter_id","finding_id","repository_full_name","source_revision_sha",
      "status","isolated","network_mode","downstream_writes","authority_violations",
      "third_party_code_execution","evidence_refs","adapter_hash","candidate_policy_hash","evaluator_revision_sha"
    }
    _req(isinstance(receipt,dict) and set(receipt)==required,"adapter receipt fields changed")
    _req(receipt["schema_version"]=="2.0.0","adapter receipt schema mismatch")
    _req(receipt["finding_id"]==discovery["finding_id"],"adapter finding lineage mismatch")
    _req(receipt["repository_full_name"]==discovery["repository_full_name"],"adapter repository lineage mismatch")
    _req(receipt["source_revision_sha"]==discovery["revision"],"adapter revision lineage mismatch")
    _req(receipt["status"]=="CLAIM_ONLY","adapter helper cannot independently establish PASS")
    _req(receipt["isolated"] is True,"adapter must be isolated")
    _req(receipt["network_mode"] in {"NONE","READ_ONLY_EXACT_SOURCE"},"adapter network mode widened")
    _req(type(receipt["downstream_writes"]) is int and receipt["downstream_writes"]==0,"adapter gained downstream write authority")
    _req(type(receipt["authority_violations"]) is int and receipt["authority_violations"]==0,"adapter authority violation")
    _req(receipt["third_party_code_execution"] in {"NONE","SANDBOXED_NO_CREDENTIALS_NO_NETWORK"},"adapter third-party execution mode unsafe")
    _req(isinstance(receipt["evidence_refs"],list) and receipt["evidence_refs"],"adapter evidence required")
    body=dict(receipt);given=body.pop("adapter_hash")
    _req(given==_hash(body),"adapter_hash mismatch")

def build_adapter_receipt(
    *,
    adapter_id: str,
    discovery: dict[str,Any],
    evidence_refs: list[str],
    third_party_code_execution: str="NONE",
    network_mode: str="NONE",
    candidate_policy_hash: str | None=None,
    evaluator_revision_sha: str | None=None,
) -> dict[str,Any]:
    _validate_discovery(discovery)
    body={
      "schema_version":"2.0.0",
      "adapter_id":adapter_id,
      "candidate_policy_hash":candidate_policy_hash,
      "evaluator_revision_sha":evaluator_revision_sha,
      "finding_id":discovery["finding_id"],
      "repository_full_name":discovery["repository_full_name"],
      "source_revision_sha":discovery["revision"],
      "status":"CLAIM_ONLY",
      "isolated":True,
      "network_mode":network_mode,
      "downstream_writes":0,
      "authority_violations":0,
      "third_party_code_execution":third_party_code_execution,
      "evidence_refs":list(evidence_refs),
    }
    _req(body["evidence_refs"],"adapter evidence required")
    receipt={**body,"adapter_hash":_hash(body)}
    _validate_adapter_receipt(receipt,discovery)
    return receipt

def _compare_metric(name: str, champion: Any, challenger: Any, direction: str) -> dict[str,Any]:
    comparable=True
    passed=False
    strict=False
    if direction=="ZERO_AND_NOT_WORSE":
        comparable=type(champion) in (int,float) and type(challenger) in (int,float)
        passed=comparable and challenger==0 and challenger<=champion
        strict=passed and challenger<champion
    elif champion is None and challenger is None:
        comparable=False
        passed=False
        strict=False
    elif not type(champion) in (int,float) or not type(challenger) in (int,float):
        comparable=False
        passed=False
    elif direction=="HIGHER_OR_EQUAL":
        passed=challenger>=champion
        strict=challenger>champion
    elif direction=="LOWER_OR_EQUAL":
        passed=challenger<=champion
        strict=challenger<champion
    else:
        raise ChallengerError(f"unsupported metric direction: {direction}")
    return {
      "metric":name,
      "direction":direction,
      "champion":champion,
      "challenger":challenger,
      "comparable":comparable,
      "passed":passed,
      "strict_improvement":strict,
    }

def derive_replay_metrics(replay_receipt: dict[str,Any]) -> dict[str,Any]:
    validate_replay_receipt(replay_receipt)
    p=policy()
    _req(replay_receipt["mode"]==p["replay_required_mode"],"replay mode is not shadow-only")
    _req(replay_receipt["promotion_allowed"] is False,"historical replay improperly granted promotion")
    _req(replay_receipt["forward_canary_required"] is p["replay_requires_forward_canary"],"forward canary requirement drifted")
    checks=[]
    for metric,direction in p["metric_directions"].items():
        entry=replay_receipt["comparison"].get(metric)
        _req(isinstance(entry,dict) and set(entry)=={"baseline","candidate"},f"replay comparison missing {metric}")
        checks.append(_compare_metric(metric,entry["baseline"],entry["candidate"],direction))
    strict=sum(1 for c in checks if c["strict_improvement"])
    all_pass=all(c["passed"] for c in checks)
    body={
      "schema_version":"2.0.0",
      "mode":"TRANSPARENT_REPLAY_METRICS",
      "replay_hash":replay_receipt["replay_hash"],
      "checks":checks,
      "strict_improvement_count":strict,
      "minimum_strict_improvements":p["minimum_strict_improvements"],
      "all_required_metrics_pass":all_pass,
      "beats_champion":all_pass and strict>=p["minimum_strict_improvements"],
      "opaque_score_used":False,
    }
    return {**body,"metrics_hash":_hash(body)}

def build_forward_canary_receipt(
    *,
    candidate_id: str,
    evidence_refs: list[str],
    observed_cycles: int,
    authority_violations: int=0,
    forbidden_actions_attempted: int=0,
    status: str="PASS",
    candidate_policy_hash: str | None=None,
    source_revision_sha: str | None=None,
    evaluator_revision_sha: str | None=None,
) -> dict[str,Any]:
    _req(type(observed_cycles) is int and observed_cycles>=1,"forward canary requires observed cycles")
    body={
      "schema_version":"2.0.0",
      "candidate_id":candidate_id,
      "candidate_policy_hash":candidate_policy_hash,
      "source_revision_sha":source_revision_sha,
      "evaluator_revision_sha":evaluator_revision_sha,
      "status":"CLAIM_ONLY",
      "claimed_status":status,
      "shadow_only":True,
      "observed_cycles":observed_cycles,
      "authority_violations":authority_violations,
      "forbidden_actions_attempted":forbidden_actions_attempted,
      "promotion_allowed":False,
      "active_policy_changed":False,
      "evidence_refs":list(evidence_refs),
    }
    _req(body["evidence_refs"],"forward canary evidence required")
    return {**body,"canary_hash":_hash(body)}

def _validate_forward_canary(receipt: dict[str,Any],candidate_id: str) -> None:
    required={
      "schema_version","candidate_id","status","shadow_only","observed_cycles",
      "authority_violations","forbidden_actions_attempted","promotion_allowed",
      "active_policy_changed","evidence_refs","canary_hash",
      "candidate_policy_hash","source_revision_sha","evaluator_revision_sha","claimed_status"
    }
    _req(isinstance(receipt,dict) and set(receipt)==required,"forward canary fields changed")
    _req(receipt["schema_version"] == "2.0.0", "forward canary schema mismatch")
    p=policy()["canary"]
    _req(receipt["candidate_id"]==candidate_id,"forward canary candidate mismatch")
    _req(receipt["status"]=="CLAIM_ONLY" and receipt["claimed_status"]==p["required_status"],"forward canary claim did not pass")
    _req(receipt["shadow_only"] is p["shadow_only"],"forward canary not shadow-only")
    _req(type(receipt["authority_violations"]) is int and 0 <= receipt["authority_violations"]<=p["authority_violations_max"],"forward canary authority violation")
    _req(type(receipt["forbidden_actions_attempted"]) is int and 0 <= receipt["forbidden_actions_attempted"]<=p["forbidden_actions_attempted_max"],"forward canary attempted forbidden action")
    _req(receipt["promotion_allowed"] is p["promotion_allowed"],"forward canary granted promotion")
    _req(receipt["active_policy_changed"] is False,"forward canary changed active policy")
    _req(type(receipt["observed_cycles"]) is int and receipt["observed_cycles"]>=1,"forward canary cycle count invalid")
    _req(isinstance(receipt["evidence_refs"],list) and receipt["evidence_refs"],"forward canary evidence missing")
    body=dict(receipt);given=body.pop("canary_hash")
    _req(given==_hash(body),"forward canary hash mismatch")

def assess_candidate(
    *,
    discovery: dict[str,Any],
    rights_record: dict[str,Any],
    adapter_receipt: dict[str,Any],
    replay_receipt: dict[str,Any],
    forward_canary_receipt: dict[str,Any],
    resolver: EvidenceResolver | None = None,
) -> dict[str,Any]:
    p=policy()
    _validate_discovery(discovery)
    validate_rights_record(rights_record)
    _req(rights_record["repository_full_name"]==discovery["repository_full_name"],"rights repository lineage mismatch")
    _req(rights_record["source_revision_sha"]==discovery["revision"],"rights exact-revision lineage mismatch")
    _req(rights_record["automatic_reuse_authority_granted"] is False,"rights discovery granted reuse authority")

    candidate_id="CHL-"+hashlib.sha256((
        discovery["candidate_fingerprint"]+"\0"+discovery["revision"]
    ).encode()).hexdigest()[:20].upper()

    validate_replay_receipt(replay_receipt)
    _req(replay_receipt["candidate_id"] == candidate_id, "replay/discovery candidate mismatch")
    subject = {
      "candidate_id": candidate_id,
      "candidate_policy_hash": replay_receipt["candidate_policy_hash"],
      "source_revision_sha": discovery["revision"],
      "evaluator_revision_sha": replay_receipt["provenance"]["evaluator_revision_sha"],
    }
    _req(exact_sha(subject["evaluator_revision_sha"]), "exact evaluator revision required")
    _validate_adapter_receipt(adapter_receipt, discovery)
    _validate_forward_canary(forward_canary_receipt, candidate_id)
    _req(adapter_receipt["candidate_policy_hash"] == subject["candidate_policy_hash"] and adapter_receipt["evaluator_revision_sha"] == subject["evaluator_revision_sha"], "adapter policy/evaluator binding mismatch")
    for field in subject:
        _req(forward_canary_receipt[field] == subject[field], "canary candidate/policy/revision binding mismatch")
    scopes = []
    stages=[
      {"stage":"DISCOVER","status":"PASS","evidence_refs":discovery["provenance_refs"]},
    ]

    license_decision=license_admission(rights_record,p["integration_rights_classes"])
    rights_ok=license_decision["allowed"]
    stages.append({
      "stage":"RIGHTS_POLICY_ADMISSION",
      "license_admission":license_decision,
      "status":"PASS" if rights_ok else "BLOCKED",
      "rights_classification":rights_record["rights_classification"],
      "allowed_integration_mode":rights_record["allowed_integration_mode"],
      "evidence_refs":rights_record["provenance_refs"],
    })

    adapter_ok=False
    if rights_ok and resolver is not None:
        refs = adapter_receipt["evidence_refs"]
        _req(len(refs) == 1 and isinstance(refs[0], str), "one exact adapter execution reference required")
        result = resolve_claim(resolver, refs[0], kind="ADAPTER_RESULT", subject=subject)
        expected = {k: adapter_receipt[k] for k in ("adapter_id", "isolated", "network_mode", "downstream_writes", "authority_violations", "third_party_code_execution")}
        expected.update({"executed": True, "result": "PASS", "behavior_checks": {"action_result": True, "isolation": True}})
        _req(_canon(result.record["measurements"]) == _canon(expected), "adapter execution measurements mismatch")
        scopes.append(result.scope)
        adapter_ok=True
    stages.append({
      "stage":"ISOLATED_ADAPTER_VERIFIED",
      "status":"PASS" if adapter_ok else "BLOCKED",
      "evidence_refs":adapter_receipt.get("evidence_refs",[]) if isinstance(adapter_receipt,dict) else [],
    })

    replay_ok=False
    metrics=None
    if adapter_ok:
        scopes.append(verify_replay_inputs(replay_receipt, resolver, subject))
        replay_ok=True
        metrics=derive_replay_metrics(replay_receipt)
    stages.append({
      "stage":"HISTORICAL_REPLAY_VERIFIED",
      "status":"PASS" if replay_ok else "BLOCKED",
      "evidence_refs":[replay_receipt.get("replay_hash")] if isinstance(replay_receipt,dict) and replay_receipt.get("replay_hash") else [],
    })

    metrics_ok=bool(metrics and metrics["beats_champion"])
    stages.append({
      "stage":"CHALLENGER_METRICS_VERIFIED",
      "status":"PASS" if metrics_ok else "BLOCKED",
      "metrics_hash":None if metrics is None else metrics["metrics_hash"],
      "strict_improvement_count":None if metrics is None else metrics["strict_improvement_count"],
      "opaque_score_used":False,
      "evidence_refs":[] if metrics is None else [metrics["metrics_hash"]],
    })

    canary_ok=False
    if metrics_ok:
        refs = forward_canary_receipt["evidence_refs"]
        _req(all(isinstance(r, str) and r for r in refs) and len(set(refs)) == len(refs), "canary references must be unique")
        _req(len(refs) == forward_canary_receipt["observed_cycles"] and len(refs) >= p["canary"]["minimum_unique_cycles"], "canary count lacks source measurements")
        cycle_ids = set()
        identities = set()
        for reference in refs:
            result = resolve_claim(resolver, reference, kind="FORWARD_CYCLE", subject=subject)
            m = result.record["measurements"]
            _req(set(m) == {"cycle_id", "executed", "result", "authority_violations", "forbidden_actions_attempted", "active_policy_changed", "checks"}, "forward measurements missing")
            _req(isinstance(m["cycle_id"], str) and m["cycle_id"] and m["cycle_id"] not in cycle_ids, "duplicate canary cycle")
            _req(result.receipt_identity not in identities, "reused canary execution receipt")
            _req(m["executed"] is True and m["result"] == "PASS", "canary action did not pass")
            _req(type(m["authority_violations"]) is int and m["authority_violations"] == 0 and type(m["forbidden_actions_attempted"]) is int and m["forbidden_actions_attempted"] == 0, "canary authority violation")
            _req(m["active_policy_changed"] is False and _canon(m["checks"]) == _canon({"behavior_result": True, "replay_binding": True, "policy_unchanged": True}), "canary behavior/safety checks missing")
            cycle_ids.add(m["cycle_id"])
            identities.add(result.receipt_identity)
            scopes.append(result.scope)
        canary_ok=True
    stages.append({
      "stage":"FORWARD_CANARY_VERIFIED",
      "status":"PASS" if canary_ok else "BLOCKED",
      "evidence_refs":forward_canary_receipt.get("evidence_refs",[]) if isinstance(forward_canary_receipt,dict) else [],
    })

    technical_pass=rights_ok and adapter_ok and replay_ok and metrics_ok and canary_ok
    production_evidence=bool(scopes) and all(scope == "PROVIDER_VERIFIED" for scope in scopes)
    eligible=technical_pass and production_evidence
    decision="ELIGIBLE_FOR_HUMAN_PROMOTION_REVIEW" if eligible else "REMAIN_SHADOW_BLOCKED"
    body={
      "schema_version":"2.0.0",
      "pipeline_id":p["pipeline_id"],
      "technical_checks_pass":technical_pass,
      "evidence_scope":"PROVIDER_VERIFIED" if production_evidence else ("SYNTHETIC_FIXTURE" if scopes else "UNRESOLVED"),
      "forward_performance_improvement_established":False,
      "source_inputs":deepcopy({"discovery":discovery, "rights_record":rights_record, "adapter_receipt":adapter_receipt, "replay_receipt":replay_receipt, "forward_canary_receipt":forward_canary_receipt}),
      "candidate_id":candidate_id,
      "finding_id":discovery["finding_id"],
      "repository_full_name":discovery["repository_full_name"],
      "source_revision_sha":discovery["revision"],
      "project_ids":discovery["project_ids"],
      "mode":p["mode"],
      "stages":stages,
      "replay_metrics":metrics,
      "decision":decision,
      "eligible_for_human_promotion_review":eligible,
      "automatic_promotion_allowed":False,
      "active_policy_changed":False,
      "authority_granted":False,
      "human_promotion_review_required":True,
      "next_action":"HUMAN_PROMOTION_REVIEW" if eligible else "REMAIN_SHADOW_AND_RESOLVE_BLOCKED_STAGE",
      "provenance_refs":list(dict.fromkeys([
        *discovery["provenance_refs"],
        *rights_record["provenance_refs"],
        *(adapter_receipt.get("evidence_refs",[]) if isinstance(adapter_receipt,dict) else []),
        *([replay_receipt["replay_hash"]] if isinstance(replay_receipt,dict) and replay_receipt.get("replay_hash") else []),
        *(forward_canary_receipt.get("evidence_refs",[]) if isinstance(forward_canary_receipt,dict) else []),
      ])),
    }
    return {**body,"assessment_hash":_hash(body)}

def validate_assessment(assessment: dict[str,Any], *, resolver: EvidenceResolver | None = None) -> None:
    _req(isinstance(assessment, dict) and isinstance(assessment.get("source_inputs"), dict), "assessment inputs required")
    _req(set(assessment["source_inputs"]) == {"discovery", "rights_record", "adapter_receipt", "replay_receipt", "forward_canary_receipt"}, "assessment input schema mismatch")
    expected = assess_candidate(**assessment["source_inputs"], resolver=resolver)
    _req(_canon(assessment) == _canon(expected), "assessment source/summary/hash contradiction")
