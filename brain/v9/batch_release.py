"""Pure release-evidence decision; never merges or certifies a live acceptance.

A caller-provided check list is NOT a provider-attested check list. The
independent GitHub issuer and exact-head must be re-read from the provider
before any protected merge. The six-hour unattended acceptance is separate.
"""
from brain.v9.batch_queue import hashval

REQUIRED={"validate":15368,"portfolio-phase1-gate":5121826}
FIELDS={"schema_version","base_sha","candidate_sha","observed_main_sha",
        "observed_candidate_sha","all_changes_integrated","batch_closed",
        "unresolved_blockers","check_runs","independent_original_state_replay"}
def review_release(payload):
    baseline={"provider_writes":False,"production_accepted":False,
              "six_hour_acceptance_passed":False,"provider_evidence_authenticated":False,
              "must_verify_original_github_readback":True}
    def hold(status): return dict(baseline,status=status)
    if type(payload) is not dict or set(payload)!=FIELDS or type(payload["schema_version"]) is not int or payload["schema_version"]!=1:
        return hold("HOLD_RELEASE_MANIFEST_INVALID")
    if not (hashval(payload["base_sha"],40) and hashval(payload["candidate_sha"],40)
            and payload["candidate_sha"]!=payload["base_sha"]
            and payload["base_sha"]==payload["observed_main_sha"]
            and payload["candidate_sha"]==payload["observed_candidate_sha"]
            and payload["all_changes_integrated"] is True
            and payload["batch_closed"] is True
            and type(payload["unresolved_blockers"]) is int
            and payload["unresolved_blockers"]==0):
        return hold("HOLD_BATCH_OR_SOURCE_CHANGED")
    check_rows=payload["check_runs"]
    if type(check_rows) is not list or not 2<=len(check_rows)<=100:
        return hold("HOLD_TECHNICAL_EVIDENCE")
    found={}
    for row in check_rows:
        if type(row) is not dict or set(row)!={"name","app_id","head_sha","status","conclusion"}:
            return hold("HOLD_TECHNICAL_EVIDENCE")
        if row["name"] in REQUIRED:
            if row["name"] in found: return hold("HOLD_TECHNICAL_EVIDENCE")
            found[row["name"]]=row
    if len(found)!=2 or any(type(found[n]["app_id"]) is not int
            or found[n]["app_id"]!=issuer or found[n]["head_sha"]!=payload["candidate_sha"]
            or found[n]["status"]!="completed" or found[n]["conclusion"]!="success"
            for n,issuer in REQUIRED.items()):
        return hold("HOLD_TECHNICAL_EVIDENCE")
    return dict(baseline,status="TECHNICALLY_READY_FOR_GOVERNED_RELEASE",
                readiness_scope="CALLER_CLAIM_ONLY_PENDING_PROVIDER_READBACK",
                base_sha=payload["base_sha"],candidate_sha=payload["candidate_sha"])
