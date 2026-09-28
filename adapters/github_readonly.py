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
GITHUB_COMPARE_COMMIT_CAP = 250

def _require(ok: bool, message: str) -> None:
    if not ok:
        raise AdapterError(message)

def _canonical_hash(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def _exact_sha(value: Any, message: str) -> str:
    _require(isinstance(value,str) and SHA.fullmatch(value) is not None, message)
    return value

def _repo_path(value: Any, message: str) -> str:
    _require(isinstance(value,str) and value, message)
    _require(not value.startswith("/") and "\\" not in value, message)
    _require(not any(ord(char)<32 or ord(char)==127 for char in value), message)
    _require(all(part not in {"",".",".."} for part in value.split("/")), message)
    return value

def _nonnegative_int(value: Any, message: str) -> int:
    _require(isinstance(value,int) and not isinstance(value,bool) and value>=0, message)
    return value

@dataclass(frozen=True)
class GitHubReadOnlyClient:
    token: str | None = None

    def get_json(self, url: str, *, timeout: float=20) -> dict[str, Any]:
        _require(url.startswith("https://api.github.com/"), "only GitHub API GET endpoints are allowed")
        headers={
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"portfolio-brain-readonly-adapter/1.0",
        }
        if self.token:
            headers["Authorization"]=f"Bearer {self.token}"
        request=urllib.request.Request(url,headers=headers,method="GET")
        _require(timeout>0, "GitHub GET timeout must be positive")
        with urllib.request.urlopen(request,timeout=min(timeout,20)) as response:
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
    return _exact_sha(cursor.get("cursor_sha"), "cursor requires an exact lowercase SHA")

def _tree_snapshot(adapter: dict[str,Any], commit_sha: str, fetch_json: FetchJSON) -> tuple[str,dict[str,dict[str,str]]]:
    """Return a complete non-directory Git tree snapshot bound to an exact commit."""
    api=_repo_api(adapter["repository_full_name"])
    commit=fetch_json(f"{api}/git/commits/{commit_sha}")
    _require(
        _exact_sha(commit.get("sha"), "GitHub git-commit response missing exact lowercase SHA")==commit_sha,
        "GitHub git-commit response is not bound to the requested SHA",
    )
    tree=commit.get("tree")
    _require(isinstance(tree,dict), "GitHub git-commit response missing tree")
    tree_sha=_exact_sha(tree.get("sha"), "GitHub git-commit tree is invalid")
    payload=fetch_json(f"{api}/git/trees/{tree_sha}?recursive=1")
    _require(payload.get("truncated") is False, "GitHub recursive tree response is truncated")
    _require(
        _exact_sha(payload.get("sha"), "GitHub recursive tree response missing exact tree SHA")==tree_sha,
        "GitHub recursive tree response is not bound to the requested tree",
    )
    raw=payload.get("tree")
    _require(isinstance(raw,list), "GitHub recursive tree response missing tree entries")
    files: dict[str,dict[str,str]]={}
    for item in raw:
        _require(isinstance(item,dict), "GitHub recursive tree entry must be an object")
        path=_repo_path(item.get("path"), "GitHub recursive tree entry has unsafe or missing path")
        kind=item.get("type")
        _require(kind in {"tree","blob","commit"}, "GitHub recursive tree entry has unsupported type")
        mode=item.get("mode")
        _require(isinstance(mode,str) and mode, "GitHub recursive tree entry has invalid mode")
        sha=_exact_sha(item.get("sha"), "GitHub recursive tree entry has invalid SHA")
        if kind=="tree":
            continue
        _require(path not in files, "GitHub recursive tree contains duplicate file paths")
        files[path]={"type":kind,"mode":mode,"sha":sha}
    return tree_sha,files

def _complete_tree_delta(adapter: dict[str,Any], base_sha: str, head_sha: str, fetch_json: FetchJSON) -> dict[str,Any]:
    """Prove a complete path-level delta when GitHub's compare file list hits its 300-file ceiling."""
    base_tree_sha,base_files=_tree_snapshot(adapter,base_sha,fetch_json)
    head_tree_sha,head_files=_tree_snapshot(adapter,head_sha,fetch_json)
    changes=[]; counts={"added":0,"removed":0,"modified":0}
    for path in sorted(set(base_files) | set(head_files)):
        before=base_files.get(path); after=head_files.get(path)
        if before==after:
            continue
        if before is None:
            status="added"
        elif after is None:
            status="removed"
        else:
            status="modified"
        counts[status]+=1
        changes.append({"path":path,"status":status,"before":before,"after":after})
    return {
        "comparison_method":"TREE_DELTA_FALLBACK",
        "files_complete":True,
        "files_materialized":False,
        "changed_file_count":len(changes),
        "file_change_counts":counts,
        "file_manifest_hash":_canonical_hash(changes),
        "tree_proof":{"base_tree_sha":base_tree_sha,"head_tree_sha":head_tree_sha},
        "files":[],
    }

def resolve_head(adapter: dict[str,Any], fetch_json: FetchJSON) -> str:
    ref=_source_ref(adapter)
    payload=fetch_json(f"{_repo_api(adapter['repository_full_name'])}/commits/{urllib.parse.quote(ref,safe='')}")
    return _exact_sha(payload.get("sha"), "GitHub commit response missing exact lowercase SHA")

def compare_range(adapter: dict[str,Any], base_sha: str, head_sha: str, fetch_json: FetchJSON) -> dict[str,Any]:
    _require(SHA.fullmatch(base_sha) is not None and SHA.fullmatch(head_sha) is not None, "compare requires exact lowercase SHAs")
    url=f"{_repo_api(adapter['repository_full_name'])}/compare/{base_sha}...{head_sha}"
    payload=fetch_json(url)
    status=payload.get("status")
    ahead_by=_nonnegative_int(payload.get("ahead_by"), "GitHub compare ahead_by is invalid")
    behind_by=_nonnegative_int(payload.get("behind_by"), "GitHub compare behind_by is invalid")
    total_commits=_nonnegative_int(payload.get("total_commits"), "GitHub compare total_commits is invalid")
    raw_files=payload.get("files")
    raw_commits=payload.get("commits")
    base_commit=payload.get("base_commit")
    merge_base_commit=payload.get("merge_base_commit")
    _require(status=="ahead", f"source history is not a fast-forward: {status}")
    _require(ahead_by>0, "fast-forward compare requires positive ahead_by")
    _require(behind_by==0, "fast-forward compare cannot be behind the cursor")
    _require(total_commits==ahead_by, "GitHub compare commit count is incomplete or inconsistent")
    _require(isinstance(base_commit,dict) and _exact_sha(base_commit.get("sha"), "GitHub compare base commit is invalid")==base_sha,
             "GitHub compare response is not bound to the requested base SHA")
    _require(isinstance(merge_base_commit,dict) and _exact_sha(merge_base_commit.get("sha"), "GitHub compare merge base is invalid")==base_sha,
             "GitHub compare is not a linear fast-forward from the requested base SHA")
    _require(isinstance(raw_commits,list), "GitHub compare response missing commits")
    _require(len(raw_commits)<GITHUB_COMPARE_COMMIT_CAP, "GitHub compare commit list reached the 250-commit completeness boundary")
    _require(len(raw_commits)==total_commits, "GitHub compare commit list is incomplete or inconsistent")
    commit_shas=[_exact_sha(item.get("sha") if isinstance(item,dict) else None,
                            "GitHub compare commit is missing an exact lowercase SHA") for item in raw_commits]
    _require(len(set(commit_shas))==len(commit_shas), "GitHub compare commit list contains duplicates")
    _require(commit_shas and commit_shas[-1]==head_sha,
             "GitHub compare response is not bound to the requested head SHA")
    _require(isinstance(raw_files,list), "GitHub compare response missing changed files")
    _require(len(raw_files)<=GITHUB_COMPARE_FILE_CAP, "GitHub compare file list exceeded the 300-file API boundary")
    if len(raw_files)==GITHUB_COMPARE_FILE_CAP:
        compact=_complete_tree_delta(adapter,base_sha,head_sha,fetch_json)
        _require(
            compact["changed_file_count"]>=GITHUB_COMPARE_FILE_CAP,
            "complete tree delta is inconsistent with the GitHub compare boundary",
        )
        return {
            "compare_status":status,
            "ahead_by":ahead_by,
            "behind_by":behind_by,
            "total_commits":total_commits,
        } | compact
    files=[]; seen_paths=set()
    for item in raw_files:
        _require(isinstance(item,dict), "GitHub compare file entry must be an object")
        path=_repo_path(item.get("filename"), "GitHub compare file has unsafe or missing path")
        file_status=item.get("status")
        _require(file_status in {"added","removed","modified","renamed","copied","changed","unchanged"}, "GitHub compare file has unsupported status")
        _require(path not in seen_paths, "GitHub compare file list contains duplicate paths")
        seen_paths.add(path)
        previous_path=item.get("previous_filename")
        if previous_path is not None:
            previous_path=_repo_path(previous_path, "GitHub compare file has unsafe previous path")
        if file_status=="renamed":
            _require(previous_path is not None and previous_path!=path, "renamed file requires a distinct previous path")
        additions=_nonnegative_int(item.get("additions"), "GitHub compare file additions are invalid")
        deletions=_nonnegative_int(item.get("deletions"), "GitHub compare file deletions are invalid")
        changes=_nonnegative_int(item.get("changes"), "GitHub compare file changes are invalid")
        _require(changes==additions+deletions, "GitHub compare file change counts are inconsistent")
        files.append({
            "path":path,
            "previous_path":previous_path,
            "status":file_status,
            "additions":additions,
            "deletions":deletions,
            "changes":changes,
        })
    return {
        "compare_status":status,
        "ahead_by":ahead_by,
        "behind_by":behind_by,
        "total_commits":total_commits,
        "comparison_method":"GITHUB_COMPARE",
        "files_complete":True,
        "files_materialized":True,
        "changed_file_count":len(files),
        "file_manifest_hash":_canonical_hash(files),
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
    sha=_exact_sha(receipt.get("current_sha"), "cursor advancement requires exact lowercase current SHA")
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
