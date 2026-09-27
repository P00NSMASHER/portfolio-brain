#!/usr/bin/env python3
"""Restore newest sanitized Step 8 runtime-state artifact from GitHub Actions."""
from __future__ import annotations
import argparse, json, os, time, urllib.request
import shutil
from pathlib import Path
from runtime.artifact_http import open_url
from runtime.artifact_restore import restore_latest_valid_state
from runtime.artifact_restore import InvalidStateArtifact
from runtime.provider_health import validate_provider_health
from runtime.state import validate_state

ROOT=Path(__file__).resolve().parents[1]

class ArtifactRestoreError(RuntimeError): pass

def policy():
    return json.loads((ROOT/"runtime"/"RUNTIME_POLICY.json").read_text())

class BudgetedHTTP:
    def __init__(self, token: str, *, max_requests: int, retries: int, backoff: float):
        self.token=token; self.max_requests=max_requests; self.retries=retries; self.backoff=backoff; self.requests=0
    def _request(self,url: str)->bytes:
        last=None
        for attempt in range(self.retries+1):
            if self.requests>=self.max_requests:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            self.requests+=1
            req=urllib.request.Request(url,headers={
              "Accept":"application/vnd.github+json",
              "Authorization":f"Bearer {self.token}",
              "X-GitHub-Api-Version":"2022-11-28",
              "User-Agent":"portfolio-brain-runtime/1.0",
            },method="GET")
            try:
                with open_url(req,timeout=20) as response:
                    return response.read()
            except Exception as exc:
                last=exc
                if attempt<self.retries: time.sleep(self.backoff*(attempt+1))
        raise ArtifactRestoreError(f"artifact API read failed after bounded retries: {last}")
    def json(self,url: str)->dict:
        return json.loads(self._request(url).decode("utf-8"))
    def bytes(self,url: str)->bytes:
        return self._request(url)

def _no_provider_metadata(path:Path|None)->None:
    if path is None:return
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({
      "schema_version":"1.0.0","restore_status":"NO_VALID_PROVIDER_HEALTH_ARTIFACT",
      "artifact_id":None,"artifact_name":None,"artifact_created_at":None,
      "artifact_expires_at":None,"source_run_id":None,"source_head_sha":None,
    },sort_keys=True)+"\n",encoding="utf-8")

def restore(*, output: Path, metadata_output: Path | None = None,
            provider_health_output:Path|None=None,
            provider_health_metadata_output:Path|None=None)->str:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repository=os.environ.get("GITHUB_REPOSITORY")
    current_run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repository:
        return "NO_ACTIONS_CONTEXT"
    p=policy(); budgets=p["budgets"]
    http=BudgetedHTTP(token,max_requests=min(6,budgets["max_api_requests_per_cycle"]),
                      retries=budgets["retry_limit"],backoff=budgets["retry_backoff_seconds"])
    url=f"https://api.github.com/repos/{repository}/actions/artifacts?name={p['state_persistence']['artifact_name']}&per_page=100"
    data=http.json(url)
    archive_cache:dict[str,bytes]={}
    def download(url:str)->bytes:
        if url not in archive_cache:
            archive_cache[url]=http.bytes(url)
        return archive_cache[url]
    status=restore_latest_valid_state(
        data,current_run=current_run,expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
        download=download,output=output,
        member_name="runtime_state.json",expected_state_id="portfolio-runtime-state",
        max_archive_bytes=budgets["max_output_bytes"],max_state_bytes=budgets["max_output_bytes"],
        validator=validate_state,metadata_output=metadata_output,
    )
    if provider_health_output is not None:
        try:
            restore_latest_valid_state(
                data,current_run=current_run,expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
                download=download,output=provider_health_output,
                member_name="provider_health.json",expected_state_id="portfolio-provider-readiness-state",
                max_archive_bytes=budgets["max_output_bytes"],max_state_bytes=budgets["max_output_bytes"],
                validator=validate_provider_health,metadata_output=provider_health_metadata_output,
            )
        except InvalidStateArtifact:
            _no_provider_metadata(provider_health_metadata_output)
        if not provider_health_output.exists():
            provider_health_output.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/"runtime"/"PROVIDER_HEALTH_SEED.json",provider_health_output)
    return status

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",required=True);ap.add_argument("--metadata-output",default=None)
    ap.add_argument("--provider-health-output",default=None)
    ap.add_argument("--provider-health-metadata-output",default=None)
    args=ap.parse_args()
    print(restore(
      output=Path(args.output),metadata_output=None if args.metadata_output is None else Path(args.metadata_output),
      provider_health_output=None if args.provider_health_output is None else Path(args.provider_health_output),
      provider_health_metadata_output=None if args.provider_health_metadata_output is None else Path(args.provider_health_metadata_output),
    ))
if __name__=="__main__": main()
