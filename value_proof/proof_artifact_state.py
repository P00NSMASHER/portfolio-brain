#!/usr/bin/env python3
"""Restore the newest usable Step 7 model-value proof artifact for Step 8 bootstrap."""
from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.request
import zipfile
from pathlib import Path

from model_router.model_router import validate_call_receipt
from runtime.artifact_http import open_url
from value_proof.feedback_loop import validate_value_outcome

ARTIFACT_NAME="portfolio-model-value-proof"
REQUIRED_MEMBERS={
  "value_outcome.json",
  "model_provider_receipt.json",
  "independent_verifier_provider_receipt.json",
}
MAX_ARCHIVE_BYTES=2_000_000
MAX_MEMBER_BYTES=500_000

class ProofRestoreError(RuntimeError):
    pass

def _atomic_write(path:Path,payload:bytes)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name("."+path.name+".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp,path)

def _validate_member(name:str,payload:bytes)->dict:
    if len(payload)>MAX_MEMBER_BYTES:
        raise ProofRestoreError(f"{name} exceeds byte budget")
    try:
        value=json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise ProofRestoreError(f"{name} is not valid UTF-8 JSON") from exc
    if name=="value_outcome.json":
        validate_value_outcome(value)
    else:
        validate_call_receipt(value)
    return value

def _validate_lineage(values:dict[str,dict])->None:
    outcome=values["value_outcome.json"]
    builder=values["model_provider_receipt.json"]
    verifier=values["independent_verifier_provider_receipt.json"]
    if outcome["builder_provider_receipt_hash"]!=builder["receipt_hash"]:
        raise ProofRestoreError("builder provider receipt lineage mismatch")
    if outcome["verifier_provider_receipt_hash"]!=verifier["receipt_hash"]:
        raise ProofRestoreError("verifier provider receipt lineage mismatch")
    if outcome["builder_model_id"]!=builder["model_id"]:
        raise ProofRestoreError("builder model lineage mismatch")
    if outcome["verifier_model_id"]!=verifier["model_id"]:
        raise ProofRestoreError("verifier model lineage mismatch")

def restore(output_dir:Path)->dict:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repo=os.environ.get("GITHUB_REPOSITORY")
    current_run=os.environ.get("GITHUB_RUN_ID")
    branch=os.environ.get("GITHUB_REF_NAME")
    if not token or not repo:
        raise ProofRestoreError("GitHub Actions context required")
    used=0
    def get(url:str)->bytes:
        nonlocal used
        if used>=8:
            raise ProofRestoreError("proof restore request budget exceeded")
        used+=1
        req=urllib.request.Request(url,headers={
          "Accept":"application/vnd.github+json",
          "Authorization":f"Bearer {token}",
          "X-GitHub-Api-Version":"2022-11-28",
          "User-Agent":"portfolio-brain-proof-restore/1.0",
        },method="GET")
        last=None
        for attempt in range(3):
            try:
                with open_url(req,timeout=20) as resp:
                    return resp.read()
            except Exception as exc:
                last=exc
                if attempt<2:
                    time.sleep(attempt+1)
        raise ProofRestoreError(str(last))
    data=json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={ARTIFACT_NAME}&per_page=100").decode())
    candidates=[
      x for x in data.get("artifacts",[])
      if not x.get("expired")
      and str((x.get("workflow_run") or {}).get("id"))!=str(current_run)
      and (branch is None or (x.get("workflow_run") or {}).get("head_branch")==branch)
    ]
    candidates.sort(key=lambda x:(x.get("created_at",""),x.get("id",0)),reverse=True)
    for item in candidates:
        url=item.get("archive_download_url")
        if not url:
            continue
        try:
            raw=get(url)
            if len(raw)>MAX_ARCHIVE_BYTES:
                continue
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names=[i.filename for i in zf.infolist() if not i.is_dir()]
                if not REQUIRED_MEMBERS.issubset(set(names)):
                    continue
                values={}
                payloads={}
                for name in REQUIRED_MEMBERS:
                    infos=[i for i in zf.infolist() if i.filename==name]
                    if len(infos)!=1 or infos[0].file_size>MAX_MEMBER_BYTES:
                        raise ProofRestoreError("proof artifact member shape invalid")
                    payload=zf.read(infos[0])
                    payloads[name]=payload
                    values[name]=_validate_member(name,payload)
                _validate_lineage(values)
        except Exception:
            continue
        output_dir.mkdir(parents=True,exist_ok=True)
        for name,payload in payloads.items():
            _atomic_write(output_dir/name,payload)
        receipt={
          "schema_version":"1.0.0",
          "restore_status":"RESTORED",
          "artifact_id":item.get("id"),
          "artifact_name":item.get("name"),
          "artifact_created_at":item.get("created_at"),
          "source_run_id":(item.get("workflow_run") or {}).get("id"),
          "source_head_sha":(item.get("workflow_run") or {}).get("head_sha"),
          "value_outcome_id":values["value_outcome.json"]["outcome_id"],
          "value_outcome_hash":values["value_outcome.json"]["outcome_hash"],
        }
        _atomic_write(output_dir/"restore_receipt.json",(json.dumps(receipt,indent=2,sort_keys=True)+"\n").encode())
        return receipt
    raise ProofRestoreError("no valid prior model-value proof artifact found")

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    receipt=restore(args.output_dir)
    print(json.dumps(receipt,sort_keys=True))

if __name__=="__main__":
    main()
