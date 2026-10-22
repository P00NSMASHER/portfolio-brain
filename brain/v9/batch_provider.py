"""Read-only, scope-pinned original GitHub evidence normalization.

Production callers MUST pass an authorized original GitHub GET reader. Tests
use fixtures and establish parser correctness, not authenticated provider
origin. No writes, native merge, CI approvals or unattended acceptance here.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re


REPO = "P00NSMASHER/portfolio-brain"
REQUIRED = (("validate", 15368), ("portfolio-phase1-gate", 5121826))
MAX_JSON_BYTES = 512_000


class ProviderProofError(ValueError):
    """A provider response is unavailable, ambiguous, or not exact-source."""


def _need(predicate, code):
    if not predicate:
        raise ProviderProofError(code)


def _sha(value, n=40):
    return type(value) is str and re.fullmatch("[a-f0-9]{%d}" % n, value) is not None


def _timestamp(value):
    _need(type(value) is str and re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z",
        value) is not None, "OBSERVED_AT_INVALID")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProviderProofError("OBSERVED_AT_INVALID") from exc


def _json(value):
    try:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProviderProofError("PROVIDER_RESPONSE_INVALID") from exc
    _need(len(content.encode("utf-8")) <= MAX_JSON_BYTES,
          "PROVIDER_RESPONSE_OVERSIZED")
    return content


def _double_get(fetch, url, changed_code):
    _need(callable(fetch) and type(url) is str and
          url.startswith("https://api.github.com/repos/" + REPO + "/"),
          "PROVIDER_SCOPE_INVALID")
    original = []
    for _ in range(2):
        try:
            value = fetch(url)
        except Exception as exc:
            raise ProviderProofError("PROVIDER_READ_UNAVAILABLE") from exc
        _need(type(value) is dict, "PROVIDER_RESPONSE_INVALID")
        original.append((value, _json(value)))
    _need(original[0][1] == original[1][1], changed_code)
    return original[1][0]


def _scope(repository, observed_at):
    _need(repository == REPO, "PROVIDER_SCOPE_INVALID")
    _timestamp(observed_at)


def _same_repo(row):
    return type(row) is dict and (row.get("repo") or {}).get("full_name") == REPO


def _fingerprint(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def read_original_draft_pr(fetch, *, repository, pr_number, base_sha,
                           head_sha, operation_id, observed_at):
    """Correlate a new, same-repository draft with its *durable* operation ID.

    The operation ID must have been reserved before issuing CREATE_DRAFT_PR.
    A generic POST acknowledgement, search result, or self-authored status is
    insufficient. Missing or inconsistent provider readback remains UNKNOWN.
    """
    _scope(repository, observed_at)
    _need(type(pr_number) is int and 0 < pr_number < 10**9 and
          _sha(base_sha) and _sha(head_sha) and _sha(operation_id, 64),
          "PROVIDER_SCOPE_INVALID")
    url = "https://api.github.com/repos/" + REPO + "/pulls/" + str(pr_number)
    value = _double_get(fetch, url, "PR_READBACK_CHANGED")
    head = value.get("head")
    base = value.get("base")
    _need(type(head) is dict and type(base) is dict and
          _same_repo(head) and _same_repo(base) and
          type(value.get("number")) is int and value["number"] == pr_number and
          value.get("state") == "open" and value.get("draft") is True and
          (value.get("user") or {}).get("login") == "P00NSMASHER" and
          head.get("sha") == head_sha and base.get("sha") == base_sha and
          base.get("ref") == "main" and
          type(value.get("body")) is str and
          "BRAIN_OPERATION_ID:" + operation_id in value["body"],
          "PR_IDENTITY_INVALID")
    proof = dict(repository=REPO, source_sha=base_sha,
                 candidate_sha=head_sha, operation_id=operation_id,
                 provider_id=pr_number, observed_at=observed_at)
    return dict(proof, status="EXACT_DRAFT_PR_READBACK_CONFIRMED",
                readback_sha256=_fingerprint(proof),
                original_provider_reads=2,
                provider_origin_must_be_confirmed_by_caller=True,
                provider_writes=False, merge_authority=False,
                production_accepted=False,
                authenticated_unattended_acceptance=False)


def read_original_check_gate(fetch, *, repository, head_sha, observed_at):
    """Validate exact-commit original check issuer identities, not names alone."""
    _scope(repository, observed_at)
    _need(_sha(head_sha), "PROVIDER_SCOPE_INVALID")
    url = ("https://api.github.com/repos/" + REPO + "/commits/" +
           head_sha + "/check-runs?per_page=100")
    value = _double_get(fetch, url, "CHECK_READBACK_CHANGED")
    rows = value.get("check_runs")
    count = value.get("total_count")
    _need(type(rows) is list and type(count) is int and
          count == len(rows) and count < 100,
          "CHECK_GATE_INCOMPLETE")
    verified = []
    for name, issuer in REQUIRED:
        matching = [r for r in rows if type(r) is dict and r.get("name") == name]
        _need(len(matching) == 1, "CHECK_GATE_INCOMPLETE")
        r = matching[0]
        _need(type(r.get("app")) is dict and
              type(r["app"].get("id")) is int and
              r["app"]["id"] == issuer and
              r.get("head_sha") == head_sha and
              r.get("status") == "completed" and
              r.get("conclusion") == "success",
              "CHECK_GATE_INCOMPLETE")
        verified.append(issuer)
    proof = dict(repository=REPO, head_sha=head_sha,
                 issuer_app_ids=verified, observed_at=observed_at,
                 checks=[name for name, _ in REQUIRED])
    return dict(proof, status="EXACT_HEAD_CHECKS_READBACK_CONFIRMED",
                readback_sha256=_fingerprint(proof),
                original_provider_reads=2,
                provider_origin_must_be_confirmed_by_caller=True,
                provider_writes=False,
                production_accepted=False,
                independent_six_hour_acceptance=False)
