#!/usr/bin/env python3
"""Bounded REPO-001 scout intake into the existing Portfolio Hunter research lane."""
from __future__ import annotations
import argparse, base64, hashlib, json, os, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]

class Repo001IntakeError(ValueError):
    pass

def req(ok: bool, message: str)->None:
    if not ok:
        raise Repo001IntakeError(message)

def load_policy()->dict:
    return json.loads((ROOT/"hunting"/"REPO001_INTAKE_POLICY.json").read_text(encoding="utf-8"))

def canon(value: Any)->bytes:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")

def digest(value: Any)->str:
    return "sha256:"+hashlib.sha256(canon(value)).hexdigest()

def is_sha(value: Any)->bool:
    return isinstance(value,str) and len(value)==40 and all(c in "0123456789abcdef" for c in value)

def _repo001_revision_from_cycle(cycle: dict)->str:
    observations=[row for row in cycle.get("observations",[]) if row.get("repository_id")=="REPO-001"]
    req(len(observations)==1,"runtime cycle must contain exactly one REPO-001 observation")
    observation=observations[0]
    req(observation.get("status") in {"UNCHANGED","INITIALIZED","CHANGED"},"REPO-001 observation is not eligible for intake")
    revision=observation.get("current_sha")
    req(is_sha(revision),"REPO-001 observation lacks exact revision")
    return revision

def fetch_snapshot(path: str, *, source_revision: str, token: str|None=None)->dict:
    policy=load_policy()
    owner_repo=policy["source_repository_full_name"]
    owner,name=owner_repo.split("/",1)
    url=(
      f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
      f"/contents/{urllib.parse.quote(path,safe='/')}?ref={urllib.parse.quote(source_revision,safe='')}"
    )
    headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
             "User-Agent":"portfolio-brain-repo001-intake/1.0"}
    if token:
        headers["Authorization"]="Bearer "+token
    request=urllib.request.Request(url,headers=headers,method="GET")
    with urllib.request.urlopen(request,timeout=20) as response:
        req(response.status==200,f"REPO-001 snapshot fetch failed: HTTP {response.status}")
        payload=json.loads(response.read().decode("utf-8"))
    req(payload.get("type")=="file" and payload.get("encoding")=="base64","REPO-001 snapshot response invalid")
    try:
        raw=base64.b64decode(payload["content"],validate=False)
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise Repo001IntakeError("REPO-001 scout snapshot is invalid JSON") from exc

def _candidate_identity(candidate: dict)->str:
    return f"{candidate['repository']}@{candidate['exact_revision']}"

def _eligible(candidate: dict, policy: dict)->tuple[bool,str]:
    gate=policy["eligibility"]
    if candidate.get("status")!=gate["required_candidate_status"]:
        return False,"STATUS_NOT_ELIGIBLE"
    if gate["require_exact_candidate_revision"] and not is_sha(candidate.get("exact_revision")):
        return False,"EXACT_REVISION_MISSING"
    if candidate.get("archived") is True and not gate["archived_allowed"]:
        return False,"ARCHIVED_SOURCE"
    if type(candidate.get("triage_score")) is not int or candidate["triage_score"]<gate["minimum_triage_score"]:
        return False,"BELOW_TRIAGE_GATE"
    if gate["require_root_code_signal"] and not candidate.get("root_code_signals"):
        return False,"NO_ROOT_CODE_SIGNAL"
    repo=candidate.get("repository")
    if not isinstance(repo,str) or repo.count("/")!=1:
        return False,"REPOSITORY_IDENTITY_INVALID"
    return True,"ELIGIBLE"

def build_intake(source_revision: str, snapshots: list[dict])->dict:
    policy=load_policy()
    req(is_sha(source_revision),"source repository revision must be exact SHA")
    req(policy["creates_hunter_engine"] is False and policy["promotes_to_hunter_proposal"] is False,
        "REPO-001 intake authority widened")
    req(len(snapshots)<=policy["bounds"]["max_source_snapshots"],"source snapshot bound exceeded")
    examined=0
    rejected: dict[str,int]={}
    candidates: dict[str,dict]={}
    workers: dict[str,set[str]]={}
    source_findings: dict[str,set[str]]={}

    for snapshot in snapshots:
        req(snapshot.get("authority")==policy["required_source_authority"],"scout source authority widened")
        worker=snapshot.get("worker_id")
        req(isinstance(worker,str) and worker.startswith("HUNTER-"),"scout worker identity invalid")
        rows=snapshot.get("candidates")
        req(isinstance(rows,list),"scout candidates missing")
        for candidate in rows:
            examined+=1
            req(examined<=policy["bounds"]["max_candidates_examined"],"candidate examination bound exceeded")
            ok,reason=_eligible(candidate,policy)
            if not ok:
                rejected[reason]=rejected.get(reason,0)+1
                continue
            identity=_candidate_identity(candidate)
            workers.setdefault(identity,set()).add(worker)
            finding_identity="R1F-"+hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24].upper()
            source_key=f"{policy['source_repository_full_name']}@{source_revision}:{finding_identity}"
            source_findings.setdefault(identity,set()).add(source_key)
            current=candidates.get(identity)
            if current is None or candidate["triage_score"]>current["triage_score"]:
                candidates[identity]=json.loads(json.dumps(candidate))

    ranked=sorted(candidates.items(),key=lambda item:(-item[1]["triage_score"],item[0]))
    cap=policy["bounds"]["max_eligible_intake_records"]
    records=[]
    for identity,candidate in ranked[:cap]:
        finding_identity="R1F-"+hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24].upper()
        source_identity=f"{policy['source_repository_full_name']}@{source_revision}:{finding_identity}"
        core={
          "schema_version":"1.0.0",
          "intake_finding_id":finding_identity,
          "source_identity":source_identity,
          "source_repository_id":policy["source_repository_id"],
          "source_repository_full_name":policy["source_repository_full_name"],
          "source_repository_revision":source_revision,
          "source_worker_ids":sorted(workers[identity]),
          "candidate_repository_full_name":candidate["repository"],
          "candidate_revision":candidate["exact_revision"],
          "candidate_identity":identity,
          "triage_score":candidate["triage_score"],
          "published_license_spdx":candidate.get("published_license_spdx"),
          "root_code_signals":sorted(set(candidate.get("root_code_signals") or [])),
          "discovery_query_hash":digest(str(candidate.get("discovery_query") or "")),
          "evidence_state":policy["evidence_state"],
          "destination":policy["destination"],
          "proposal_eligible":False,
          "technical_verified":False,
          "market_verified":False,
          "revenue_verified":False,
          "authority_granted":False,
        }
        records.append({**core,"record_hash":digest(core)})

    out={
      "schema_version":"1.0.0",
      "intake_id":policy["intake_id"],
      "source_repository_id":policy["source_repository_id"],
      "source_repository_full_name":policy["source_repository_full_name"],
      "source_repository_revision":source_revision,
      "authority_class":"OBSERVE",
      "destination":policy["destination"],
      "creates_hunter_engine":False,
      "promotes_to_hunter_proposal":False,
      "dedupe_key_fields":["source_repository_full_name","source_repository_revision","intake_finding_id"],
      "candidate_identity_dedupe":True,
      "source_snapshot_count":len(snapshots),
      "candidates_examined":examined,
      "eligible_unique_candidates":len(ranked),
      "intake_record_count":len(records),
      "bounded_deferred_count":max(0,len(ranked)-cap),
      "rejection_counts":dict(sorted(rejected.items())),
      "records":records,
      "verification_credit":{"technical":False,"market":False,"revenue":False},
    }
    out["receipt_hash"]=digest(out)
    return out

def validate_intake(receipt: dict)->None:
    policy=load_policy()
    req(receipt["source_repository_full_name"]==policy["source_repository_full_name"],"intake source repository mismatch")
    req(is_sha(receipt["source_repository_revision"]),"intake source revision invalid")
    req(receipt["authority_class"]=="OBSERVE","intake authority widened")
    req(receipt["creates_hunter_engine"] is False and receipt["promotes_to_hunter_proposal"] is False,"intake created/promoted duplicate Hunter path")
    req(receipt["intake_record_count"]<=policy["bounds"]["max_eligible_intake_records"],"intake output bound exceeded")
    req(receipt["verification_credit"]=={"technical":False,"market":False,"revenue":False},"intake gained verification credit")
    ids=set(); source_ids=set()
    for record in receipt["records"]:
        req(record["candidate_identity"] not in ids,"duplicate candidate identity admitted")
        ids.add(record["candidate_identity"])
        req(record["source_identity"] not in source_ids,"duplicate source finding admitted")
        source_ids.add(record["source_identity"])
        expected=f"{policy['source_repository_full_name']}@{receipt['source_repository_revision']}:{record['intake_finding_id']}"
        req(record["source_identity"]==expected,"source repository/revision/finding identity binding mismatch")
        req(record["proposal_eligible"] is False and record["authority_granted"] is False,"pre-verification intake escalated authority")
        req(not record["technical_verified"] and not record["market_verified"] and not record["revenue_verified"],"pre-verification intake claimed verification")
    body={k:v for k,v in receipt.items() if k!="receipt_hash"}
    req(receipt.get("receipt_hash")==digest(body),"intake receipt hash mismatch")

def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--source-revision",default=None)
    parser.add_argument("--cycle",default=None)
    parser.add_argument("--output",default="hunting/out/repo001_intake.json")
    args=parser.parse_args()
    if args.source_revision:
        revision=args.source_revision
    elif args.cycle:
        cycle=json.loads(Path(args.cycle).read_text(encoding="utf-8"))
        revision=_repo001_revision_from_cycle(cycle)
    else:
        parser.error("--source-revision or --cycle required")
    policy=load_policy()
    token=os.environ.get("PORTFOLIO_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    snapshots=[fetch_snapshot(path,source_revision=revision,token=token) for path in policy["source_paths"]]
    receipt=build_intake(revision,snapshots); validate_intake(receipt)
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(receipt,indent=2,sort_keys=True)+"\n"
    req(len(raw.encode("utf-8"))<=policy["bounds"]["max_output_bytes"],"intake output byte bound exceeded")
    output.write_text(raw,encoding="utf-8")
    print(json.dumps({"source_revision":revision,"records":receipt["intake_record_count"],
                      "deferred":receipt["bounded_deferred_count"],"destination":receipt["destination"]},sort_keys=True))

if __name__=="__main__":
    main()
