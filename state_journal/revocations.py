"""Exact provider identities that are permanently non-authoritative.

This is intentionally a closed, code-reviewed denylist for provider records
that cannot be deleted but whose identity has been independently proven.
Unknown runs are never covered by this exception.
"""
from __future__ import annotations

from typing import Any

from state_journal.contracts import require

REDUCER_PATH = ".github/workflows/portfolio-state-reducer.yml"
REVOKED_REDUCER_SOURCES = {
    37655516971: "18f3e3d5a9b3b8c9a3e64e118a7cd487a3551edb",
}


def revoked_reducer_source(source: dict[str, Any], *, require_path: bool = False) -> bool:
    """Return True only for an exact reviewed reducer run/SHA identity."""
    run_id = source.get("id")
    expected_sha = REVOKED_REDUCER_SOURCES.get(run_id)
    if expected_sha is None:
        return False
    require(source.get("head_branch") == "main", "Revoked reducer source branch identity mismatch")
    require(source.get("head_sha") == expected_sha, "Revoked reducer source SHA identity mismatch")
    if require_path:
        require(source.get("path") == REDUCER_PATH, "Revoked reducer source workflow identity mismatch")
    return True


def revoked_reducer_run(run: dict[str, Any]) -> bool:
    return revoked_reducer_source(run, require_path=True)
