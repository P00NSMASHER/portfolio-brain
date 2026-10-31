"""Fail-closed, source-specific predecessor admission for issuer-pinned PR checks.

Called by the *trusted-main*, independently credentialed verifier before it
publishes portfolio-phase1-gate. An ordinary branch, push, PR comment, or prior
source receipt never substitutes for an original 12-hour attestation.
This module performs read-only original GitHub GETs, bounded to five routes.
"""
from __future__ import annotations

import re
import urllib.error
from typing import Callable, Any

from brain.v9.guarded_merge import Denied, accepted_source, REPO

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DATE = r"[0-9]{8}"
_PREFIX = "repos/" + REPO + "/"
_MAX_READS = 8


class SourceAdmissionError(RuntimeError):
    """Sanitized denial. Never contains tokens or provider response bodies."""


def _allowed_route(route: str, main: str) -> bool:
    short = main[:8]
    return (
        route == "git/matching-refs/heads/brain-acceptance-" + short + "-"
        or re.fullmatch(r"git/commits/[0-9a-f]{40}", route) is not None
        or re.fullmatch(r"compare/" + main + r"\.\.\.[0-9a-f]{40}", route) is not None
        or re.fullmatch(
            r"contents/acceptance/finish-soak-" + short + r"-" + _DATE
            + r"\.json\?ref=[0-9a-f]{40}", route,
        ) is not None
        or re.fullmatch(r"commits/[0-9a-f]{40}/check-runs\?per_page=100", route) is not None
    )


def verify_predecessor_acceptance(
    main_sha: str, read: Callable[[str], Any],
) -> dict[str, str]:
    """Require genuine exact-source App5121826 attestation, or deny ALL PRs.

    The existing guarded admission verifier validates an exact-one-child
    acceptance branch, immutable receipt blob, 43,200 completed seconds,
    terminal follow-through and independent issuer-pinned check/receipt hash.
    A separate API principal supplies the original read-only provider GETs.
    """
    if type(main_sha) is not str or _SHA.fullmatch(main_sha) is None:
        raise SourceAdmissionError("SOURCE_SHA_INVALID")
    if not callable(read):
        raise SourceAdmissionError("SOURCE_READ_PRINCIPAL_MISSING")

    class OriginalGitHub:
        calls = 0

        def get(self, path: str) -> Any:
            if type(path) is not str or not path.startswith(_PREFIX):
                raise SourceAdmissionError("SOURCE_API_ROUTE_DENIED")
            route = path[len(_PREFIX):]
            if not _allowed_route(route, main_sha):
                raise SourceAdmissionError("SOURCE_API_ROUTE_DENIED")
            if self.calls >= _MAX_READS:
                raise SourceAdmissionError("SOURCE_API_READ_CAP_EXCEEDED")
            self.calls += 1
            try:
                return read("/" + route)
            except urllib.error.HTTPError as error:
                # The existing reader maps 404 to a distinct *not yet
                # accepted* state. All other HTTP statuses deny, no retry.
                if error.code == 404:
                    raise Denied("HTTP_404") from None
                raise SourceAdmissionError("SOURCE_API_UNAVAILABLE") from None
            except (OSError, TimeoutError, ValueError, TypeError):
                raise SourceAdmissionError("SOURCE_API_UNAVAILABLE") from None

    try:
        return accepted_source(OriginalGitHub(), main_sha)
    except Denied as error:
        # All cases are fail closed; print only fixed producer denial codes.
        code = str(error)
        if not re.fullmatch(r"[A-Z0-9_]{1,90}", code):
            code = "SOURCE_ACCEPTANCE_UNVERIFIED"
        raise SourceAdmissionError(code) from None
