#!/usr/bin/env python3
"""Repository license observations plus the Brain owner's non-blocking policy.

Observed SPDX data, copyright, conditions, and source hashes remain unchanged.
Operational admission is separate: the owner assumes rights for all candidates.
That assumption is never labeled independently verified or execution authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from hunting.rights_usage import current_usage_decision, validate_usage_decision

ROOT=Path(__file__).resolve().parents[1]

class RightsGateError(ValueError):
    pass

def _req(ok: bool, msg: str) -> None:
    if not ok:
        raise RightsGateError(msg)

def _canon(v: Any) -> str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def _hash(v: Any) -> str:
    return "sha256:"+hashlib.sha256(_canon(v).encode("utf-8")).hexdigest()

def _policy() -> dict[str,Any]:
    return json.loads((ROOT/"hunting"/"RIGHTS_GATE_POLICY.json").read_text(encoding="utf-8"))

def _detect_spdx(text: str | None) -> str | None:
    if not text:
        return None
    t=text.casefold()
    if "gnu affero general public license" in t:
        return "AGPL-3.0-or-later"
    if "gnu lesser general public license" in t:
        return "LGPL-3.0-or-later"
    if "gnu general public license" in t:
        return "GPL-3.0-or-later"
    if "mozilla public license version 2.0" in t or "mozilla public license, version 2.0" in t:
        return "MPL-2.0"
    if "apache license" in t and "version 2.0" in t:
        return "Apache-2.0"
    if "permission is hereby granted, free of charge" in t:
        return "MIT"
    if "redistribution and use in source and binary forms" in t:
        return "BSD-3-Clause"
    if "the unlicense" in t and "public domain" in t:
        return "Unlicense"
    return None

def _copyright_owner(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines()[:80]:
        m=re.search(r"copyright\s*(?:\(c\)|©)?\s*(?:19|20)\d{2}(?:[-–, ]+(?:19|20)\d{2})?\s+(.+)",line,re.I)
        if m:
            owner=" ".join(m.group(1).strip(" .,:;").split())
            if owner:
                return owner[:240]
    return None

def _dependency_manifests(paths: list[str]) -> list[str]:
    names=set(_policy()["dependency_manifest_names"])
    return sorted(p for p in paths if Path(p).name in names)

def _classify(spdx: str | None) -> dict[str,Any]:
    # Observational classification only. Internal admission uses rights_usage.
    p=_policy()
    normalized=None if spdx is None else str(spdx).strip()
    if not normalized or normalized.upper() in set(p["unknown_spdx_values"]):
        return {
          "rights_classification":"NO_LICENSE_NO_REUSE",
          "commercial_use_allowed":False,
          "modification_allowed":False,
          "redistribution_conditions":["No recognized license grant is established by discovery; default copyright restrictions apply."],
          "network_copyleft":None,
          "source_disclosure_required":None,
          "dependency_license_risk":"HIGH",
          "allowed_integration_mode":"ARCHITECTURE_STUDY_ONLY_NO_CODE_REUSE",
        }
    if normalized in set(p["permissive_spdx"]):
        conditions=["Preserve applicable copyright and license notices."]
        if normalized=="Apache-2.0":
            conditions+=["Preserve NOTICE content when applicable.","Observe Apache-2.0 patent/license conditions."]
        return {
          "rights_classification":"PERMISSIVE_DEPENDENCY",
          "commercial_use_allowed":True,
          "modification_allowed":True,
          "redistribution_conditions":conditions,
          "network_copyleft":False,
          "source_disclosure_required":False,
          "dependency_license_risk":"UNASSESSED",
          "allowed_integration_mode":"DEPENDENCY_OR_FORK_WITH_REQUIRED_NOTICES",
        }
    if normalized in set(p["file_level_copyleft_spdx"]):
        return {
          "rights_classification":"COPYLEFT_REVIEW",
          "commercial_use_allowed":True,
          "modification_allowed":True,
          "redistribution_conditions":["Modified covered files may require source disclosure and license preservation."],
          "network_copyleft":False,
          "source_disclosure_required":True,
          "dependency_license_risk":"ELEVATED",
          "allowed_integration_mode":"LEGAL_COMPLIANCE_REVIEW_BEFORE_REUSE",
        }
    if normalized in set(p["copyleft_spdx"]):
        network=normalized.startswith("AGPL") or normalized=="SSPL-1.0"
        return {
          "rights_classification":"COPYLEFT_REVIEW",
          "commercial_use_allowed":True,
          "modification_allowed":True,
          "redistribution_conditions":["Copyleft/source-disclosure obligations may apply to redistribution or combined works."],
          "network_copyleft":network,
          "source_disclosure_required":True,
          "dependency_license_risk":"ELEVATED",
          "allowed_integration_mode":"LEGAL_COMPLIANCE_REVIEW_BEFORE_REUSE",
        }
    if normalized in set(p["source_available_or_restricted_spdx"]):
        return {
          "rights_classification":"SEPARATE_PERMISSION_REQUIRED",
          "commercial_use_allowed":None,
          "modification_allowed":None,
          "redistribution_conditions":["Source-available or restricted terms require separate review before commercial reuse."],
          "network_copyleft":None,
          "source_disclosure_required":None,
          "dependency_license_risk":"ELEVATED",
          "allowed_integration_mode":"SEPARATE_PERMISSION_OR_LICENSE_REVIEW_REQUIRED",
        }
    return {
      "rights_classification":"SEPARATE_PERMISSION_REQUIRED",
      "commercial_use_allowed":None,
      "modification_allowed":None,
      "redistribution_conditions":["Custom or unrecognized license terms require separate verification before reuse."],
      "network_copyleft":None,
      "source_disclosure_required":None,
      "dependency_license_risk":"UNASSESSED",
      "allowed_integration_mode":"SEPARATE_PERMISSION_OR_LICENSE_REVIEW_REQUIRED",
    }

def build_rights_record(candidate: dict[str,Any], inspection: dict[str,Any], evidence: dict[str,Any] | None=None) -> dict[str,Any]:
    evidence=evidence or {}
    revision=inspection.get("revision")
    _req(isinstance(revision,str) and len(revision)==40,"rights record requires exact revision")
    license_meta=candidate.get("license") if isinstance(candidate.get("license"),dict) else {}
    spdx=evidence.get("license_spdx") or license_meta.get("spdx_id")
    if isinstance(spdx,str) and spdx.upper() in {"NOASSERTION","OTHER"}:
        spdx=None
    license_text=evidence.get("license_text")
    detected=_detect_spdx(license_text)
    spdx=spdx or detected
    classification=_classify(spdx)
    license_text_hash=None if not license_text else "sha256:"+hashlib.sha256(license_text.encode("utf-8")).hexdigest()
    manifests=_dependency_manifests(list(inspection.get("paths") or []))
    body={
      "schema_version":"1.0.0",
      "repository_full_name":candidate.get("full_name"),
      "source_revision_sha":revision,
      "license_spdx":spdx,
      "license_path":evidence.get("license_path"),
      "license_text_hash":license_text_hash,
      "copyright_owner":_copyright_owner(license_text),
      "commercial_use_allowed":classification["commercial_use_allowed"],
      "modification_allowed":classification["modification_allowed"],
      "redistribution_conditions":classification["redistribution_conditions"],
      "network_copyleft":classification["network_copyleft"],
      "source_disclosure_required":classification["source_disclosure_required"],
      "dependency_license_risk":classification["dependency_license_risk"],
      "dependency_manifest_paths":manifests,
      "rights_classification":classification["rights_classification"],
      "allowed_integration_mode":classification["allowed_integration_mode"],
      "automatic_reuse_authority_granted":False,
      "usage_policy":current_usage_decision(),
      "provenance_refs":[
        f"github:{candidate.get('full_name')}@{revision}",
        *( [f"github-license:{candidate.get('full_name')}@{revision}:{evidence.get('license_path')}"] if evidence.get("license_path") else [] )
      ],
    }
    return {**body,"rights_hash":_hash(body)}

def validate_rights_record(record: dict[str,Any]) -> None:
    required={
      "schema_version","repository_full_name","source_revision_sha","license_spdx","license_path",
      "license_text_hash","copyright_owner","commercial_use_allowed","modification_allowed",
      "redistribution_conditions","network_copyleft","source_disclosure_required",
      "dependency_license_risk","dependency_manifest_paths","rights_classification",
      "allowed_integration_mode","automatic_reuse_authority_granted","provenance_refs","rights_hash"
    }
    _req(isinstance(record,dict) and set(record) in (required,required|{"usage_policy"}),"rights record fields changed")
    _req(record["schema_version"]=="1.0.0","rights schema mismatch")
    _req(isinstance(record["source_revision_sha"],str) and len(record["source_revision_sha"])==40,"rights revision invalid")
    _req(record["automatic_reuse_authority_granted"] is False,"discovery granted reuse authority")
    _req(record["rights_classification"] in set(_policy()["classifications"]),"rights classification invalid")
    _req(isinstance(record["redistribution_conditions"],list) and record["redistribution_conditions"],"redistribution conditions missing")
    _req(isinstance(record["dependency_manifest_paths"],list),"dependency manifest paths invalid")
    _req(isinstance(record["provenance_refs"],list) and record["provenance_refs"],"rights provenance missing")
    if "usage_policy" in record:
        validate_usage_decision(record["usage_policy"])
    body=dict(record);given=body.pop("rights_hash")
    _req(given==_hash(body),"rights_hash mismatch")
