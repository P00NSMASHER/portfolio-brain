"""Bounded GitHub GET-only discovery. Content is data, never instructions.

Public scheduled reads may use the existing workflow token, but reject private
repository metadata before inspecting or persisting content.
Private discovery is explicit, locally persisted, token-accessible only, and has
no publication path. License classifications are preserved without filtering.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from brain.core import require, BrainError, digest, utcnow
from brain.intelligence import REPO, is_test_source_path

_GENERIC_PATH_TOKENS = {
    "api", "app", "code", "go", "index", "js", "lib", "library", "lua",
    "main", "mod", "module", "py", "rs", "source", "spec", "specs", "src",
    "test", "tests", "ts",
}

def _path_tokens(path):
    return {
        token for token in re.findall(r"[a-z0-9]+", path.lower())
        if len(token) > 1 and token not in _GENERIC_PATH_TOKENS
    }

def related_test_paths(source_path, rows):
    """Return only tests with path evidence linking them to this implementation.

    Repository-wide test presence is not implementation evidence. This conservative
    path association avoids awarding reuse-score credit for unrelated test suites.
    """
    source_tokens = _path_tokens(source_path)
    if not source_tokens:
        return []
    related = []
    for entry in rows:
        path = entry.get("path")
        if entry.get("type") != "blob" or not is_test_source_path(path):
            continue
        if source_tokens.intersection(_path_tokens(path)):
            related.append(path)
            if len(related) == 10:
                break
    return related

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BrainError("REDIRECT_REFUSED: source identity must remain api.github.com")

class GitHub:
    def __init__(self, *, private=False, transport=None):
        self.private=private
        self.token=os.environ.get("GITHUB_TOKEN", "")
        require(not private or self.token, "PRIVATE_ACCESS_UNAVAILABLE: explicit existing GITHUB_TOKEN required")
        self.transport=transport
        self.requests=0
        # Count optional search hits whose advertised branch was never created.
        # This is not a waiver for monitored repositories or nonempty sources.
        self.unavailable_discovery_branches=0
        self.opener=urllib.request.build_opener(NoRedirect())

    def get(self, path):
        require(path.startswith("/") and not path.startswith("//") and "://" not in path and ".." not in path.split("/"), "unsafe API path")
        for attempt in range(2):
            self.requests+=1
            require(self.requests <= 24, "REQUEST_BUDGET_EXHAUSTED")
            try:
                if self.transport:
                    return self.transport(path)
                headers={"Accept":"application/vnd.github+json","User-Agent":"PortfolioBrain-v2-readonly","X-GitHub-Api-Version":"2022-11-28"}
                if self.token:
                    headers["Authorization"]="Bearer "+self.token
                request=urllib.request.Request("https://api.github.com"+path, headers=headers, method="GET")
                with self.opener.open(request, timeout=10) as response:
                    raw=response.read(2_000_001)
                require(len(raw)<=2_000_000, "SOURCE_RESPONSE_TOO_LARGE")
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                if attempt==0 and exc.code in {429,502,503,504}:
                    retry=exc.headers.get("Retry-After","1")
                    require(retry.isdigit() and int(retry)<=2, "RATE_LIMIT: retry exceeds bounded budget")
                    time.sleep(int(retry))
                    continue
                raise BrainError(f'SOURCE_API_{exc.code}: GET failed; no cursor advanced') from None
            except (TimeoutError, OSError, json.JSONDecodeError) as exc:
                raise BrainError(f'SOURCE_READ_FAILED:{type(exc).__name__}; no cursor advanced') from None
        raise BrainError("SOURCE_RETRY_EXHAUSTED")

    def repository(self, repository):
        require(REPO.fullmatch(repository or ""), "repository invalid")
        meta=self.get("/repos/"+repository)
        require(meta.get("full_name", "").lower()==repository.lower(), "repository renamed/identity changed")
        require(type(meta.get("private")) is bool, "visibility unavailable")
        require(self.private or meta["private"] is False, "PRIVATE_INPUT_REFUSED_BY_PUBLIC_ADAPTER")
        branch=meta["default_branch"]
        head=self.get("/repos/"+repository+"/branches/"+urllib.parse.quote(branch,safe=""))
        sha=head["commit"]["sha"]
        return meta,branch,sha

    def observe(self, repository):
        meta,branch,sha=self.repository(repository)
        checks=self.get(f'/repos/{repository}/commits/{sha}/check-runs?per_page=100')
        total=checks.get('total_count')
        require(type(total) is int and 0<=total<=500 and type(checks.get('check_runs')) is list, 'CHECK_COVERAGE_UNAVAILABLE: malformed or over bounded500 history')
        items=list(checks['check_runs'])
        require(len(items)==min(total,100), 'CHECK_COVERAGE_TRUNCATED: incomplete first page')
        for page in range(2,(total+99)//100+1):
            batch=self.get(f'/repos/{repository}/commits/{sha}/check-runs?per_page=100&page={page}')
            require(batch.get('total_count')==total and type(batch.get('check_runs')) is list, 'CHECK_COVERAGE_CHANGED: do not claim complete changing history')
            items.extend(batch['check_runs'])
        require(len(items)==total,'CHECK_COVERAGE_TRUNCATED: incomplete delivery')
        if total>100:
            require(all(type(x.get('id')) is int for x in items) and len({x['id'] for x in items})==total, 'CHECK_COVERAGE_AMBIGUOUS: duplicate/missing paginated identities')
        rows=[{"name":x["name"],"status":x["status"],"conclusion":x.get("conclusion"),"head_sha":x["head_sha"],"url":x["html_url"]} for x in items]
        return {"repository":repository,"head_sha":sha,"default_branch":branch,"checks":rows,"open_issues":meta["open_issues_count"],"source_ref":f'https://github.com/{repository}/commit/{sha}'}, meta["private"]

    def discover(self, target, *, repository=None):
        self.unavailable_discovery_branches=0
        if repository:
            repos=[self.get("/repos/"+repository)]
        else:
            query=target["query"]+('' if self.private else ' is:public')
            response=self.get("/search/repositories?q="+urllib.parse.quote(query,safe="")+"&per_page=2&sort=updated")
            require(response.get("incomplete_results") is False, "DISCOVERY_INCOMPLETE")
            repos=response.get("items",[])
        found=[]
        for meta in repos[:2]:
            name=meta["full_name"]
            require(self.private or meta["private"] is False, "private search result cannot enter public state")
            # Resolve commit once. Search sometimes lists *uninitialized* public
            # repos (size=0) with an advertised default branch that returns 404.
            # This is an optional discovery result, never an authoritative
            # monitored repository. For that one observed case, skip and report
            # degraded coverage; other 404s, identity errors and API failures
            # must still fail closed. A size-0 repo WITH a branch is inspected.
            try:
                head=self.get(f'/repos/{name}/branches/'+urllib.parse.quote(meta["default_branch"],safe=""))
            except BrainError as exc:
                if (str(exc) == 'SOURCE_API_404: GET failed; no cursor advanced'
                        and type(meta.get("size")) is int and meta["size"] == 0
                        and repository is None):
                    self.unavailable_discovery_branches+=1
                    continue
                raise
            sha=head["commit"]["sha"]
            tree=self.get(f'/repos/{name}/git/trees/{sha}?recursive=1')
            require(tree.get("truncated") is False, "SOURCE_TREE_TRUNCATED")
            rows=tree.get("tree",[])
            paths=[r for r in rows if r.get("type")=="blob" and 0<r.get("size",0)<=100000 and r["path"].endswith((".py",".ts",".js",".lua",".rs",".go")) and not re.search(r"(^|/)(vendor|node_modules|dist)(/|[_.])",r["path"],re.I) and not is_test_source_path(r["path"])]
            terms=target["terms"]
            paths.sort(key=lambda r:(-sum(t in r["path"].lower() for t in terms),r["path"]))
            if not paths:
                continue
            row=paths[0]
            blob=self.get(f'/repos/{name}/git/blobs/{row["sha"]}')
            require(blob.get("encoding")=="base64" and blob.get("sha")==row["sha"], "source blob identity invalid")
            raw=base64.b64decode(blob["content"],validate=False)
            require(len(raw)==row["size"] and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==row["sha"], "SOURCE_CONTENT_HASH_MISMATCH")
            body=raw.decode("utf-8",errors="strict")
            test_paths=related_test_paths(row["path"], rows)
            license=(meta.get("license") or {}).get("spdx_id") or "UNKNOWN"
            found.append(({"repository":name,"head_sha":sha,"path":row["path"],"blob_sha":row["sha"],"code_sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"test_paths":test_paths,"license":license,"source_ref":f'https://github.com/{name}/blob/{sha}/{row["path"]}',"target":target["project"],"query":target["query"],"matched_terms":[term for term in terms if term in body.lower()]},meta["private"]))
        return found

def event(kind, key, payload, source_sha, *, private=False, data_kind="ACTUAL", now=None):
    now=now or utcnow()
    item={"id":"", "kind":kind,"key":key,"payload":payload,"observed_at":now,"source_sha":source_sha,"visibility":"PRIVATE" if private else "PUBLIC","data_kind":data_kind}
    item["id"]=kind+":"+digest(item)
    return item

def policy():
    return json.loads((Path(__file__).parent/"POLICY.json").read_text())
