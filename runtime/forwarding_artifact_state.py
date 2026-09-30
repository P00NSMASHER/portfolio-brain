#!/usr/bin/env python3
"""Restore the durable project-forwarding ledger from the runtime artifact."""
from __future__ import annotations
import argparse,io,json,os,time,urllib.request,zipfile
from pathlib import Path
from runtime.artifact_http import open_url
from runtime.artifact_restore import InvalidStateArtifact, _atomic_write, restore_latest_valid_state
from runtime.artifact_state import validate_runtime_artifact_bundle
from runtime.project_forwarding import seed_state, validate_state

ARTIFACT_NAME="portfolio-runtime-state"
MAX_CANDIDATES=5
class RestoreError(RuntimeError): pass

def _legacy_runtime_artifact(data:dict,downloaded:dict[str,bytes],*,current_run:str|None,
                             expected_head_branch:str|None)->dict|None:
    candidates=[
        item for item in data.get("artifacts",[])
        if not item.get("expired")
        and str((item.get("workflow_run") or {}).get("id"))!=str(current_run)
        and (
            expected_head_branch is None
            or (item.get("workflow_run") or {}).get("head_branch")==expected_head_branch
        )
    ]
    candidates.sort(key=lambda item:(item.get("created_at",""),item.get("id",0)),reverse=True)
    legacy=[]
    for item in candidates[:MAX_CANDIDATES]:
        url=item.get("archive_download_url")
        raw=downloaded.get(url) if isinstance(url,str) else None
        if raw is None:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if any(info.filename=="project_forwarding_state.json" for info in archive.infolist()):
                    return None
        except (zipfile.BadZipFile,OSError):
            continue
        try:
            validate_runtime_artifact_bundle(
                raw,max_archive_bytes=5_242_880,max_member_bytes=5_242_880
            )
        except InvalidStateArtifact:
            continue
        legacy.append(item)
    return legacy[0] if legacy else None

def restore(output:Path,metadata_output:Path|None=None)->str:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repo=os.environ.get("GITHUB_REPOSITORY"); run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo: return "NO_ACTIONS_CONTEXT"
    used=0
    downloaded={}
    def get(url:str)->bytes:
        nonlocal used
        last=None
        for attempt in range(3):
            if used>=6: raise RestoreError("project forwarding artifact request budget exceeded")
            used+=1
            request=urllib.request.Request(url,headers={
              "Accept":"application/vnd.github+json","Authorization":f"Bearer {token}",
              "X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-project-forwarding/1.0"
            },method="GET")
            try:
                with open_url(request,timeout=20) as response:
                    body=response.read()
                downloaded[url]=body
                return body
            except Exception as exc:
                last=exc
                if attempt<2: time.sleep(attempt+1)
        raise RestoreError(str(last))
    data=json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={ARTIFACT_NAME}&per_page=100").decode())
    branch=os.environ.get("GITHUB_REF_NAME")
    try:
        return restore_latest_valid_state(
          data,current_run=run,expected_head_branch=branch,
          download=get,output=output,member_name="project_forwarding_state.json",
          expected_state_id="portfolio-project-forwarding-state",max_archive_bytes=5_242_880,
          max_state_bytes=1_048_576,validator=validate_state,metadata_output=metadata_output,
          max_candidates=MAX_CANDIDATES)
    except InvalidStateArtifact as exc:
        if str(exc)!="no valid prior state artifact found":
            raise
        legacy=_legacy_runtime_artifact(
            data,downloaded,current_run=run,expected_head_branch=branch
        )
        if legacy is None:
            raise
        status="SEEDED_FROM_LEGACY_RUNTIME_ARTIFACT"
        _atomic_write(output,(json.dumps(seed_state(),sort_keys=True,separators=(",",":"))+"\n").encode())
        if metadata_output is not None:
            workflow_run=legacy.get("workflow_run") or {}
            metadata={
                "schema_version":"1.0.0","restore_status":status,
                "artifact_id":legacy.get("id"),"artifact_name":legacy.get("name"),
                "artifact_created_at":legacy.get("created_at"),
                "artifact_expires_at":legacy.get("expires_at"),
                "source_run_id":workflow_run.get("id"),
                "source_head_sha":workflow_run.get("head_sha"),
            }
            _atomic_write(metadata_output,(json.dumps(metadata,sort_keys=True)+"\n").encode())
        return status

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",required=True);ap.add_argument("--metadata-output",default=None);a=ap.parse_args()
    print(restore(Path(a.output),None if a.metadata_output is None else Path(a.metadata_output)))
if __name__=="__main__": main()
