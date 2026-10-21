"""Isolated Cloudflare-original comparison: read-only data, never acceptance.

Inputs are untrusted JSON snapshots, even if structurally identical to original
GitHub / Cloudflare responses. This module cannot authenticate their origin and
therefore NEVER publishes an issuer check, acceptance, or merge authorization.
It does not contact any provider, read credentials, or mutate any repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

SOURCE = "37a0b9300a28e2f1fc19481a5351410709664302"
WORKER_SCRIPT = "portfolio-brain-recovery"
MAX_ROWS = 1000
MAX_EXPECTED = 80
MAX_WINDOW_SECONDS = 8 * 3600
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.0{1,6})?Z\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")

# Official Cloudflare Analytics GraphQL workersInvocationsAdaptive dataset.
# The caller must obtain a response using existing authorized READ access;
# never store or pass any token to the GitHub reviewer or this module.
QUERY = """query OriginalWorkerInvocations(
  $accountTag: string, $datetimeStart: string,
  $datetimeEnd: string, $scriptName: string
) {
  viewer {
    accounts(filter: { accountTag: $accountTag }) {
      workersInvocationsAdaptive(
        limit: 1000
        filter: {
          scriptName: $scriptName
          datetime_geq: $datetimeStart
          datetime_leq: $datetimeEnd
        }
      ) {
        dimensions { datetime scriptName status }
        sum { requests errors }
      }
    }
  }
}"""


class _Hold(ValueError):
    pass


@dataclass(frozen=True)
class Result:
    status: str
    reason: str
    expected_signed_dispatches: int = 0
    matched_original_invocations: int = 0
    github_writes: int = 0
    authenticated_cloudflare_provider: bool = False
    source_acceptance_issued: bool = False
    merge_authorized: bool = False


def _need(ok, code):
    if not ok:
        raise _Hold(code)


def _utc(value):
    _need(type(value) is str and _TIME.fullmatch(value) is not None,
          "UTC_TIMESTAMP_MALFORMED")
    try:
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ"
        return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
    except ValueError:
        raise _Hold("UTC_TIMESTAMP_MALFORMED") from None


def _manifest(proof):
    _need(type(proof) is dict
          and proof.get("production_source") == SOURCE
          and proof.get("status") == "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED"
          and proof.get("acceptance_pass") is False
          and proof.get("release_or_merge_authorized") is False
          and proof.get("external_cloudflare_provider_accepted") is False
          and type(proof.get("completion_span_seconds")) is int
          and proof["completion_span_seconds"] >= 21600
          and type(proof.get("verified_original_cores")) is int
          and 13 <= proof["verified_original_cores"] <= MAX_EXPECTED
          and type(proof.get("terminal_replay")) is dict
          and proof["terminal_replay"].get("status")
              == "ORIGINAL_TERMINAL_RAW_SQLITE_REPLAY_VERIFIED"
          and proof["terminal_replay"].get("pending_events") == 0,
          "ORIGINAL_TERMINAL_SOURCE_PROOF_NOT_READY")
    records = proof.get("signed_cloudflare_origins")
    _need(type(records) is list
          and 1 <= len(records) <= MAX_EXPECTED
          and len(records) <= proof["verified_original_cores"],
          "ORIGINAL_SIGNED_ORIGIN_MANIFEST_MISSING")
    expected = {}
    run_ids = set()
    slots = set()
    last = None
    for record in records:
        _need(type(record) is dict
              and type(record.get("run_id")) is int
              and 0 < record["run_id"] < 10**16
              and type(record.get("slot")) is int
              and 0 <= record["slot"] < 10**12
              and type(record.get("artifact_sha256")) is str
              and _SHA256.fullmatch(record["artifact_sha256"]) is not None,
              "ORIGINAL_SIGNED_ORIGIN_INVALID")
        moment = _utc(record.get("scheduled_at"))
        _need(record["run_id"] not in run_ids
              and record["slot"] not in slots
              and moment not in expected
              and (last is None or moment > last),
              "ORIGINAL_SIGNED_ORIGIN_DUPLICATE_OR_UNORDERED")
        run_ids.add(record["run_id"])
        slots.add(record["slot"])
        expected[moment] = record
        last = moment
    _need((last - next(iter(expected))).total_seconds() <= MAX_WINDOW_SECONDS,
          "ORIGINAL_SIGNED_WINDOW_EXCEEDS_BOUND")
    return expected


def query_envelope(proof, *, account_tag):
    """Generate a bounded query, not an authenticated Cloudflare request."""
    expected = _manifest(proof)
    _need(type(account_tag) is str
          and re.fullmatch(r"[0-9a-f]{32}", account_tag) is not None,
          "ACCOUNT_ID_MALFORMED")
    stamps = sorted(expected)
    start = stamps[0] - timedelta(minutes=2)
    end = stamps[-1] + timedelta(minutes=2)
    _need((end - start).total_seconds() <= MAX_WINDOW_SECONDS,
          "QUERY_WINDOW_OVER_BUDGET")
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "query": QUERY,
        "variables": {
            "accountTag": account_tag,
            "scriptName": WORKER_SCRIPT,
            "datetimeStart": fmt(start),
            "datetimeEnd": fmt(end),
        },
    }


def compare_cloudflare_rows(github_proof, cloudflare_response):
    """Compare two purported provider records. No evidence-origin attestation.

    A positive Result only means their contents agree. An independent, trusted
    Cloudflare account reader must still prove that the response is ORIGINAL.
    """
    matched = 0
    count = 0
    try:
        expected = _manifest(github_proof)
        count = len(expected)
        _need(type(cloudflare_response) is dict
              and not cloudflare_response.get("errors"),
              "CLOUDFLARE_GRAPHQL_ERRORS_OR_RESPONSE_INVALID")
        data = cloudflare_response.get("data")
        viewer = data.get("viewer") if type(data) is dict else None
        accounts = viewer.get("accounts") if type(viewer) is dict else None
        _need(type(accounts) is list and len(accounts) == 1
              and type(accounts[0]) is dict,
              "CLOUDFLARE_ACCOUNT_IDENTITY_AMBIGUOUS")
        rows = accounts[0].get("workersInvocationsAdaptive")
        _need(type(rows) is list and 1 <= len(rows) <= MAX_ROWS,
              "CLOUDFLARE_INVOCATION_CENSUS_INVALID")
        observed = {}
        for row in rows:
            _need(type(row) is dict, "CLOUDFLARE_INVOCATION_ROW_INVALID")
            dimensions = row.get("dimensions")
            sums = row.get("sum")
            _need(type(dimensions) is dict and type(sums) is dict
                  and dimensions.get("scriptName") == WORKER_SCRIPT
                  and dimensions.get("status") == "success"
                  and type(sums.get("requests")) is int
                  and sums["requests"] == 1
                  and type(sums.get("errors")) is int
                  and sums["errors"] == 0,
                  "CLOUDFLARE_SCRIPT_COUNT_OR_ERROR_INVALID")
            moment = _utc(dimensions.get("datetime"))
            _need(moment in expected,
                  "CLOUDFLARE_EXTRA_OR_DIFFERENT_INVOCATION")
            _need(moment not in observed, "CLOUDFLARE_DUPLICATE_INVOCATION")
            observed[moment] = row
            matched += 1
        _need(len(observed) == count, "CLOUDFLARE_SIGNED_DISPATCH_MISSING")
        return Result(
            "CONTENT_MATCHED_PROVIDER_AUTHENTICATION_STILL_REQUIRED",
            "INDEPENDENT_ORIGINAL_CLOUDFLARE_GET_AND_GOVERNED_ACCEPTANCE_NOT_PERFORMED",
            count, matched)
    except _Hold as ex:
        return Result("HOLD", str(ex), count, 0)
    except Exception:
        # Malformed/untrusted structures never expose exception content.
        return Result("HOLD", "UNVERIFIED_PROVIDER_OR_INPUT_ERROR", count, 0)
