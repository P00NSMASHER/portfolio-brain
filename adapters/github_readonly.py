#!/usr/bin/env python3
"""Read-only GitHub repository adapter with exact-SHA cursors.

The adapter performs GET requests only. It never writes to a downstream repository.
A changed source is compared from the persisted cursor SHA to the current configured
ref; an unchanged SHA is skipped without a compare/content reread.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
import re

FetchJSON = Callable[[str], dict[str, Any]]

class AdapterError(ValueError):
    pass

SHA = re.compile(r"^[0-9a-f]{40}$")
GITHUB_COMPARE_FILE_CAP = 300

def _require(ok: bool, message: str) -> None:
    if not ok:
        raise AdapterError(message)

def _canonical_hash(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return "sha256:"+hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class GitHubReadOnlyClient:
    token: str | None = None

    def get_json(self, url: str) -> dict[str, Any]:
        _require(url.startswith("https://api.github.com/"), "only GitHub API GET endpoints are allowed")
        headers={
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"portfolio-brain-readonly-adapter/1.0",
        }
        if self.token:
            headers["Authorization"]=f"Bearer {self.token}"
        request=urllib.request.Request(url,headers=headers,method="GET")
        with urllib.request.urlopen(request,timeout=20) as response:
            _require(response.status==200, f"GitHub GET failed: HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))

def _repo_api(full_name: str) -> str:
    owner,repo=full_name.split("/",1)
    return f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"

def _source_ref(adapter: dict[str,Any]) -> str:
    ref=adapter["source_ref_policy"]["ref"]
    _require(isinstance(ref,str) and ref, "adapter source ref must be explicit at execution time")
    return ref

def _validate_cursor(cursor: dict[str,Any] | None, ref: str) -> str | None:
    if cursor is None:
        return None
    _require(isinstance(cursor,dict), "cursor must be an object")
    _require(cursor.get("source_ref")==ref, "cursor source_ref does not match configured adapter ref")
    sha=cursor.get("cursor_sha")
    _require(isinstance(sha,str) and SHA.fullmatch(sha) is not None, "cursor requires an exact lowercase SHA")
    return sha

def resolve_head(adapter: dict[str,Any], fetch_json: FetchJSON) -> str:
    ref=_source_ref(adapter)
    payload=fetch_json(f"{_repo_api(adapter['repository_full_name'])}/commits/{urllib.parse.quote(ref,safe='')}")
    sha=payload.get("sha")
    _require(isinstance(sha,str) and len(sha)==40, "GitHub commit response missing exact SHA")
    return sha

def compare_range(adapter: dict[str,Any], base_sha: str, head_sha: str, fetch_json: FetchJSON) -> dict[str,Any]:
    _require(SHA.fullmatch(base_sha) is not None and SHA.fullmatch(head_sha) is not None, "compare requires exact lowercase SHAs")
    url=f"{_repo_api(adapter['repository_full_name'])}/compare/{base_sha}...{head_sha}"
    payload=fetch_json(url)
    status=payload.get("status")
    ahead_by=payload.get("ahead_by")
    behind_by=payload.get("behind_by")
    total_commits=payload.get("total_commits")
    raw_files=payload.get("files")
    _require(status=="ahead", f"source history is not a fast-forward: {status}")
    _require(isinstance(ahead_by,int) and ahead_by>0, "fast-forward compare requires positive ahead_by")
    _require(behind_by==0, "fast-forward compare cannot be behind the cursor")
    _require(total_commits==ahead_by, "GitHub compare commit count is incomplete or inconsistent")
    _require(isinstance(raw_files,list), "GitHub compare response missing changed files")
    _require(len(raw_files)<GITHUB_COMPARE_FILE_CAP, "GitHub compare file list reached the 300-file completeness boundary")
    files=[]
    for item in raw_files:
        path=item.get("filename")
        file_status=item.get("status")
        _require(isinstance(path,str) and path, "GitHub compare file missing path")
        _require(file_status in {"added","removed","modified","renamed","copied","changed","unchanged"}, "GitHub compare file has unsupported status")
        files.append({
            "path":path,
            "previous_path":item.get("previous_filename"),
            "status":file_status,
            "additions":item.get("additions"),
            "deletions":item.get("deletions"),
            "changes":item.get("changes"),
        })
    return {
        "compare_status":status,
        "ahead_by":ahead_by,
        "behind_by":behind_by,
        "total_commits":total_commits,
        "files_complete":True,
        "files":files,
    }

def observe_repository(
    adapter: dict[str,Any],
    cursor: dict[str,Any] | None,
    *,
    fetch_json: FetchJSON,
    observed_at: str,
) -> dict[str,Any]:
    _require(adapter.get("authority_class")=="OBSERVE", "adapter must be OBSERVE-only")
    ref=_source_ref(adapter)
    prior=_validate_cursor(cursor,ref)
    if not adapter.get("enabled",False):
        _require(adapter.get("blocked_by"), "disabled adapter requires blocker")
        return {
            "schema_version":"1.0.0",
            "adapter_id":adapter["adapter_id"],
            "repository_id":adapter["repository_id"],
            "repository_full_name":adapter["repository_full_name"],
            "source_ref":ref,
            "observed_at":observed_at,
            "status":"BLOCKED",
            "blocked_by":adapter["blocked_by"],
            "prior_sha":prior,
            "current_sha":None,
            "compare":None,
            "network_reads":0,
            "receipt_hash":"",
        } | {"receipt_hash": _canonical_hash({
            "schema_version":"1.0.0","adapter_id":adapter["adapter_id"],
            "repository_id":adapter["repository_id"],"repository_full_name":adapter["repository_full_name"],
            "source_ref":ref,
            "observed_at":observed_at,"status":"BLOCKED","blocked_by":adapter["blocked_by"],
            "prior_sha":prior,"current_sha":None,
            "compare":None,"network_reads":0
        })}

    calls=0
    def counted(url: str) -> dict[str,Any]:
        nonlocal calls
        calls+=1
        return fetch_json(url)

    head=resolve_head(adapter,counted)
    if prior==head:
        body={
            "schema_version":"1.0.0","adapter_id":adapter["adapter_id"],
            "repository_id":adapter["repository_id"],"repository_full_name":adapter["repository_full_name"],
            "source_ref":ref,
            "observed_at":observed_at,"status":"UNCHANGED","blocked_by":None,
            "prior_sha":prior,"current_sha":head,"compare":None,"network_reads":calls
        }
    elif prior is None:
        body={
            "schema_version":"1.0.0","adapter_id":adapter["adapter_id"],
            "repository_id":adapter["repository_id"],"repository_full_name":adapter["repository_full_name"],
            "source_ref":ref,
            "observed_at":observed_at,"status":"INITIALIZED","blocked_by":None,
            "prior_sha":None,"current_sha":head,"compare":None,"network_reads":calls
        }
    else:
        delta=compare_range(adapter,prior,head,counted)
        body={
            "schema_version":"1.0.0","adapter_id":adapter["adapter_id"],
            "repository_id":adapter["repository_id"],"repository_full_name":adapter["repository_full_name"],
            "source_ref":ref,
            "observed_at":observed_at,"status":"CHANGED","blocked_by":None,
            "prior_sha":prior,"current_sha":head,"compare":delta,"network_reads":calls
        }
    return body | {"receipt_hash":_canonical_hash(body)}

def next_cursor(receipt: dict[str,Any], prior_cursor: dict[str,Any] | None) -> dict[str,Any] | None:
    status=receipt["status"]
    if status=="BLOCKED":
        return prior_cursor
    _require(status in {"UNCHANGED","INITIALIZED","CHANGED"}, "receipt status cannot advance cursor")
    sha=receipt.get("current_sha")
    _require(isinstance(sha,str) and len(sha)==40, "cursor advancement requires exact current SHA")
    ref=receipt.get("source_ref")
    _require(isinstance(ref,str) and ref, "cursor advancement requires source_ref provenance")
    return {
        "source_ref":ref,
        "cursor_sha":sha,
        "status":"CURRENT",
    }

def load_token() -> str | None:
    # Optional token supports private repositories later. This module never logs it.
    return os.environ.get("PORTFOLIO_GITHUB_TOKEN")
