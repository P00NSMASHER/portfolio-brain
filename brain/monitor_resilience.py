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
