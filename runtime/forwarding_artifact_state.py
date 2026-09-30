#!/usr/bin/env python3
"""Restore the durable project-forwarding ledger from the runtime artifact."""
from __future__ import annotations
import argparse,io,json,os,time,urllib.request,zipfile
from pathlib import Path
from runtime.artifact_http import open_url
from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from runtime.artifact_state import validate_runtime_artifact_bundle
from runtime.project_forwarding import validate_state

ARTIFACT_NAME="portfolio-runtime-state"
class RestoreError(RuntimeError): pass

def _only_legacy_runtime_artifacts(data:dict,downloaded:dict[str,bytes])->bool:
    candidates=[
      item for item in data.get("artifacts",[])
      if not item.get("expired")
      and str((item.get("workflow_run") or {}).get("id"))!=str(os.environ.get("GITHUB_RUN_ID"))
      and (os.environ.get("GITHUB_REF_NAME") is None
           or (item.get("workflow_run") or {}).get("head_branch")==os.environ.get("GITHUB_REF_NAME"))
    ]
    candidates.sort(key=lambda item:(item.get("created_at",""),item.get("id",0)),reverse=True)
    candidates=candidates[:5]
    if not candidates:
        return False
    for item in candidates:
        url=item.get("archive_download_url")
        raw=downloaded.get(url) if isinstance(url,str) else None
        if raw is None:
            return False
        try:
            validate_runtime_artifact_bundle(raw,max_archive_bytes=5_242_880,max_member_bytes=5_242_880)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if any(info.filename=="project_forwarding_state.json" for info in archive.infolist()):
                    return False
        except (InvalidStateArtifact,zipfile.BadZipFile):
            return False
    return True

def _write_no_prior_metadata(path:Path|None)->None:
    if path is None:
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({
      "schema_version":"1.0.0","restore_status":"NO_PRIOR_FORWARDING_STATE",
      "artifact_id":None,"artifact_name":None,"artifact_created_at":None,
      "artifact_expires_at":None,"source_run_id":None,"source_head_sha":None,
    },sort_keys=True)+"\n",encoding="utf-8")

def restore(output:Path,metadata_output:Path|None=None)->str:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repo=os.environ.get("GITHUB_REPOSITORY"); run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo: return "NO_ACTIONS_CONTEXT"
    used=0; downloaded={}
    def get(url:str)->bytes:
        nonlocal used
        if url in downloaded:
            return downloaded[url]
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
    try:
        return restore_latest_valid_state(
          data,current_run=run,expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
          download=get,output=output,member_name="project_forwarding_state.json",
          expected_state_id="portfolio-project-forwarding-state",max_archive_bytes=5_242_880,
          max_state_bytes=1_048_576,validator=validate_state,metadata_output=metadata_output)
    except InvalidStateArtifact as exc:
        if str(exc)!="no valid prior state artifact found" or not _only_legacy_runtime_artifacts(data,downloaded):
            raise
        _write_no_prior_metadata(metadata_output)
        return "NO_PRIOR_FORWARDING_STATE"

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",required=True);ap.add_argument("--metadata-output",default=None);a=ap.parse_args()
    print(restore(Path(a.output),None if a.metadata_output is None else Path(a.metadata_output)))
if __name__=="__main__": main()
