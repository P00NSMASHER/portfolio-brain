"""Source-bound operator-engineering outcome: reviewed release -> measured state.

A before/after snapshot is a verified measurement, never proof of causality,
customer revenue, cost saving, sustained reliability, or unrelated discoveries.
No mutation, no Web calls beyond the strict original GitHub GET allowlist.
"""
from __future__ import annotations
import base64
from datetime import datetime
import json
import re
import urllib.request
from brain.state_maintenance import VERIFIED_PRODUCTION_RAW_BYTES, VERIFIED_PRODUCTION_COMPRESSED_BYTES

REPO="P00NSMASHER/portfolio-brain"
ROOT="https://api.github.com/repos/"+REPO+"/"
SHA=re.compile(r"[0-9a-f]{40}\Z")
HASH=re.compile(r"[0-9a-f]{64}\Z")
REQUIRED={"validate":15368,"portfolio-phase1-gate":5121826}

class MeasurementHold(ValueError):
    pass

def need(condition, message):
    if not condition:
        raise MeasurementHold(message)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class GitHubOriginal:
    def __init__(self, token):
        need(type(token) is str and 20<=len(token)<=4096, "MEASUREMENT_TOKEN_MISSING")
        self.token=token
        self.reads=0

    def get(self, path):
        allowed=(path=="pulls/865"
                 or re.fullmatch(r"git/commits/[0-9a-f]{40}",path)
                 or re.fullmatch(r"compare/[0-9a-f]{40}[.][.][.][0-9a-f]{40}",path)
                 or re.fullmatch(r"commits/[0-9a-f]{40}/check-runs\?per_page=100",path)
                 or re.fullmatch(r"contents/state-manifest\.json\?ref=[0-9a-f]{40}",path))
        need(allowed, "MEASUREMENT_ROUTE_REFUSED")
        self.reads+=1
        need(self.reads<=12, "MEASUREMENT_READ_BUDGET_EXCEEDED")
        req=urllib.request.Request(ROOT+path,headers={
            "Authorization":"Bearer "+self.token,
            "Accept":"application/vnd.github+json",
            "User-Agent":"portfolio-brain-technical-outcome-readonly",
            "X-GitHub-Api-Version":"2022-11-28"})
        try:
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=10) as response:
                need(response.status==200,"MEASUREMENT_PROVIDER_STATUS")
                raw=response.read(600_001)
        except (OSError,urllib.error.URLError) as exc:
            raise MeasurementHold("MEASUREMENT_PROVIDER_UNAVAILABLE") from exc
        need(len(raw)<=600_000,"MEASUREMENT_RESPONSE_TOO_LARGE")
        try:
            return json.loads(raw)
        except (ValueError,UnicodeError) as exc:
            raise MeasurementHold("MEASUREMENT_RESPONSE_INVALID") from exc

def instant(value):
    need(type(value) is str and value.endswith("Z"),"MEASUREMENT_TIME_INVALID")
    try:
        result=datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as exc:
        raise MeasurementHold("MEASUREMENT_TIME_INVALID") from exc
    return result

def manifest(api,sha):
    data=api.get("contents/state-manifest.json?ref="+sha)
    need(type(data) is dict and data.get("encoding")=="base64"
         and type(data.get("content")) is str and len(data["content"])<=16_000
         and data.get("type")=="file", "MEASUREMENT_MANIFEST_SOURCE_INVALID")
    try:
        binary=base64.b64decode(data["content"],validate=False)
        need(len(binary)<=12_000,"MEASUREMENT_MANIFEST_TOO_LARGE")
        payload=json.loads(binary)
    except (ValueError,UnicodeError) as exc:
        raise MeasurementHold("MEASUREMENT_MANIFEST_INVALID") from exc
    need(type(payload) is dict and payload.get("format")=="sqlite-zlib-chunks-v1"
         and payload.get("schema_version")==1
         and type(payload.get("raw_size")) is int
         and 0<payload["raw_size"]<=5_000_000_000
         and type(payload.get("compressed_size")) is int
         and 0<payload["compressed_size"]<=VERIFIED_PRODUCTION_COMPRESSED_BYTES
         and type(payload.get("raw_sha256")) is str
         and HASH.fullmatch(payload["raw_sha256"])
         and type(payload.get("chunks")) is list
         and 0<len(payload["chunks"])<=1000
         and all(type(x) is dict and type(x.get("size")) is int and x["size"]>0
                 and type(x.get("raw_size")) is int and x["raw_size"]>0
                 for x in payload["chunks"])
         and sum(x["size"] for x in payload["chunks"])==payload["compressed_size"]
         and sum(x["raw_size"] for x in payload["chunks"])==payload["raw_size"],
         "MEASUREMENT_MANIFEST_UNTRUSTED")
    return {"raw_bytes":payload["raw_size"],
            "compressed_bytes":payload["compressed_size"],
            "raw_sha256":payload["raw_sha256"],"ref":sha}

def evaluate(api,case):
    need(type(case) is dict
         and set(case)=={"schema_version","kind","source_pr","candidate_sha",
                        "merge_sha","before","after"}
         and case["schema_version"]==1
         and case["kind"]=="OPERATOR_REQUESTED_STORAGE_REPAIR"
         and case["source_pr"]==865
         and type(case["candidate_sha"]) is str and SHA.fullmatch(case["candidate_sha"])
         and type(case["merge_sha"]) is str and SHA.fullmatch(case["merge_sha"])
         and type(case["before"]) is list and len(case["before"])==2
         and type(case["after"]) is list and len(case["after"])==2
         and all(type(x) is str and SHA.fullmatch(x) for x in case["before"]+case["after"])
         and len(set(case["before"]+case["after"]))==4,
         "MEASUREMENT_CASE_SCHEMA_DENIED")
    pr=api.get("pulls/865")
    need(type(pr) is dict and pr.get("number")==865 and pr.get("merged") is True
         and pr.get("state")=="closed"
         and pr.get("head",{}).get("sha")==case["candidate_sha"]
         and pr.get("merge_commit_sha")==case["merge_sha"]
         and pr.get("base",{}).get("repo",{}).get("full_name")==REPO
         and pr.get("base",{}).get("ref")=="main",
         "MEASUREMENT_RELEASE_UNVERIFIED")
    checks=api.get("commits/"+case["candidate_sha"]+"/check-runs?per_page=100")
    rows=checks.get("check_runs") if type(checks) is dict else None
    need(type(rows) is list and type(checks.get("total_count")) is int
         and len(rows)==checks["total_count"]<100
         and all(sum(type(x) is dict and x.get("name")==name
                     and x.get("head_sha")==case["candidate_sha"]
                     and x.get("status")=="completed"
                     and x.get("conclusion")=="success"
                     and x.get("app",{}).get("id")==app
                     for x in rows)==1 for name,app in REQUIRED.items()),
         "MEASUREMENT_INDEPENDENT_REVIEW_UNVERIFIED")
    baseline=case["before"][0]
    last=case["after"][-1]
    ancestry=api.get("compare/"+baseline+"..."+last)
    compared=ancestry.get("commits") if type(ancestry) is dict else None
    need(type(compared) is list and type(ancestry.get("total_commits")) is int
         and len(compared)==ancestry["total_commits"]<250
         and ancestry.get("merge_base_commit",{}).get("sha")==baseline
         and ancestry.get("behind_by")==0
         and type(ancestry.get("ahead_by")) is int
         and ancestry["ahead_by"]>=3
         and {x.get("sha") for x in compared if type(x) is dict} >=
         set(case["before"][1:]+case["after"]),
         "MEASUREMENT_STATE_ANCESTRY_UNVERIFIED")
    records=[]
    for sha in case["before"]+case["after"]:
        commit=api.get("git/commits/"+sha)
        need(type(commit) is dict and commit.get("sha")==sha,
             "MEASUREMENT_EXACT_COMMIT_UNAVAILABLE")
        msg=commit.get("message")
        need(type(msg) is str and re.fullmatch(
            r"Persist Brain v2 cycle [1-9][0-9]+ source [0-9a-f]{40}",msg),
            "MEASUREMENT_STATE_PROVENANCE_UNVERIFIED")
        row=manifest(api,sha)
        row["observed_at"]=commit.get("committer",{}).get("date")
        row["source_sha"]=msg.split()[-1]
        row["time"]=instant(row["observed_at"])
        records.append(row)
    b0,b1,a0,a1=records
    release=instant(pr.get("merged_at"))
    need(b0["time"]<b1["time"]<release<a0["time"]<a1["time"]
         and a0["source_sha"]==a1["source_sha"]==case["merge_sha"]
         and b0["source_sha"]==b1["source_sha"],
         "MEASUREMENT_SOURCE_OR_TIME_BOUNDARY_INVALID")
    before_seconds=int((b1["time"]-b0["time"]).total_seconds())
    after_seconds=int((a1["time"]-a0["time"]).total_seconds())
    need(before_seconds>=1800 and after_seconds>=1800
         and before_seconds<=24*3600 and after_seconds<=24*3600,
         "MEASUREMENT_WINDOW_INVALID")
    before_raw=b1["raw_bytes"]-b0["raw_bytes"]
    after_raw=a1["raw_bytes"]-a0["raw_bytes"]
    pre_rate=round(before_raw*3600/before_seconds)
    post_rate=round(after_raw*3600/after_seconds)
    return {"schema_version":1,
            "status":"INDEPENDENTLY_MEASURED_SHORT_WINDOW_TECHNICAL_OUTCOME",
            "input_discovery":"OPERATOR_IDENTIFIED_PROBLEM_NOT_THIRD_PARTY_CODE",
            "reviewed_pr":865,"candidate_head_sha":case["candidate_sha"],
            "protected_merge_sha":case["merge_sha"],
            "review":"TWO_ORIGINAL_EXACT_HEAD_APP_CHECKS_PASSED",
            "release":"MERGED_ON_PROTECTED_MAIN",
            "before_refs":case["before"],"after_refs":case["after"],
            "before_hours":round(before_seconds/3600,3),
            "after_hours":round(after_seconds/3600,3),
            "before_raw_delta_bytes":before_raw,
            "after_raw_delta_bytes":after_raw,
            "before_raw_bytes_per_hour":pre_rate,
            "after_raw_bytes_per_hour":post_rate,
            "after_compressed_delta_bytes":a1["compressed_bytes"]-a0["compressed_bytes"],
            "raw_capacity_margin_at_end_bytes":VERIFIED_PRODUCTION_RAW_BYTES-a1["raw_bytes"],
            "compressed_capacity_margin_at_end_bytes":VERIFIED_PRODUCTION_COMPRESSED_BYTES-a1["compressed_bytes"],
            "verified_provider_reads":api.reads,
            "sustained_improvement_verified":False,
            "causal_attribution_verified":False,
            "customer_value_verified":None,
            "source_code_discovery_attribution_verified":None,
            "provider_writes":0}
