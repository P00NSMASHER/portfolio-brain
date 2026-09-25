#!/usr/bin/env python3
"""Pinned adapter from AI Business OS Truth Engine receipts to Portfolio truth state.

The upstream engine remains canonical. This module does not copy or reimplement
its proof evaluator. It validates the pinned receipt contract and projects it into
Portfolio Brain's seven-state evidence vocabulary.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
PIN_PATH=ROOT/"truth"/"AI_BUSINESS_OS_TRUTH_ENGINE_PIN.json"

SHA40=re.compile(r"^[0-9a-f]{40}$")
SHA64=re.compile(r"^[0-9a-f]{64}$")
VERDICTS={"PROVEN","CONTESTED","NOT_PROVEN","UNKNOWN"}
FINDING_STATUSES={
    "SATISFIED","MISSING","STALE","INADMISSIBLE",
    "INSUFFICIENT_SUPPORT","INSUFFICIENT_INDEPENDENCE",
    "CONFLICTED","CONTRADICTED",
}
PORTFOLIO_STATES={"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"}

class TruthIntegrationError(ValueError):
    pass

def _require(ok: bool, message: str) -> None:
    if not ok:
        raise TruthIntegrationError(message)

def _canonical_hash(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def load_pin() -> dict[str,Any]:
    data=json.loads(PIN_PATH.read_text(encoding="utf-8"))
    validate_pin(data)
    return data

def validate_pin(pin: dict[str,Any]) -> None:
    required={
        "schema_version","integration_id","source_repository","source_revision",
        "source_path","source_blob_sha","source_test_path","source_test_blob_sha",
        "integration_mode","copied_source_code","upstream_contract",
        "observed_semantics","drift_policy"
    }
    _require(set(pin)==required,"truth-engine pin fields changed")
    _require(pin["schema_version"]=="1.0.0","pin schema_version mismatch")
    _require(pin["source_repository"]=="P00NSMASHER/github-value-hunt-ledger","unexpected truth source repository")
    _require(SHA40.fullmatch(pin["source_revision"]) is not None,"invalid source revision")
    _require(SHA40.fullmatch(pin["source_blob_sha"]) is not None,"invalid source blob SHA")
    _require(SHA40.fullmatch(pin["source_test_blob_sha"]) is not None,"invalid source test blob SHA")
    _require(pin["integration_mode"]=="PINNED_INTERFACE_ADAPTER","integration must remain pinned-interface")
    _require(pin["copied_source_code"] is False,"canonical Truth Engine source must not be copied")
    contract=pin["upstream_contract"]
    _require(set(contract["verdicts"])==VERDICTS,"upstream verdict contract changed")
    _require(set(contract["finding_statuses"])==FINDING_STATUSES,"upstream finding-status contract changed")
    _require(set(contract["evidence_stances"])=={"SUPPORTS","CONTRADICTS"},"upstream stance contract changed")
    _require(pin["drift_policy"]=={
        "exact_repository_revision_required":True,
        "exact_blob_sha_required":True,
        "on_source_revision_change":"RECONFORM_BEFORE_USE",
        "on_blob_mismatch":"FAIL_CLOSED",
    },"truth-source drift policy weakened")

def verify_source_identity(pin: dict[str,Any], *, source_revision: str, source_blob_sha: str) -> None:
    validate_pin(pin)
    _require(source_revision==pin["source_revision"],"truth source revision drifted; reconformance required")
    _require(source_blob_sha==pin["source_blob_sha"],"truth source blob mismatch")

def _validate_finding(finding: dict[str,Any]) -> None:
    required={
        "key","required","status","reason",
        "supporting_evidence_ids","contradicting_evidence_ids",
        "stale_evidence_ids","inadmissible_evidence_ids",
    }
    _require(required <= set(finding),"upstream finding missing required field")
    _require(isinstance(finding["key"],str) and finding["key"],"finding key required")
    _require(isinstance(finding["required"],bool),"finding.required must be boolean")
    _require(finding["status"] in FINDING_STATUSES,"unknown upstream finding status")
    _require(isinstance(finding["reason"],str) and finding["reason"],"finding reason required")
    for key in [
        "supporting_evidence_ids","contradicting_evidence_ids",
        "stale_evidence_ids","inadmissible_evidence_ids",
    ]:
        values=finding[key]
        _require(isinstance(values,list),"finding evidence IDs must be lists")
        _require(all(isinstance(x,str) and x for x in values),"finding evidence IDs must be non-empty strings")
        _require(len(values)==len(set(values)),"finding evidence IDs must be unique")

def validate_upstream_receipt(receipt: dict[str,Any]) -> None:
    _require(isinstance(receipt,dict),"truth receipt must be an object")
    for field in ["claim_id","claim_hash","verdict","evaluated_at","findings","evidence_set_hash","receipt_hash"]:
        _require(field in receipt,f"truth receipt missing {field}")
    _require(isinstance(receipt["claim_id"],str) and receipt["claim_id"],"claim_id required")
    _require(SHA64.fullmatch(receipt["claim_hash"]) is not None,"claim_hash must be 64 hex")
    _require(receipt["verdict"] in VERDICTS,"unknown upstream verdict")
    _require(isinstance(receipt["evaluated_at"],(int,float)),"evaluated_at must be numeric")
    _require(SHA64.fullmatch(receipt["evidence_set_hash"]) is not None,"evidence_set_hash must be 64 hex")
    _require(SHA64.fullmatch(receipt["receipt_hash"]) is not None,"receipt_hash must be 64 hex")
    findings=receipt["findings"]
    _require(isinstance(findings,list) and findings,"truth receipt requires findings")
    for finding in findings:
        _validate_finding(finding)

    required=[f for f in findings if f["required"]]
    verdict=receipt["verdict"]
    if verdict=="PROVEN":
        _require(required and all(f["status"]=="SATISFIED" for f in required),"PROVEN receipt requires every required finding SATISFIED")
    elif verdict=="CONTESTED":
        _require(any(f["required"] and f["status"] in {"CONFLICTED","CONTRADICTED"} for f in findings),"CONTESTED receipt requires required contradiction/conflict")
    elif verdict=="UNKNOWN":
        _require(all(f["required"] and f["status"]=="MISSING" for f in required) if required else False,"UNKNOWN receipt must represent missing required evidence")

def project_truth_state(receipt: dict[str,Any]) -> str:
    validate_upstream_receipt(receipt)
    required=[f for f in receipt["findings"] if f["required"]]
    statuses={f["status"] for f in required}

    if statuses & {"CONFLICTED","CONTRADICTED"}:
        return "CONTRADICTED"
    if "STALE" in statuses:
        return "STALE"
    if receipt["verdict"]=="PROVEN":
        return "VERIFIED"
    if receipt["verdict"] in {"NOT_PROVEN","UNKNOWN"}:
        return "UNKNOWN"
    if receipt["verdict"]=="CONTESTED":
        return "CONTRADICTED"
    raise TruthIntegrationError("unreachable verdict projection")

def project_receipt(
    receipt: dict[str,Any],
    *,
    project_id: str,
    source_revision: str,
    source_blob_sha: str,
    source_receipt_ref: str,
) -> dict[str,Any]:
    pin=load_pin()
    verify_source_identity(pin,source_revision=source_revision,source_blob_sha=source_blob_sha)
    state=project_truth_state(receipt)
    required=[f for f in receipt["findings"] if f["required"]]
    projection={
        "schema_version":"1.0.0",
        "project_id":project_id,
        "claim_id":receipt["claim_id"],
        "truth_state":state,
        "upstream_verdict":receipt["verdict"],
        "upstream_claim_hash":receipt["claim_hash"],
        "upstream_evidence_set_hash":receipt["evidence_set_hash"],
        "upstream_receipt_hash":receipt["receipt_hash"],
        "upstream_source":{
            "repository":pin["source_repository"],
            "revision":pin["source_revision"],
            "path":pin["source_path"],
            "blob_sha":pin["source_blob_sha"],
            "receipt_ref":source_receipt_ref,
        },
        "evaluated_at":receipt["evaluated_at"],
        "required_findings":[{
            "key":f["key"],
            "status":f["status"],
            "reason":f["reason"],
            "supporting_evidence_ids":f["supporting_evidence_ids"],
            "contradicting_evidence_ids":f["contradicting_evidence_ids"],
            "stale_evidence_ids":f["stale_evidence_ids"],
            "inadmissible_evidence_ids":f["inadmissible_evidence_ids"],
        } for f in required],
    }
    return projection | {"projection_hash":_canonical_hash(projection)}
