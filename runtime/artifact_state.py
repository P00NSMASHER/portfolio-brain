#!/usr/bin/env python3
"""Restore newest sanitized Step 8 runtime-state artifact from GitHub Actions."""
from __future__ import annotations
import argparse, io, json, os, time, urllib.request, zipfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
import shutil
from pathlib import Path
from runtime.artifact_http import open_url
from runtime.artifact_restore import restore_latest_valid_state
from runtime.artifact_restore import InvalidStateArtifact
from runtime.provider_health import validate_provider_health
from runtime.state import validate_cycle_receipt, validate_state

ROOT=Path(__file__).resolve().parents[1]

class ArtifactRestoreError(RuntimeError): pass

def _single_json_member(archive:zipfile.ZipFile,name:str,*,max_bytes:int)->dict:
    matches=[info for info in archive.infolist() if info.filename==name and not info.is_dir()]
    if len(matches)!=1:
        raise InvalidStateArtifact(f"runtime artifact must contain exactly one {name}")
    info=matches[0]
    if info.file_size>max_bytes:
        raise InvalidStateArtifact(f"runtime artifact {name} exceeds byte budget")
    try:
        raw=archive.read(info)
        if len(raw)!=info.file_size:
            raise InvalidStateArtifact(f"runtime artifact {name} size mismatch")
        value=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError,RuntimeError,OSError) as exc:
        raise InvalidStateArtifact(f"runtime artifact {name} is invalid JSON") from exc
    if not isinstance(value,dict):
        raise InvalidStateArtifact(f"runtime artifact {name} must be an object")
    return value

def validate_runtime_artifact_bundle(raw:bytes,*,max_archive_bytes:int,max_member_bytes:int)->None:
    if len(raw)>max_archive_bytes:
        raise InvalidStateArtifact("runtime artifact archive exceeds byte budget")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            state=_single_json_member(archive,"runtime_state.json",max_bytes=max_member_bytes)
            receipt=_single_json_member(archive,"cycle_receipt.json",max_bytes=max_member_bytes)
    except zipfile.BadZipFile as exc:
        raise InvalidStateArtifact("runtime artifact is not a readable zip archive") from exc
    try:
        validate_state(state)
        validate_cycle_receipt(receipt,allow_disabled=True)
    except Exception as exc:
        raise InvalidStateArtifact(f"runtime artifact state/receipt validation failed: {exc}") from exc
    if receipt["status"]=="PASS":
        if not state["recent_cycles"]:
            raise InvalidStateArtifact("runtime artifact PASS receipt has no durable cycle history")
        last=state["recent_cycles"][-1]
        expected={
          "cycle_id":receipt["cycle_id"],
          "mode":receipt["mode"],
          "finished_at":receipt["finished_at"],
          "status":"PASS",
          "receipt_hash":receipt["receipt_hash"],
        }
        if last!=expected:
            raise InvalidStateArtifact("runtime artifact state/receipt binding mismatch")
        if state["last_cycle_id"]!=receipt["cycle_id"] or state["updated_at"]!=receipt["finished_at"]:
            raise InvalidStateArtifact("runtime artifact latest-cycle projection mismatch")
    else:
        if receipt["cycle_id"]!="disabled":
            raise InvalidStateArtifact("runtime disabled artifact receipt identity mismatch")

def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

def _runtime_state_subsumes(
    winner_state: dict,
    winner_receipt: dict,
    other_state: dict,
) -> bool:
    if winner_state["sequence"] != other_state["sequence"]:
        return False
    if winner_state["recent_cycles"][:-1] != other_state["recent_cycles"][:-1]:
        return False
    if _utc(winner_receipt["finished_at"]) <= _utc(other_state["updated_at"]):
        return False
    observations = {
        row.get("repository_id"): row
        for row in winner_receipt.get("observations", [])
        if isinstance(row, dict)
    }
    if set(winner_state["repositories"]) != set(other_state["repositories"]):
        return False
    for rid, other in other_state["repositories"].items():
        current = winner_state["repositories"][rid]
        if current["source_ref"] != other["source_ref"] or current["status"] != other["status"]:
            return False
        if current["cursor_sha"] != other["cursor_sha"]:
            observation = observations.get(rid)
            if not observation:
                return False
            if observation.get("status") != "CHANGED":
                return False
            if observation.get("source_ref") != other["source_ref"]:
                return False
            if observation.get("prior_sha") != other["cursor_sha"]:
                return False
            if observation.get("current_sha") != current["cursor_sha"]:
                return False
        if other["observed_at"] is not None:
            if current["observed_at"] is None or _utc(current["observed_at"]) < _utc(other["observed_at"]):
                return False
    return True

def _resolve_dominant_runtime_fork(
    data: dict,
    *,
    current_run: str | None,
    expected_head_branch: str | None,
    download,
    max_archive_bytes: int,
    max_member_bytes: int,
    max_candidates: int = 5,
) -> tuple[dict, list[int]]:
    candidates = [
        item
        for item in data.get("artifacts", [])
        if not item.get("expired")
        and str((item.get("workflow_run") or {}).get("id")) != str(current_run)
        and (
            expected_head_branch is None
            or (item.get("workflow_run") or {}).get("head_branch") == expected_head_branch
        )
    ]
    candidates.sort(key=lambda item: (item.get("created_at", ""), item.get("id", 0)), reverse=True)
    valid = []
    for item in candidates[:max_candidates]:
        url = item.get("archive_download_url")
        if not isinstance(url, str) or not url:
            continue
        try:
            raw = download(url)
            validate_runtime_artifact_bundle(
                raw,
                max_archive_bytes=max_archive_bytes,
                max_member_bytes=max_member_bytes,
            )
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                state = _single_json_member(
                    archive, "runtime_state.json", max_bytes=max_member_bytes
                )
                receipt = _single_json_member(
                    archive, "cycle_receipt.json", max_bytes=max_member_bytes
                )
        except Exception:
            continue
        valid.append((item, state, receipt))
    if len(valid) < 2:
        raise InvalidStateArtifact("runtime concurrent fork recovery requires two valid candidates")
    highest_sequence = max(state["sequence"] for _, state, _ in valid)
    highest = [entry for entry in valid if entry[1]["sequence"] == highest_sequence]
    if len(highest) < 2:
        raise InvalidStateArtifact("runtime concurrent fork recovery found no highest-sequence fork")
    winners = []
    for entry in highest:
        item, state, receipt = entry
        if receipt.get("status") != "PASS" or receipt.get("mode") != "sync":
            continue
        if all(
            other is entry or _runtime_state_subsumes(state, receipt, other[1])
            for other in highest
        ):
            winners.append(entry)
    if len(winners) != 1:
        raise InvalidStateArtifact("runtime concurrent fork has no unique dominant sync state")
    winner = winners[0][0]
    return {"artifacts": [winner]}, [int(entry[0].get("id")) for entry in highest]

def policy():
    return json.loads((ROOT/"runtime"/"RUNTIME_POLICY.json").read_text())

def _retryable_fetch_error(exc: Exception)->bool:
    if isinstance(exc,HTTPError):
        return exc.code in {408,429} or 500<=exc.code<600
    return isinstance(exc,(URLError,TimeoutError,ConnectionError))

class BudgetedHTTP:
    def __init__(self, token: str, *, max_requests: int, retries: int, backoff: float,
                 deadline: float|None=None, clock=time.monotonic, sleep=time.sleep):
        self.token=token; self.max_requests=max_requests; self.retries=retries; self.backoff=backoff; self.requests=0
        self.deadline=deadline; self.clock=clock; self.sleep=sleep
    def _timeout(self)->float:
        if self.deadline is None:return 20
        remaining=self.deadline-self.clock()
        if remaining<=0:raise ArtifactRestoreError("artifact restore time budget exceeded")
        return min(20,remaining)
    def _request(self,url: str)->bytes:
        last=None
        for attempt in range(self.retries+1):
            timeout=self._timeout()
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
                with open_url(req,timeout=timeout) as response:
                    body=response.read()
                self._timeout()
                return body
            except Exception as exc:
                if isinstance(exc,ArtifactRestoreError):raise
                last=exc
                if attempt>=self.retries or not _retryable_fetch_error(exc):break
                delay=self.backoff*(attempt+1)
                if self.deadline is not None and self.clock()+delay>=self.deadline:
                    raise ArtifactRestoreError("artifact restore time budget exceeded") from exc
                self.sleep(delay)
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
                      retries=budgets["retry_limit"],backoff=budgets["retry_backoff_seconds"],
                      deadline=time.monotonic()+budgets["max_state_restore_seconds"])
    url=f"https://api.github.com/repos/{repository}/actions/artifacts?name={p['state_persistence']['artifact_name']}&per_page=100"
    data=http.json(url)
    archive_cache:dict[str,bytes]={}
    def download(url:str)->bytes:
        if url not in archive_cache:
            raw=http.bytes(url)
            validate_runtime_artifact_bundle(
              raw,
              max_archive_bytes=budgets["max_output_bytes"],
              max_member_bytes=budgets["max_output_bytes"],
            )
            archive_cache[url]=raw
        return archive_cache[url]
    try:
        status=restore_latest_valid_state(
            data,current_run=current_run,expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
            download=download,output=output,
            member_name="runtime_state.json",expected_state_id="portfolio-runtime-state",
            max_archive_bytes=budgets["max_output_bytes"],max_state_bytes=budgets["max_output_bytes"],
            validator=validate_state,metadata_output=metadata_output,
        )
    except InvalidStateArtifact as exc:
        if str(exc) != "conflicting state artifacts at highest sequence":
            raise
        recovered, fork_ids = _resolve_dominant_runtime_fork(
            data,
            current_run=current_run,
            expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
            download=download,
            max_archive_bytes=budgets["max_output_bytes"],
            max_member_bytes=budgets["max_output_bytes"],
        )
        restore_latest_valid_state(
            recovered,current_run=current_run,expected_head_branch=os.environ.get("GITHUB_REF_NAME"),
            download=download,output=output,
            member_name="runtime_state.json",expected_state_id="portfolio-runtime-state",
            max_archive_bytes=budgets["max_output_bytes"],max_state_bytes=budgets["max_output_bytes"],
            validator=validate_state,metadata_output=metadata_output,
        )
        status="RESTORED_DOMINANT_SYNC_AFTER_CONCURRENT_FORK_" + "_".join(map(str, fork_ids))
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
