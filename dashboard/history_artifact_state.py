#!/usr/bin/env python3
"""Restore sanitized command-center history, losslessly resolving native forked observations."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from dashboard.history_state import (
    ARTIFACT_NAME,
    canon,
    history_observation,
    replay_history_observation,
    validate_state,
)
from runtime.artifact_http import open_url
from runtime.artifact_restore import restore_latest_valid_state
from runtime.artifact_restore import InvalidStateArtifact, _atomic_write

MAX_BYTES=5_242_880


class RestoreError(RuntimeError):pass


def _utc(value:str)->datetime:
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed.tzinfo is None:raise InvalidStateArtifact("history timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def _state_from_archive(raw:bytes)->dict:
    if len(raw)>MAX_BYTES:raise InvalidStateArtifact("history artifact exceeds byte budget")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            matches=[info for info in archive.infolist() if info.filename=="history_state.json" and not info.is_dir()]
            if len(matches)!=1 or matches[0].file_size>MAX_BYTES:
                raise InvalidStateArtifact("history artifact member invalid")
            body=archive.read(matches[0])
    except (zipfile.BadZipFile,RuntimeError,OSError) as exc:
        raise InvalidStateArtifact("history artifact unreadable") from exc
    try:
        state=json.loads(body.decode("utf-8"));validate_state(state)
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc:
        raise InvalidStateArtifact("history artifact state invalid") from exc
    return state


def _state_hash(state:dict)->str:
    return "sha256:"+hashlib.sha256(canon(state).encode()).hexdigest()


def _valid_history_candidates(data:dict,*,current_run:str|None,expected_head_branch:str|None,download,max_candidates:int=5):
    candidates=[
      item for item in data.get("artifacts",[])
      if not item.get("expired")
      and str((item.get("workflow_run") or {}).get("id"))!=str(current_run)
      and (expected_head_branch is None or (item.get("workflow_run") or {}).get("head_branch")==expected_head_branch)
    ]
    candidates.sort(key=lambda item:(item.get("created_at",""),item.get("id",0)),reverse=True)
    valid=[]
    for item in candidates[:max_candidates]:
        url=item.get("archive_download_url")
        if not isinstance(url,str) or not url:continue
        try:
            raw=download(url)
            expected=item.get("digest")
            actual="sha256:"+hashlib.sha256(raw).hexdigest()
            if not isinstance(expected,str) or expected!=actual:
                raise InvalidStateArtifact("history artifact digest mismatch")
            state=_state_from_archive(raw)
        except Exception:
            continue
        valid.append((item,state))
    return valid


def _merge_history_fork(data:dict,*,current_run:str|None,expected_head_branch:str|None,download,max_candidates:int=5):
    """Replay every exact native observation from one unique common predecessor."""
    valid=_valid_history_candidates(
      data,current_run=current_run,expected_head_branch=expected_head_branch,
      download=download,max_candidates=max_candidates,
    )
    if len(valid)<3:raise InvalidStateArtifact("history fork merge requires exact predecessor evidence")
    highest_sequence=max(state["sequence"] for _,state in valid)
    highest=[entry for entry in valid if entry[1]["sequence"]==highest_sequence]
    if len(highest)<2:raise InvalidStateArtifact("history fork merge found no highest-sequence fork")

    predecessor_entries=[entry for entry in valid if entry[1]["sequence"]==highest_sequence-1]
    predecessor_states={}
    for item,state in predecessor_entries:
        predecessor_states.setdefault(canon(state),[]).append((item,state))
    if len(predecessor_states)!=1:
        raise InvalidStateArtifact("history fork has no unique exact predecessor")
    predecessor_group=next(iter(predecessor_states.values()))
    base=predecessor_group[0][1]

    observations={}
    slots={}
    for _item,state in highest:
        point=history_observation(base,state)
        if point is None:raise InvalidStateArtifact("history fork branch is not exact-replayable")
        point_bytes=canon(point)
        slot=_utc(point["observed_at"])
        prior=slots.get(slot)
        if prior is not None and prior!=point_bytes:
            raise InvalidStateArtifact("history fork has ambiguous equal-time observations")
        slots[slot]=point_bytes
        observations[point_bytes]=point
    if len(observations)<2:
        raise InvalidStateArtifact("history fork merge has no distinct concurrent observations")

    merged=json.loads(json.dumps(base))
    for key in sorted(observations,key=lambda value:(_utc(observations[value]["observed_at"]),value)):
        merged=replay_history_observation(merged,observations[key])
    validate_state(merged)

    sources=[entry[0] for entry in highest]
    sources.extend(item for item,_state in predecessor_group)
    deduped={int(item["id"]):item for item in sources}
    fork_ids=sorted((int(item["id"]) for item,_state in highest),reverse=True)
    return merged,[deduped[key] for key in sorted(deduped,reverse=True)],fork_ids,len(valid)


def _write_merged_fork(output:Path,metadata_output:Path|None,merged:dict,sources:list[dict],fork_ids:list[int],inspected:int)->str:
    status="RESTORED_MERGED_HISTORY_FORK_"+"_".join(map(str,fork_ids))
    _atomic_write(output,canon(merged).encode()+b"\n")
    if metadata_output is not None:
        metadata={
          "schema_version":"1.1.0","restore_status":status,
          "artifact_id":None,"artifact_name":ARTIFACT_NAME,
          "artifact_created_at":max((item.get("created_at") or "") for item in sources),
          "artifact_expires_at":min((item.get("expires_at") or "") for item in sources),
          "source_run_id":None,"source_head_sha":None,
          "source_sequence":merged["sequence"],"source_state_hash":_state_hash(merged),
          "source_artifact_ids":[int(item["id"]) for item in sources],
          "source_run_ids":[int((item.get("workflow_run") or {})["id"]) for item in sources],
          "source_head_shas":[str((item.get("workflow_run") or {}).get("head_sha") or "") for item in sources],
          "source_artifact_digests":[item.get("digest") for item in sources],
          "fork_artifact_ids":fork_ids,"candidates_inspected":inspected,
        }
        _atomic_write(metadata_output,(json.dumps(metadata,sort_keys=True,separators=(",",":"))+"\n").encode())
    return status


def restore(output:Path,metadata_output:Path|None=None)->str:
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    repo=os.environ.get("GITHUB_REPOSITORY");run=os.environ.get("GITHUB_RUN_ID")
    if not token or not repo:return "NO_ACTIONS_CONTEXT"
    used=0
    def get(url:str)->bytes:
        nonlocal used
        last=None
        for attempt in range(3):
            if used>=6:raise RestoreError("history artifact request budget exceeded")
            used+=1
            req=urllib.request.Request(url,headers={
              "Accept":"application/vnd.github+json","Authorization":f"Bearer {token}",
              "X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-history/1.0"
            },method="GET")
            try:
                with open_url(req,timeout=20) as resp:return resp.read()
            except Exception as exc:
                last=exc
                if attempt<2:time.sleep(attempt+1)
        raise RestoreError(str(last))
    data=json.loads(get(f"https://api.github.com/repos/{repo}/actions/artifacts?name={ARTIFACT_NAME}&per_page=100").decode())
    cache={}
    def download(url:str)->bytes:
        if url not in cache:cache[url]=get(url)
        return cache[url]
    try:
        return restore_latest_valid_state(
          data,current_run=run,expected_head_branch=os.environ.get("GITHUB_REF_NAME"),download=download,output=output,
          member_name="history_state.json",expected_state_id="portfolio-command-center-history",
          max_archive_bytes=MAX_BYTES,max_state_bytes=MAX_BYTES,validator=validate_state,
          metadata_output=metadata_output,
        )
    except InvalidStateArtifact as exc:
        if str(exc)!="conflicting state artifacts at highest sequence":raise
        merged,sources,fork_ids,inspected=_merge_history_fork(
          data,current_run=run,expected_head_branch=os.environ.get("GITHUB_REF_NAME"),download=download,
        )
        return _write_merged_fork(output,metadata_output,merged,sources,fork_ids,inspected)


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",required=True);ap.add_argument("--metadata-output",default=None)
    a=ap.parse_args();print(restore(Path(a.output),None if a.metadata_output is None else Path(a.metadata_output)))


if __name__=="__main__":main()
