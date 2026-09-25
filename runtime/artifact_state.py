#!/usr/bin/env python3
"""Restore newest sanitized Step 8 runtime-state artifact from GitHub Actions."""
from __future__ import annotations
import argparse, io, json, os, time, urllib.request, zipfile
from pathlib import Path

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
                with urllib.request.urlopen(req,timeout=20) as response:
                    return response.read()
            except Exception as exc:
                last=exc
                if attempt<self.retries: time.sleep(self.backoff*(attempt+1))
        raise ArtifactRestoreError(f"artifact API read failed after bounded retries: {last}")
    def json(self,url: str)->dict:
        return json.loads(self._request(url).decode("utf-8"))
    def bytes(self,url: str)->bytes:
        return self._request(url)

def restore(*, output: Path)->str:
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
    candidates=[]
    for item in data.get("artifacts",[]):
        if item.get("expired"): continue
        wr=item.get("workflow_run") or {}
        if current_run and str(wr.get("id"))==str(current_run): continue
        candidates.append(item)
    if not candidates:
        return "NO_PRIOR_ARTIFACT"
    candidates.sort(key=lambda x:x.get("created_at",""),reverse=True)
    raw=http.bytes(candidates[0]["archive_download_url"])
    if len(raw)>budgets["max_output_bytes"]:
        raise ArtifactRestoreError("runtime-state artifact exceeds byte budget")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names=zf.namelist()
        if "runtime_state.json" not in names:
            raise ArtifactRestoreError("runtime-state artifact missing runtime_state.json")
        info=zf.getinfo("runtime_state.json")
        if info.file_size>budgets["max_output_bytes"]:
            raise ArtifactRestoreError("extracted runtime state exceeds byte budget")
        payload=zf.read(info)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(payload)
    return "RESTORED"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",required=True)
    args=ap.parse_args()
    print(restore(output=Path(args.output)))
if __name__=="__main__": main()
