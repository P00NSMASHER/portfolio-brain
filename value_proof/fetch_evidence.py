#!/usr/bin/env python3
"""Fetch the exact public source files bound by the model value task contract."""
from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from value_proof.model_task import load_contract, make_evidence_pack, validate_evidence_pack

class EvidenceFetchError(ValueError):
    pass

def req(ok,msg):
    if not ok:
        raise EvidenceFetchError(msg)

def _get(url,token=None):
    headers={
      "Accept":"application/vnd.github+json",
      "X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"portfolio-brain-value-proof/1.0",
    }
    if token:
        headers["Authorization"]="Bearer "+token
    request=urllib.request.Request(url,headers=headers,method="GET")
    with urllib.request.urlopen(request,timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

def fetch_evidence(contract,token=None):
    src=contract["source_candidate"]
    repo=src["repository_full_name"]
    metadata=_get("https://api.github.com/repos/"+urllib.parse.quote(repo,safe="/"),token)
    req(metadata.get("private") is False,"evidence repository is not public")
    req(int(metadata["id"])==int(src["repository_id"]),"evidence repository identity drift")
    files=[]
    for path in contract["evidence_manifest"]["required_paths"]:
        url=(
          "https://api.github.com/repos/"+urllib.parse.quote(repo,safe="/")+
          "/contents/"+urllib.parse.quote(path,safe="/")+
          "?ref="+urllib.parse.quote(src["revision"],safe="")
        )
        data=_get(url,token)
        req(data.get("type")=="file","evidence path is not a file")
        req(data.get("path")==path,"evidence path drift")
        req(data.get("encoding")=="base64","unexpected evidence encoding")
        raw=base64.b64decode(data["content"])
        req(len(raw)<=50000,"individual evidence file exceeds bound")
        text=raw.decode("utf-8")
        files.append({"path":path,"content":text})
    pack=make_evidence_pack(
      repository_full_name=repo,
      repository_id=int(src["repository_id"]),
      revision=src["revision"],
      files=files,
    )
    validate_evidence_pack(pack,contract)
    return pack

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--contract",type=Path,default=Path("value_proof/MODEL_TASK_CONTRACT.json"))
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    contract=load_contract(args.contract)
    pack=fetch_evidence(contract,os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN"))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(pack,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
      "status":"PASS",
      "repository":pack["repository_full_name"],
      "revision":pack["revision"],
      "files":len(pack["files"]),
      "pack_hash":pack["pack_hash"],
    },sort_keys=True))

if __name__=="__main__":
    main()
