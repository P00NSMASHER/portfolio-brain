"""Bounded GitHub GET-only discovery. Content is data, never instructions.

Public scheduled state never uses authorization to obtain private content.
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
from brain.intelligence import REPO

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BrainError("REDIRECT_REFUSED: source identity must remain api.github.com")

class GitHub:
    def __init__(self, *, private=False, transport=None):
        self.private=private
        self.token=os.environ.get("GITHUB_TOKEN", "") if private else ""
        require(not private or self.token, "PRIVATE_ACCESS_UNAVAILABLE: explicit existing GITHUB_TOKEN required")
        self.transport=transport
        self.requests=0
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
            # Resolve commit once. Fetch every source from that exact revision.
            head=self.get(f'/repos/{name}/branches/'+urllib.parse.quote(meta["default_branch"],safe=""))
            sha=head["commit"]["sha"]
            tree=self.get(f'/repos/{name}/git/trees/{sha}?recursive=1')
            require(tree.get("truncated") is False, "SOURCE_TREE_TRUNCATED")
            rows=tree.get("tree",[])
            paths=[r for r in rows if r.get("type")=="blob" and 0<r.get("size",0)<=100000 and r["path"].endswith((".py",".ts",".js",".lua",".rs",".go")) and not re.search(r"(^|/)(vendor|node_modules|dist|test[s]?)(/|[_.])",r["path"],re.I)]
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
            test_paths=[r["path"] for r in rows if r.get("type")=="blob" and re.search(r"(^|/)(test[s]?|__tests__)(/|[_.])|(_test|\.test|\.spec)\.",r["path"],re.I)][:10]
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
