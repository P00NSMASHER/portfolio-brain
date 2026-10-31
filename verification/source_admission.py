"""Bounded cross-path admission of the current production acceptance receipt.

Executed ONLY by the trusted-main independent App5121826 PR verifier.
The canonical receipt is created by source_acceptance_producer, validated
by source_acceptance_verifier, and independently attested by App5121826.
This does not create a receipt, accept a simulated run, or change any rules.
"""
from __future__ import annotations

import hashlib
import re
import urllib.error
from typing import Any, Callable

from brain.v9.guarded_merge import REPO, checked_document
from verification.source_acceptance_verifier import (
    SourceAcceptanceError, _verify_receipt_contract, strict_json, utc,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DATE = re.compile(r"[0-9]{8}\Z")
_MAX_READS = 7
_APP_ID = 5121826
_NAME = "portfolio-source-acceptance"
_SCOPE = "SOURCE_SPECIFIC_UNATTENDED_PRODUCTION_CORE_RELIABILITY_ONLY"


class SourceAdmissionError(RuntimeError):
    """Fixed denial codes, no provider URLs, tokens or response text."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise SourceAdmissionError(reason)


def _allowed_route(route: str, source: str) -> bool:
    short = source[:8]
    prefix = "auto-repair/pb-01-acceptance-receipt-" + short + "-"
    return (
        route == "/git/matching-refs/heads/" + prefix
        or re.fullmatch(r"/git/commits/[0-9a-f]{40}", route) is not None
        or re.fullmatch(r"/compare/" + source + r"\.\.\.[0-9a-f]{40}", route) is not None
        or re.fullmatch(
            r"/contents/acceptance/finish-soak-" + short
            + r"-[0-9]{8}\.json\?ref=[0-9a-f]{40}", route
        ) is not None
        or re.fullmatch(r"/commits/[0-9a-f]{40}/check-runs\?per_page=100", route)
            is not None
        or route == "/branches/main"
    )


def verify_predecessor_acceptance(
    source: str, read: Callable[[str], Any],
) -> dict[str, str]:
    """Require the *current source's* real, independently attested 12h receipt.

    No PR labels, owner comments, old source acceptances, synthetic data,
    or normal phase1-gate check can be substituted for App's source receipt.
    """
    _require(type(source) is str and _SHA.fullmatch(source) is not None,
             "SOURCE_SHA_INVALID")
    _require(callable(read), "SOURCE_READ_PRINCIPAL_MISSING")
    calls = 0

    def get(route: str) -> Any:
        nonlocal calls
        _require(type(route) is str and _allowed_route(route, source),
                 "SOURCE_API_ROUTE_DENIED")
        _require(calls < _MAX_READS, "SOURCE_API_READ_CAP_EXCEEDED")
        calls += 1
        try:
            return read(route)
        except urllib.error.HTTPError as exc:
            # A missing canonical receipt is a normal *denial*, never success.
            if exc.code == 404 and route.startswith(
                "/git/matching-refs/heads/auto-repair/pb-01-acceptance-receipt-"
            ):
                raise SourceAdmissionError("SOURCE_ACCEPTANCE_NOT_YET_RECORDED") from None
            raise SourceAdmissionError("SOURCE_API_UNAVAILABLE") from None
        except SourceAdmissionError:
            raise
        except (OSError, TimeoutError, ValueError, TypeError):
            raise SourceAdmissionError("SOURCE_API_UNAVAILABLE") from None

    prefix = "auto-repair/pb-01-acceptance-receipt-" + source[:8] + "-"
    matches = get("/git/matching-refs/heads/" + prefix)
    _require(type(matches) is list and len(matches) == 1,
             "SOURCE_ACCEPTANCE_NOT_YET_RECORDED" if matches == []
             else "ACCEPTANCE_BRANCH_NOT_UNIQUE")
    ref = matches[0]
    _require(type(ref) is dict and type(ref.get("ref")) is str
             and ref["ref"].startswith("refs/heads/" + prefix)
             and type(ref.get("object")) is dict
             and ref["object"].get("type") == "commit",
             "ACCEPTANCE_BRANCH_IDENTITY")
    date = ref["ref"][len("refs/heads/" + prefix):]
    _require(_DATE.fullmatch(date) is not None, "ACCEPTANCE_BRANCH_IDENTITY")
    tip = ref["object"].get("sha")
    _require(type(tip) is str and _SHA.fullmatch(tip) is not None,
             "ACCEPTANCE_COMMIT_IDENTITY")

    commit = get("/git/commits/" + tip)
    _require(type(commit) is dict and commit.get("sha") == tip
             and type(commit.get("parents")) is list
             and len(commit["parents"]) == 1
             and type(commit["parents"][0]) is dict
             and commit["parents"][0].get("sha") == source,
             "ACCEPTANCE_COMMIT_ANCESTRY")
    path = "acceptance/finish-soak-" + source[:8] + "-" + date + ".json"
    compare = get("/compare/" + source + "..." + tip)
    _require(type(compare) is dict
             and compare.get("ahead_by") == 1
             and compare.get("behind_by") == 0
             and type(compare.get("merge_base_commit")) is dict
             and compare["merge_base_commit"].get("sha") == source
             and type(compare.get("files")) is list
             and len(compare["files"]) == 1
             and type(compare["files"][0]) is dict
             and compare["files"][0].get("filename") == path
             and compare["files"][0].get("status") == "added",
             "ACCEPTANCE_BRANCH_SCOPE")
    content = get("/contents/" + path + "?ref=" + tip)
    try:
        raw = checked_document(content)
        receipt = strict_json(raw)
        _verify_receipt_contract(receipt)
    except (SourceAcceptanceError, ValueError, TypeError):
        raise SourceAdmissionError("ACCEPTANCE_RECEIPT_INVALID") from None

    _require(receipt.get("source_sha") == source
             and receipt.get("scope") == _SCOPE
             and receipt.get("decision") == "RELEASED"
             and receipt.get("status") == "PASS",
             "ACCEPTANCE_STATUS_OR_SOURCE")
    evidence = receipt["original_run_evidence"]
    terminal = receipt["terminal_state_replay"]
    proof = receipt["proof"]
    _require(type(evidence.get("completed_span_seconds")) is int
             and evidence["completed_span_seconds"] >= 43200
             and type(evidence.get("maximum_gap_seconds")) is int
             and 0 <= evidence["maximum_gap_seconds"] <= 5400
             and evidence.get("all_success_attempt_one") is True
             and evidence.get("all_original_core_state_parent_child_links_contiguous") is True
             and evidence.get("all_required_original_job_steps_success") is True
             and evidence.get("original_artifacts_sha256_size_crc_verified") is True
             and receipt["external_cloudflare_provider"].get(
                 "all_signed_origin_records_source_bound") is True
             and receipt["external_cloudflare_provider"].get(
                 "all_origin_verification_steps_success") is True
             and type(receipt["external_cloudflare_provider"].get(
                 "signed_dispatch_count")) is int
             and receipt["external_cloudflare_provider"]["signed_dispatch_count"] > 0
             and terminal.get("source_sha") == source
             and terminal.get("pending_events") == 0
             and terminal.get("sqlite_integrity") == "PASS"
             and terminal.get("foreign_keys") == "PASS"
             and terminal.get("strict_event_ledger_replay") == "PASS"
             and terminal.get("deterministic_report_reproduction") == "PASS"
             and proof.get("technical_workflow_conclusion") == "success"
             and proof.get("hosted_review_result_source_bound") is True,
             "ACCEPTANCE_ORIGINAL_EVIDENCE_MISSING")
    try:
        stamp = utc(evidence.get("first_original_monitor_completed_utc"))
    except SourceAcceptanceError:
        raise SourceAdmissionError("ACCEPTANCE_DATE_INVALID") from None
    _require(stamp.strftime("%Y%m%d") == date, "ACCEPTANCE_DATE_INVALID")

    checks = get("/commits/" + tip + "/check-runs?per_page=100")
    _require(type(checks) is dict and type(checks.get("total_count")) is int
             and 0 <= checks["total_count"] < 100
             and type(checks.get("check_runs")) is list
             and len(checks["check_runs"]) == checks["total_count"],
             "ACCEPTANCE_ATTESTATION_CENSUS_INCOMPLETE")
    rows = checks["check_runs"]
    _require(all(type(row) is dict and row.get("head_sha") == tip
                 and type(row.get("id")) is int and row["id"] > 0
                 for row in rows)
             and len({row["id"] for row in rows}) == len(rows),
             "ACCEPTANCE_ATTESTATION_CENSUS_INCOMPLETE")
    attested = [row for row in rows if row.get("name") == _NAME]
    binding = "source-acceptance:" + source + ":" + hashlib.sha256(raw).hexdigest()
    _require(len(attested) == 1 and type(attested[0].get("app")) is dict
             and attested[0]["app"].get("id") == _APP_ID
             and attested[0].get("external_id") == binding
             and attested[0].get("status") == "completed"
             and attested[0].get("conclusion") == "success",
             "ACCEPTANCE_ATTESTATION_UNVERIFIED")
    main = get("/branches/main")
    _require(type(main) is dict and main.get("protected") is True
             and type(main.get("commit")) is dict
             and main["commit"].get("sha") == source,
             "ACCEPTANCE_MAIN_MOVED")
    return {"acceptance_ref": prefix + date, "acceptance_commit": tip}
