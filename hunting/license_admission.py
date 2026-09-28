"""License workflow admission, deliberately separate from source-rights evidence."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from hunting.rights_gate import validate_rights_record

POLICY_PATH = Path(__file__).with_name("LICENSE_ADMISSION_POLICY.json")

class LicenseAdmissionError(ValueError):
    pass

def load_policy() -> dict[str, Any]:
    p = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if p.get("schema_version") != "1.0.0" or p.get("scope") != "P00NSMASHER/portfolio-brain":
        raise LicenseAdmissionError("invalid license-admission policy scope/schema")
    if p.get("mode") not in {"ADVISORY_OWNER_ASSUMED", "ENFORCE"}:
        raise LicenseAdmissionError("unknown license-admission mode")
    if p.get("decision_basis") != "EXPLICIT_OWNER_REQUEST":
        raise LicenseAdmissionError("owner decision basis missing")
    if p.get("rights_verification_claimed") is not False:
        raise LicenseAdmissionError("workflow policy cannot verify source rights")
    if p.get("source_records_must_remain_unchanged") is not True:
        raise LicenseAdmissionError("source evidence preservation required")
    if p.get("security_access_budget_and_action_gates_unchanged") is not True:
        raise LicenseAdmissionError("license preference cannot change other controls")
    if p.get("license_based_blocking") is not (p["mode"] == "ENFORCE"):
        raise LicenseAdmissionError("license mode/blocking setting inconsistent")
    return p

def license_review_required() -> bool:
    return load_policy()["mode"] == "ENFORCE"

def admission(record: dict[str, Any], accepted_classes: Iterable[str] = ("PERMISSIVE_DEPENDENCY",)) -> dict[str, Any]:
    """Validate integrity, then admit under owner preference without changing facts."""
    validate_rights_record(record)
    p = load_policy()
    assumed = p["mode"] == "ADVISORY_OWNER_ASSUMED"
    allowed = assumed or record["rights_classification"] in set(accepted_classes)
    canonical = json.dumps(p,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return {
        "allowed": allowed,
        "status": "OPERATOR_ASSUMED" if assumed else ("POLICY_ALLOWED" if allowed else "POLICY_BLOCKED"),
        "license_based_blocking": not assumed,
        "rights_verification_claimed": False,
        "source_rights_hash": record["rights_hash"],
        "observed_rights_classification": record["rights_classification"],
        "policy_ref": "hunting/LICENSE_ADMISSION_POLICY.json",
        "policy_hash": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
    }
