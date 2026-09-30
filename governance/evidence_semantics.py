#!/usr/bin/env python3
"""Verification-credit semantics for telemetry, alerts, and publication evidence."""
from __future__ import annotations

class EvidenceSemanticsError(ValueError):
    pass

SEMANTICS={
  "HEARTBEAT":{"meaning":"CONNECTIVITY_LIVENESS_ONLY","technical":False,"market":False,"revenue":False},
  "NOTIFICATION":{"meaning":"ALERT_ONLY","technical":False,"market":False,"revenue":False},
  "PAGES_PUBLICATION":{"meaning":"PUBLICATION_ONLY","technical":False,"market":False,"revenue":False},
  "REPOSITORY_OBSERVATION":{"meaning":"OBSERVED_INPUT_ONLY","technical":False,"market":False,"revenue":False},
}

def verification_credit(evidence_kind: str)->dict:
    if evidence_kind not in SEMANTICS:
        raise EvidenceSemanticsError(f"unclassified evidence kind: {evidence_kind}")
    return dict(SEMANTICS[evidence_kind])

def can_verify(evidence_kind: str, dimension: str)->bool:
    if dimension not in {"technical","market","revenue"}:
        raise EvidenceSemanticsError(f"unknown verification dimension: {dimension}")
    return verification_credit(evidence_kind)[dimension]

def require_no_verification_credit(evidence_kind: str)->None:
    credit=verification_credit(evidence_kind)
    if any(credit[key] for key in ("technical","market","revenue")):
        raise EvidenceSemanticsError(f"{evidence_kind} improperly grants verification credit")
