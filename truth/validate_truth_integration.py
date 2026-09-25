#!/usr/bin/env python3
"""Cross-file validator for Step 5 Truth Engine integration."""
from __future__ import annotations

import json
from pathlib import Path

from truth.truth_adapter import load_pin, validate_pin

ROOT=Path(__file__).resolve().parents[1]

class TruthConformanceError(ValueError):
    pass

def require(ok: bool, message: str) -> None:
    if not ok:
        raise TruthConformanceError(message)

def load(path: str):
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def validate_truth_integration() -> dict[str, object]:
    pin=load_pin()
    validate_pin(pin)
    conformance=load("truth/TRUTH_ENGINE_CONFORMANCE.json")
    state=load("PORTFOLIO_BUILD_STATE.json")

    repo1=state["repositories"]["REPO-001"]
    require(
        repo1["last_inspected_sha"]==pin["source_revision"],
        "canonical Truth Engine repository cursor changed; reconformance required",
    )
    require(pin["copied_source_code"] is False,"Truth Engine source must remain external/pinned")
    require(conformance["schema_version"]=="1.0.0","conformance schema_version mismatch")
    source=conformance["source"]
    require(source["repository"]==pin["source_repository"],"conformance repository mismatch")
    require(source["revision"]==pin["source_revision"],"conformance revision mismatch")
    require(source["path"]==pin["source_path"],"conformance path mismatch")
    require(source["blob_sha"]==pin["source_blob_sha"],"conformance blob mismatch")
    require(source["test_blob_sha"]==pin["source_test_blob_sha"],"conformance test blob mismatch")
    require(conformance["authority_change"]=="NONE","truth integration cannot grant authority")

    expected={
        "PROVEN":"VERIFIED",
        "CONTESTED":"CONTRADICTED",
        "NOT_PROVEN":"UNKNOWN",
        "UNKNOWN":"UNKNOWN",
        "required_stale_precedence":"STALE",
        "required_conflict_precedence":"CONTRADICTED",
    }
    require(conformance["portfolio_projection"]==expected,"truth projection mapping changed")

    semantics=conformance["checked_semantics"]
    require(semantics["no_evidence"]=="UNKNOWN_NOT_FALSE","missing evidence must remain unknown")
    require(semantics["stale_evidence"]=="VISIBLE_NOT_PROOF","stale evidence semantics weakened")
    require(semantics["wrong_authority"]=="INADMISSIBLE","authority semantics weakened")
    require(semantics["future_observation"]=="INADMISSIBLE","future evidence semantics weakened")
    require(semantics["contradictions"]=="PRESERVED_AND_CONTESTED","contradiction semantics weakened")
    require(semantics["independence"]=="REQUIRED_WHEN_CONFIGURED","independence semantics weakened")
    require(semantics["evidence_set_identity"]=="HASH_CHANGES_WITH_EVIDENCE","receipt identity semantics weakened")
    require(semantics["counterfactual_planning"]=="DOES_NOT_PERSIST_FAKE_EVIDENCE","counterfactual isolation weakened")

    return {
        "source_revision":pin["source_revision"],
        "source_blob_sha":pin["source_blob_sha"],
        "verdicts":len(pin["upstream_contract"]["verdicts"]),
        "finding_statuses":len(pin["upstream_contract"]["finding_statuses"]),
        "projection_states":sorted(set(expected.values())),
    }

if __name__=="__main__":
    print("portfolio-brain Step 5 truth integration: PASS",json.dumps(validate_truth_integration(),sort_keys=True))
