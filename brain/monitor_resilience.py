"""One bounded V7-only recheck of a GitHub default-branch snapshot race.

This is a GET-only, source-pinned recovery for a specific branch movement,
not a broad retry, a downgrade of provenance, or permission to persist a
partially collected observation. Original V6 behavior remains unchanged
until a separately authorized V7 release.
"""
from __future__ import annotations

from .adapters import policy
from .core import BrainError, require

# GitHub.observe: 1 repo GET, 2 branch GETs, up to 5 check-page GETs.
# Each operation can retry an HTTP transient once. Reserve 16 remaining
# GETs to bound the entire fresh observation even in the worst case.
_WORST_CASE_RECHECK_REQUESTS = 16
_REVISION_RACE = "SOURCE_REVISION_CHANGED"


def observe_after_bounded_revision_race(api, repository):
    """Return (complete provider observation, retry_used) or fail closed.

    The first attempt's unverified partial data is NEVER returned or written.
    Only one full, fresh, source-bound follow-up is allowed. No other error
    type, auth/rate limit, check coverage ambiguity, or public/private
    visibility failure is retried by this helper.
    """
    limits = policy()
    ceiling = limits["max_requests_per_operation"]
    require(type(ceiling) is int and ceiling == 24,
            "REVISION_RECHECK_POLICY_BUDGET_CHANGED")
    require(api.private is False and type(api.requests) is int
            and 0 <= api.requests <= ceiling,
            "REVISION_RECHECK_REQUIRES_BOUNDED_PUBLIC_READS")
    try:
        return api.observe(repository), False
    except BrainError as exc:
        # Exact fixed internal code, not a substring or user-input warning.
        if str(exc).partition(":")[0] != _REVISION_RACE:
            raise
        if ceiling - api.requests < _WORST_CASE_RECHECK_REQUESTS:
            raise BrainError(
                "SOURCE_REVISION_CHANGED: no safe full-snapshot retry budget"
            ) from None
        # A second branch movement, malformed response, auth issue or
        # exhausted budget remains a real failure. Never try a third time.
        return api.observe(repository), True


# A missing or racing source is scoped to that one repository. GitHub-wide
# access, rate, transport and unknown errors mean subsequent reads could be
# unauthorized or amplify a provider outage: stop the monitor. The original
# provider message MUST NOT be exported to reports, logs or GitHub artifacts.
_LOCAL_SOURCE_CODES = frozenset({
    "SOURCE_API_404", "SOURCE_REVISION_CHANGED",
    "SOURCE_REVISION_UNAVAILABLE", "SOURCE_RESPONSE_TOO_LARGE",
    "CHECK_COVERAGE_UNAVAILABLE", "CHECK_COVERAGE_TRUNCATED",
    "CHECK_COVERAGE_CHANGED", "CHECK_COVERAGE_AMBIGUOUS",
})
_LOCAL_SCOPE = "REPOSITORY_LOCAL_READ_FAILED"
_GLOBAL_SCOPE = "GLOBAL_OR_UNCLASSIFIED_SOURCE_STOP"


def public_monitor_failure_scope(exc):
    """Fixed, failure-only scope, based on known local GitHub read contracts.

    No arbitrary exception class, provider message or HTTP header is copied
    to result content. Unknown codes (including near matches) always stop.
    """
    if isinstance(exc, BrainError):
        code = str(exc).partition(":")[0]
        if code in _LOCAL_SOURCE_CODES:
            return _LOCAL_SCOPE
    return _GLOBAL_SCOPE
