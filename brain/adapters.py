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
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from brain.core import require, BrainError, digest, utcnow
from brain.intelligence import REPO, is_test_source_path, related_test_paths

def _api_request_family(path):
    """Return only a fixed, non-sensitive endpoint family; never a URL/path.

    The GitHub API path can contain private repositories, branch names, and
    full-text search queries. None of those values belong in provider logs.
    """
    if path.startswith("/search/repositories?"):
        return "REPOSITORY_SEARCH"
    if re.fullmatch(r"/repos/[^/?]+/[^/?]+", path):
        return "REPOSITORY_METADATA"
    if re.fullmatch(r"/repos/[^/?]+/[^/?]+/branches/[^/?]+", path):
        return "BRANCH_LOOKUP"
    if re.fullmatch(r"/repos/[^/?]+/[^/?]+/git/trees/[^/?]+(?:\?recursive=1)?", path):
        return "GIT_TREE"
    if re.fullmatch(r"/repos/[^/?]+/[^/?]+/git/blobs/[^/?]+", path):
        return "GIT_BLOB"
    if re.fullmatch(r"/repos/[^/?]+/[^/?]+/commits/[^/?]+/check-runs\?.*", path):
        return "COMMIT_CHECK_RUNS"
    return "OTHER_BOUNDED_GET"


def _report_api_read_context(path, request_number, *, http_status=None, read_error=None):
    """Diagnostic for one failed GET, never a claim about the whole workload."""
    evidence = {
        "event": "SOURCE_API_GET_FAILURE_CONTEXT",
        "request_family": _api_request_family(path),
        "request_number": request_number,
    }
    if type(http_status) is int and 100 <= http_status <= 599:
        evidence["http_status"] = http_status
    elif read_error is not None:
        # No exception message or URL, and no arbitrary class name.
        evidence["read_failure"] = (
            read_error if read_error in {"TimeoutError", "OSError", "JSONDecodeError", "ResponseTooLarge"}
            else "UNKNOWN"
        )
    print(json.dumps(evidence, sort_keys=True), file=sys.stderr)


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
        # Per-discovery diagnostics are NOT events or verified source facts.
        # They only explain why a search-index hit could not be inspected.
        self.discovery_unavailable=[]
        self.discovery_bounded_trees=[]
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
                if len(raw)>2_000_000:
                    _report_api_read_context(
                        path, self.requests, read_error="ResponseTooLarge"
                    )
                    raise BrainError("SOURCE_RESPONSE_TOO_LARGE")
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                if attempt==0 and exc.code in {429,502,503,504}:
                    retry=exc.headers.get("Retry-After","1")
                    require(retry.isdigit() and int(retry)<=2, "RATE_LIMIT: retry exceeds bounded budget")
                    time.sleep(int(retry))
                    continue
                _report_api_read_context(path, self.requests, http_status=exc.code)
                raise BrainError(f'SOURCE_API_{exc.code}: GET failed; no cursor advanced') from None
            except (TimeoutError, OSError, json.JSONDecodeError) as exc:
                _report_api_read_context(
                    path, self.requests, read_error=type(exc).__name__
                )
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
        require(type(sha) is str and re.fullmatch(r"[0-9a-f]{40}", sha) is not None,
                "SOURCE_REVISION_UNAVAILABLE: invalid default-branch commit")
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
        # GitHub check-run IDs are unique, positive provider identities on
        # EVERY page, including a one-page response. Never accept a duplicate
        # as a second independent run, or a result for another source SHA.
        require(
            all(type(x) is dict and type(x.get("id")) is int
                and x["id"] > 0 and x.get("head_sha") == sha for x in items)
            and len({x["id"] for x in items}) == total,
            "CHECK_COVERAGE_AMBIGUOUS: invalid, duplicate or cross-revision check identity",
        )
        # Branches can advance during a multi-page check fetch. A sampled
        # branch must still point to this SHA at the end, or the entire
        # observation fails closed. No retry or second provider is spawned.
        confirmed=self.get("/repos/"+repository+"/branches/"+urllib.parse.quote(branch,safe=""))
        require(
            type(confirmed) is dict
            and type(confirmed.get("commit")) is dict
            and confirmed["commit"].get("sha") == sha,
            "SOURCE_REVISION_CHANGED: branch advanced during check collection",
        )
        rows=[{"name":x["name"],"status":x["status"],"conclusion":x.get("conclusion"),"head_sha":x["head_sha"],"url":x["html_url"]} for x in items]
        return {"repository":repository,"head_sha":sha,"default_branch":branch,"checks":rows,"open_issues":meta["open_issues_count"],"source_ref":f'https://github.com/{repository}/commit/{sha}'}, meta["private"]

    def _bounded_public_tree(self, repository, head_sha, terms):
        """Source-visible but INCOMPLETE tree evidence after recursive overflow.

        Pin the Git commit -> root Git tree -> each child Git tree by provider
        object IDs, and verify the chosen original blob later in discover().
        At most FOUR child trees, never a speculative full-tree crawl or an
        override of the original 2 MB/read or 24 GET/workload limits.
        Only call for optional *public* search hits, never private/explicit.
        """
        require(REPO.fullmatch(repository or ""), "BOUNDED_TREE_REPOSITORY_INVALID")
        require(type(head_sha) is str and re.fullmatch(r"[0-9a-f]{40}", head_sha),
                "BOUNDED_TREE_HEAD_INVALID")
        commit=self.get(f"/repos/{repository}/git/commits/{head_sha}")
        require(type(commit) is dict and commit.get("sha")==head_sha
                and type(commit.get("tree")) is dict,
                "BOUNDED_TREE_COMMIT_IDENTITY_INVALID")
        root_sha=commit["tree"].get("sha")
        require(type(root_sha) is str and re.fullmatch(r"[0-9a-f]{40}",root_sha),
                "BOUNDED_TREE_ROOT_ID_INVALID")

        def inspect(prefix, expected_sha):
            tree=self.get(f"/repos/{repository}/git/trees/{expected_sha}")
            require(type(tree) is dict and tree.get("sha")==expected_sha
                    and tree.get("truncated") is False
                    and type(tree.get("tree")) is list,
                    "BOUNDED_TREE_OBJECT_INVALID")
            files,children=[],[]
            seen=set()
            for obj in tree["tree"]:
                require(type(obj) is dict and type(obj.get("path")) is str,
                        "BOUNDED_TREE_ENTRY_INVALID")
                name=obj["path"]
                require(0<len(name)<=255 and name not in {".",".."}
                        and "/" not in name and "\\" not in name
                        and "\x00" not in name and name not in seen,
                        "BOUNDED_TREE_PATH_INVALID")
                seen.add(name)
                full=prefix+name
                kind=obj.get("type")
                if kind=="tree":
                    node_sha=obj.get("sha")
                    require(type(node_sha) is str and
                            re.fullmatch(r"[0-9a-f]{40}",node_sha),
                            "BOUNDED_TREE_CHILD_ID_INVALID")
                    children.append((full+"/",node_sha))
                elif kind=="blob":
                    node_sha=obj.get("sha")
                    size=obj.get("size")
                    require(type(node_sha) is str and
                            re.fullmatch(r"[0-9a-f]{40}",node_sha)
                            and type(size) is int and size>=0,
                            "BOUNDED_TREE_BLOB_ID_OR_SIZE_INVALID")
                    files.append({"type":"blob","path":full,
                                  "size":size,"sha":node_sha})
                else:
                    # Gitlink/submodule content is NOT recursively inspected.
                    require(kind=="commit", "BOUNDED_TREE_KIND_INVALID")
            return files,children

        all_files,pending=inspect("",root_sha)
        # Prefer source/test code roots, then target-word-bearing folders.
        # Re-rank at every step so a relevant second-level folder may be
        # visited before unrelated root folders, without extra fanout.
        names={"src":0,"tests":1,"lib":2,"app":3,"packages":4,
               "services":5,"source":6,"internal":7,"test":8,
               "examples":9,"crates":10}
        def key(node):
            path=node[0].rstrip("/").lower()
            tail=path.rsplit("/",1)[-1]
            matched=sum(str(t).lower() in path for t in terms)
            return (-matched*20+names.get(tail,20),
                    path.count("/"),path)
        scanned=0
        while pending and scanned<4:
            pending.sort(key=key)
            prefix,tree_sha=pending.pop(0)
            # Only root or two child levels: reject unbounded descent.
            if prefix.count("/")>2:
                continue
            files,children=inspect(prefix,tree_sha)
            all_files.extend(files)
            if prefix.count("/")<2:
                pending.extend(children)
            scanned+=1
        return all_files,scanned

    def discover(self, target, *, repository=None):
        self.discovery_unavailable=[]
        self.discovery_bounded_trees=[]
        if repository:
            # Explicitly requested sources are authoritative user scope: 404 is
            # always an error, never silently changed into an empty search.
            repos=[self.get("/repos/"+repository)]
        else:
            query=target["query"]+('' if self.private else ' is:public')
            response=self.get("/search/repositories?q="+urllib.parse.quote(query,safe="")+"&per_page=2&sort=updated")
            require(response.get("incomplete_results") is False, "DISCOVERY_INCOMPLETE")
            require(type(response.get("items")) is list, "DISCOVERY_RESPONSE_INVALID")
            repos=response["items"]
        found=[]
        for meta in repos[:2]:
            require(type(meta) is dict and type(meta.get("full_name")) is str
                    and REPO.fullmatch(meta["full_name"]), "DISCOVERY_RESULT_IDENTITY_INVALID")
            name=meta["full_name"]
            require(type(meta.get("private")) is bool, "DISCOVERY_RESULT_VISIBILITY_UNAVAILABLE")
            require(self.private or meta["private"] is False, "private search result cannot enter public state")
            require(type(meta.get("default_branch")) is str
                    and 0<len(meta["default_branch"])<=100, "DISCOVERY_RESULT_DEFAULT_BRANCH_INVALID")
            # A GitHub search index can point to a repository or revision
            # deleted between search and inspection. Only a provider 404 from
            # inspecting a SEARCH-DERIVED candidate is skippable, and only if
            # another result is genuinely inspected. All other errors fail.
            stage="branch"
            try:
                head=self.get(f'/repos/{name}/branches/'+urllib.parse.quote(meta["default_branch"],safe=""))
                sha=head["commit"]["sha"]
                require(type(sha) is str and re.fullmatch(r"[0-9a-f]{40}",sha),
                        "DISCOVERY_SOURCE_SHA_INVALID")
                stage="tree"
                bounded_child_count=None
                try:
                    tree=self.get(f'/repos/{name}/git/trees/{sha}?recursive=1')
                    require(tree.get("truncated") is False, "SOURCE_TREE_TRUNCATED")
                    rows=tree.get("tree",[])
                except BrainError as exc:
                    optional_public=(repository is None and not self.private
                                     and meta["private"] is False)
                    if not optional_public or str(exc)!="SOURCE_RESPONSE_TOO_LARGE":
                        raise
                    # Fresh fixed-head provider objects; never inspect the
                    # oversized recursive result or invent its contents.
                    rows,bounded_child_count=self._bounded_public_tree(
                        name,sha,target["terms"])
                paths=[r for r in rows if r.get("type")=="blob" and 0<r.get("size",0)<=100000 and r["path"].endswith((".py",".ts",".js",".lua",".rs",".go")) and not re.search(r"(^|/)(vendor|node_modules|dist)(/|[_.])",r["path"],re.I) and not is_test_source_path(r["path"])]
                terms=target["terms"]
                paths.sort(key=lambda r:(-sum(t in r["path"].lower() for t in terms),r["path"]))
                if not paths:
                    if bounded_child_count is not None:
                        self.discovery_unavailable.append({
                            "repository":name,"stage":"tree",
                            "reason":"SEARCH_RESULT_BOUNDED_TREE_NO_ELIGIBLE_SOURCE",
                        })
                    continue
                row=paths[0]
                stage="blob"
                blob=self.get(f'/repos/{name}/git/blobs/{row["sha"]}')
                require(blob.get("encoding")=="base64" and blob.get("sha")==row["sha"], "source blob identity invalid")
                raw=base64.b64decode(blob["content"],validate=False)
                require(len(raw)==row["size"] and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==row["sha"], "SOURCE_CONTENT_HASH_MISMATCH")
                body=raw.decode("utf-8",errors="strict")
                test_paths=related_test_paths(row["path"], rows)
                license=(meta.get("license") or {}).get("spdx_id") or "UNKNOWN"
                found.append(({"repository":name,"head_sha":sha,"path":row["path"],"blob_sha":row["sha"],"code_sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"test_paths":test_paths,"license":license,"source_ref":f'https://github.com/{name}/blob/{sha}/{row["path"]}',"target":target["project"],"query":target["query"],"matched_terms":[term for term in terms if term in body.lower()]},meta["private"]))
                if bounded_child_count is not None:
                    self.discovery_bounded_trees.append({
                        "repository":name,"head_sha":sha,
                        "source_path":row["path"],
                        "child_trees_inspected":bounded_child_count,
                        "scope":"PARTIAL_TREE_ORIGINAL_BLOB_VERIFIED",
                    })
            except BrainError as exc:
                # Only a never-initialized, public, search-derived branch
                # may disappear without a fatal error. Nonempty or malformed
                # repository size and private discovery always remain fatal.
                # Preserve the V5 separate tree/blob search-volatility handling
                # only for public optional hits with surviving inspected source.
                optional_public = (repository is None and not self.private
                                   and meta["private"] is False)
                empty_branch = (stage == "branch"
                                and type(meta.get("size")) is int
                                and meta["size"] == 0)
                vanished = (str(exc) ==
                            "SOURCE_API_404: GET failed; no cursor advanced")
                oversized = (str(exc) == "SOURCE_RESPONSE_TOO_LARGE")
                # A too-large optional recursive tree/blob is NOT an inspected
                # source. Never truncate/parse it, increase the 2 MB response
                # budget, retry it, or silently substitute a candidate. A
                # distinct fully hash-inspected source is mandatory to PASS.
                # Oversized search API, branch, explicit-repository, private,
                # transport, identity or integrity failures remain fatal.
                if optional_public and (
                    (vanished and (stage in {"tree", "blob"} or empty_branch))
                    or (oversized and stage in {"tree", "blob"})
                ):
                    self.discovery_unavailable.append({
                        "repository":name, "stage":stage,
                        "reason":("SEARCH_RESULT_SOURCE_404_NOT_INSPECTED"
                                  if vanished else
                                  "SEARCH_RESULT_RESPONSE_TOO_LARGE_NOT_INSPECTED"),
                    })
                    continue
                raise
        # This is NOT a blanket 404 suppressor. No verified candidate means
        # the selected search results were unavailable: leave the research
        # workflow failed so the doctor cannot certify missing observation.
        if self.discovery_unavailable and not found:
            stages=",".join(sorted({row["stage"] for row in self.discovery_unavailable}))
            reasons={row["reason"] for row in self.discovery_unavailable}
            failure_family = (
                "provider 404" if reasons=={"SEARCH_RESULT_SOURCE_404_NOT_INSPECTED"}
                else "provider size bound" if reasons==
                    {"SEARCH_RESULT_RESPONSE_TOO_LARGE_NOT_INSPECTED"}
                else "partial tree no eligible source" if reasons==
                    {"SEARCH_RESULT_BOUNDED_TREE_NO_ELIGIBLE_SOURCE"}
                else "provider 404/size bound/partial tree"
            )
            raise BrainError(
                "DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE: "
                +failure_family+" at "+stages+"; verified_candidates=0"
            )
        return found

def event(kind, key, payload, source_sha, *, private=False, data_kind="ACTUAL", now=None):
    now=now or utcnow()
    item={"id":"", "kind":kind,"key":key,"payload":payload,"observed_at":now,"source_sha":source_sha,"visibility":"PRIVATE" if private else "PUBLIC","data_kind":data_kind}
    item["id"]=kind+":"+digest(item)
    return item

def policy():
    return json.loads((Path(__file__).parent/"POLICY.json").read_text())
