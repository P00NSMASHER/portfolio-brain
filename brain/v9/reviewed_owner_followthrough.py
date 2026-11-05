"""Enroll one active original owner observation in verified release progression.

The enrolled source, owner and work identity are immutable. GitHub original
PR, merge ancestry and exact-head App checks are independently read before
the existing journal can advance DIAGNOSED -> PATCHED -> TESTED. No live
functional acceptance, third-party code execution or new write authority.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from brain.v9.batch_queue import BatchFault, BatchQueue, digest, hashval

REPO = "P00NSMASHER/portfolio-brain"
ROOT = "https://api.github.com/repos/" + REPO + "/"
PR_NUMBER = 873
SOURCE_SHA = "a680fa9e888940ff907bf3364aba6b9f12e4ecfc"
WORK_ID = "03749797de0a5276d44002bd95a600fa2468c6cc7fade30bbcbfe69303fe0d0d"
EXPECTED_OWNER = "brain-engineering"
FINGERPRINT = "11573c605a67b5c2b31396a0ed8898ba83d0b2dc3928c4a5a3e9464c09d8bf20"
REQUIRED_APPS = {"validate": 15368, "portfolio-phase1-gate": 5121826}
STEPS = ("DIAGNOSED", "PATCHED", "TESTED")
SOURCE_ID = re.compile(r"[0-9a-f]{40}\Z")


class OwnerProofHeld(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise OwnerProofHeld(reason)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OriginalGitHub:
    def __init__(self, token):
        need(type(token) is str and 20 <= len(token) <= 4096,
             "OWNER_PROOF_TOKEN_UNAVAILABLE")
        self.token = token
        self.reads = 0

    def get(self, route):
        # Only the exact approved PR and exact-identity immutable Git objects.
        # Identifiers are supplied by the original PR readback, not by the
        # candidate work item or arbitrary external source content.
        allowed = (
            route == "pulls/873"
            or re.fullmatch(r"git/commits/[0-9a-f]{40}", route) is not None
            or re.fullmatch(r"commits/[0-9a-f]{40}/check-runs\?per_page=100",
                            route) is not None
        )
        need(type(route) is str and allowed, "OWNER_PROOF_ROUTE_DENIED")
        self.reads += 1
        need(self.reads <= 3, "OWNER_PROOF_READ_BOUND")
        request = urllib.request.Request(ROOT + route, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "portfolio-brain-owner-proof",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urllib.request.build_opener(_NoRedirect()).open(
                request, timeout=10
            ) as response:
                need(response.status == 200, "OWNER_PROOF_HTTP_STATUS")
                raw = response.read(160_001)
        except (OSError, urllib.error.URLError) as exc:
            raise OwnerProofHeld("OWNER_PROOF_PROVIDER_UNAVAILABLE") from exc
        need(0 < len(raw) <= 160_000, "OWNER_PROOF_RESPONSE_BOUND")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise OwnerProofHeld("OWNER_PROOF_JSON_INVALID") from exc


def _eligible(row):
    return (
        type(row) is dict
        and row.get("work_id") == WORK_ID
        and row.get("project_id") == "portfolio-brain"
        and row.get("repository") == REPO
        and row.get("source_sha") == SOURCE_SHA
        and row.get("owner") == EXPECTED_OWNER
        and row.get("fingerprint") == FINGERPRINT
        and row.get("path") == "repository-observation"
        and type(row.get("priority")) is int and row["priority"] == 2
        and row.get("pending") is None
        and row.get("stage") in {"OBSERVED", "DIAGNOSED", "PATCHED", "TESTED"}
    )


def inspect_original_proof(api):
    """Return source-bound evidence only after the protected release is real."""
    pr = api.get("pulls/873")
    need(type(pr) is dict and type(pr.get("number")) is int
         and pr["number"] == PR_NUMBER
         and pr.get("state") == "closed" and pr.get("merged") is True
         and type(pr.get("merged_at")) is str
         and type(pr.get("head")) is dict
         and type(pr.get("base")) is dict
         and pr["head"].get("repo", {}).get("full_name") == REPO
         and pr["base"].get("repo", {}).get("full_name") == REPO
         and pr["base"].get("ref") == "main",
         "OWNER_PROOF_EXACT_REVIEWED_PR_UNVERIFIED")
    candidate = pr["head"].get("sha")
    merge_sha = pr.get("merge_commit_sha")
    need(type(candidate) is str and SOURCE_ID.fullmatch(candidate)
         and type(merge_sha) is str and SOURCE_ID.fullmatch(merge_sha)
         and len({candidate, merge_sha, SOURCE_SHA}) == 3,
         "OWNER_PROOF_SOURCE_IDENTITIES_UNVERIFIED")

    merge = api.get("git/commits/" + merge_sha)
    parents = merge.get("parents") if type(merge) is dict else None
    need(type(merge) is dict and merge.get("sha") == merge_sha
         and type(parents) is list and len(parents) == 1
         and type(parents[0]) is dict
         and parents[0].get("sha") == SOURCE_SHA,
         "OWNER_PROOF_PROTECTED_SOURCE_PARENT_UNVERIFIED")

    checks = api.get("commits/" + candidate + "/check-runs?per_page=100")
    rows = checks.get("check_runs") if type(checks) is dict else None
    need(type(rows) is list and type(checks.get("total_count")) is int
         and len(rows) == checks["total_count"] < 100,
         "OWNER_PROOF_INDEPENDENT_CENSUS_INCOMPLETE")
    for name, issuer in REQUIRED_APPS.items():
        matches = [r for r in rows if type(r) is dict and r.get("name") == name]
        need(len(matches) == 1, "OWNER_PROOF_CHECK_UNVERIFIED")
        row = matches[0]
        need(row.get("head_sha") == candidate
             and row.get("status") == "completed"
             and row.get("conclusion") == "success"
             and type(row.get("app")) is dict
             and type(row["app"].get("id")) is int
             and row["app"]["id"] == issuer,
             "OWNER_PROOF_INDEPENDENT_ISSUER_UNVERIFIED")

    base = {
        "kind": "VERIFIED_ORIGINAL_PROTECTED_REPAIR",
        "original_source_sha": SOURCE_SHA,
        "candidate_head_sha": candidate,
        "protected_merge_sha": merge_sha,
        "source_pr": PR_NUMBER,
        "original_app_issuers": REQUIRED_APPS,
        "merged_at": pr["merged_at"],
    }
    return {
        "candidate_head_sha": candidate,
        "protected_merge_sha": merge_sha,
        "stage_evidence": {stage: digest({**base, "stage": stage})
                           for stage in STEPS},
    }


def try_progress(queue, *, source_sha, now, budget, api=None):
    """Apply only this approved original repair, never unverified live status.

    Claim tokens and progress are private to canonical queue transaction
    boundaries, and affected projects remain subject to source freshness.
    """
    need(type(queue) is BatchQueue and hashval(source_sha,40)
         and type(now) is str and type(budget) is int and 0 <= budget <= 24,
         "OWNER_PROOF_CALLER_INVALID")
    work = queue.snapshot()["work"].get(WORK_ID)
    if work is None:
        return dict(status="NO_REVIEWED_OWNER_WORK_IN_ACTIVE_QUEUE",
                    transitions=0, provider_gets=0, production_accepted=False)
    need(_eligible(work), "OWNER_PROOF_WORK_NOT_ELIGIBLE")
    if work["stage"] == "TESTED":
        return dict(status="REVIEWED_WORK_ALREADY_TESTED",
                    transitions=0,provider_gets=0,production_accepted=False)
    if source_sha == SOURCE_SHA:
        return dict(status="UNRELEASED_SOURCE_CANNOT_ATTEST_REPAIR",
                    transitions=0,provider_gets=0,production_accepted=False)
    if work.get("claim") is not None and work["claim"].get("expires_at","") > now:
        return dict(status="OWNER_WORK_CLAIM_HELD",
                    transitions=0,provider_gets=0,production_accepted=False)
    if budget < 3:
        return dict(status="OWNER_ORIGINAL_READ_BUDGET_DEFERRED",
                    transitions=0,provider_gets=0,production_accepted=False)
    used=0
    try:
        provider = api if api is not None else OriginalGitHub(
            os.environ.get("GITHUB_TOKEN",""))
        proof = inspect_original_proof(provider)
        used = 3
    except (OwnerProofHeld,OSError,ValueError,KeyError,TypeError,AttributeError):
        return dict(status="ORIGINAL_OWNER_REVIEW_NOT_VERIFIED",
                    transitions=0,provider_gets=min(3,getattr(
                        locals().get("provider"),"reads",0)),
                    production_accepted=False)
    try:
        token = queue.claim(WORK_ID, EXPECTED_OWNER, now=now)
        stages = list(STEPS)
        first = stages.index(work["stage"]) + 1 if work["stage"] in stages else 0
        done = 0
        for stage in stages[first:]:
            queue.advance(WORK_ID,token,stage,
                          evidence_sha=proof["stage_evidence"][stage],now=now)
            done += 1
    except BatchFault:
        return dict(status="OWNER_QUEUE_FENCED_OR_CONFLICTED",transitions=0,
                    provider_gets=used,production_accepted=False)
    return dict(
        status="REVIEWED_OWNER_REPAIR_TESTED_FROM_ORIGINAL_GITHUB",
        work_id=WORK_ID,reviewed_pr=PR_NUMBER,
        candidate_head_sha=proof["candidate_head_sha"],
        protected_merge_sha=proof["protected_merge_sha"],
        stages_reached=stages[first:],independent_checks_verified=True,
        transitions=done,provider_gets=used,
        real_world_functionality_verified=False,
        production_accepted=False,
    )
