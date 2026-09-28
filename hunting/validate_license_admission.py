"""Deterministic synthetic controls; no source-rights verification is asserted."""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
from hunting.license_admission import admission, load_policy
from hunting.rights_gate import build_rights_record, RightsGateError

LICENSES = ("MIT", "Apache-2.0", "GPL-3.0-only", "AGPL-3.0-only", "BUSL-1.1", "PolyForm-Noncommercial-1.0.0", "LicenseRef-Proprietary", "NOASSERTION", None)

def validate() -> dict:
    policy = load_policy()
    if policy["mode"] != "ADVISORY_OWNER_ASSUMED":
        raise AssertionError("owner-requested advisory mode not active")
    controls = []
    for spdx in LICENSES:
        record = build_rights_record(
            {"full_name": "synthetic/license-control", "license": {"spdx_id": spdx}},
            {"revision": "a"*40, "paths": [], "tree_sha": "b"*40, "truncated": False},
        )
        before = copy.deepcopy(record)
        decision = admission(record)
        assert decision["allowed"] is True
        assert decision["status"] == "OPERATOR_ASSUMED"
        assert decision["rights_verification_claimed"] is False
        assert before == record
        assert record["automatic_reuse_authority_granted"] is False
        assert record["license_text_hash"] is None
        controls.append({"license_spdx": spdx, "admitted": True, "rights_record_preserved": True})
    tampered = copy.deepcopy(record)
    tampered["source_revision_sha"] = "c"*40
    try:
        admission(tampered)
    except RightsGateError:
        pass
    else:
        raise AssertionError("tampered rights evidence admitted")
    return {"schema_version":"1.0.0", "status":"PASS", "evidence_class":"SYNTHETIC_CONTROLS_ONLY", "source_commit":os.environ.get("GITHUB_SHA"), "policy_mode":policy["mode"], "rights_verification_claimed":False, "tampered_receipt_rejected":True, "controls":controls}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    result=validate()
    text=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding="utf-8")
    print(text,end="")

if __name__=="__main__":
    main()
