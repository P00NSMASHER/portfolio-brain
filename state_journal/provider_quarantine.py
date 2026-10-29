"""Fail-closed quarantine for immutable GitHub provider anomalies.

A quarantined reducer run is never eligible to provide canonical snapshot
authority or freshness credit. Entries are exact provider identities backed by
observed GitHub metadata; this is not a generic stale-run bypass.
"""
from __future__ import annotations

from typing import Any

from state_journal.contracts import require

QUARANTINED_REDUCER_RUNS = {
    37655516971: {
        "workflow_id": 370374321,
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "head_branch": "main",
        "head_sha": "18f3e3d5a9b3b8c9a3e64e118a7cd487a3551edb",
        "event": "workflow_run",
        "created_at": "2026-10-07T16:54:41Z",
        "updated_at": "2026-10-07T16:54:41Z",
        "reason": "GITHUB_PROVIDER_JOBLESS_QUEUE_GHOST",
    },
}


def reducer_run_is_quarantined(run_id: Any) -> bool:
    return type(run_id) is int and run_id in QUARANTINED_REDUCER_RUNS


def require_quarantined_reducer_identity(row: dict[str, Any]) -> dict[str, Any]:
    run_id = row.get("id")
    expected = QUARANTINED_REDUCER_RUNS.get(run_id)
    require(expected is not None, "queued reducer is not an explicitly quarantined provider anomaly")
    for key in ("workflow_id", "path", "head_branch", "head_sha", "event", "created_at", "updated_at"):
        require(row.get(key) == expected[key], f"quarantined reducer identity changed: {key}")
    return expected
