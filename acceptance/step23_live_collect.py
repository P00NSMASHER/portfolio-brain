#!/usr/bin/env python3
"""Collect strict Step-23 scheduled-soak evidence from one exact protected main."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from acceptance.final_acceptance import bind_receipt, validate_step23
from runtime.artifact_state import BudgetedHTTP
from state_journal.archive import archived_artifact_ids, load_active_manifest
from state_journal.contracts import strict_load
from state_journal.github_reducer import restore_snapshot
from state_journal.production_reader import _pending_events
from state_journal.transport import GitHubReader

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_ARTIFACTS = {
    "portfolio-state-reducer": ("portfolio-canonical-shadow-state",),
    "runtime-hourly-sync": ("portfolio-runtime-state",),
    "portfolio-autonomous-scheduler": ("portfolio-scheduler-state",),
    "hunter-autonomous-cycle": ("portfolio-hunter-state",),
    "agent-heartbeat-sweep": ("portfolio-agent-heartbeat-state",),
    "portfolio-cost-watchdog": ("portfolio-workflow-liveness",),
    "portfolio-notification-cycle": ("portfolio-notification-state",),
    "command-center-pages": ("portfolio-command-center-preview-", "portfolio-command-center-history"),
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GH:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.base = "https://api.github.com/repos/" + repo
        self.token = token
        self.http = BudgetedHTTP(token, max_requests=200, retries=0, backoff=0)

    def get(self, path: str) -> Any:
        if not path.startswith("/") or "://" in path or ".." in path.split("/"):
            raise RuntimeError("unsafe observer API path")
        return self.http.json(self.base + path)

    def bytes(self, path: str) -> bytes:
        if not path.startswith("/") or "://" in path or ".." in path.split("/"):
            raise RuntimeError("unsafe observer artifact path")
        return self.http.bytes(self.base + path)


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def zip_json(raw: bytes, basename: str) -> Any:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        matches = [n for n in z.namelist() if n.rsplit("/", 1)[-1] == basename]
        if len(matches) != 1:
            raise RuntimeError(f"{basename} missing/ambiguous in artifact ZIP: {matches}")
        return json.loads(z.read(matches[0]))


def select_artifact(gh: GH, workflow: str, run_id: int, exact_sha: str) -> tuple[dict[str, Any], bytes]:
    doc = gh.get(f"/actions/runs/{run_id}/artifacts?per_page=100")
    if doc.get("total_count", 0) >= 100:
        raise RuntimeError("run artifact listing incomplete at page bound")
    rows = [a for a in doc.get("artifacts", []) if a.get("expired") is False]
    prefixes = EVIDENCE_ARTIFACTS[workflow]
    selected = None
    for prefix in prefixes:
        # Prefer an exact artifact name before treating the value as a prefix.
        # This matters for watchdog runs, which intentionally publish both
        # "portfolio-workflow-liveness" and a pre-restore diagnostic whose
        # name begins with the same text.
        exact = [a for a in rows if a.get("name") == prefix]
        if len(exact) == 1:
            selected = exact[0]
            break
        if len(exact) > 1:
            raise RuntimeError(f"{workflow} run {run_id} exact artifact {prefix} ambiguous")
        matches = [a for a in rows if str(a.get("name") or "").startswith(prefix)]
        if len(matches) == 1:
            selected = matches[0]
            break
        if len(matches) > 1:
            raise RuntimeError(f"{workflow} run {run_id} artifact prefix {prefix} ambiguous")
    if selected is None:
        raise RuntimeError(f"{workflow} run {run_id} evidence artifact missing")
    source = selected.get("workflow_run", {})
    if source.get("id") != run_id or source.get("head_sha") != exact_sha or source.get("head_branch") != "main":
        raise RuntimeError(f"{workflow} run {run_id} artifact source identity mismatch")
    digest = selected.get("digest")
    if not (isinstance(digest, str) and digest.startswith("sha256:") and len(digest) == 71):
        raise RuntimeError(f"{workflow} run {run_id} provider digest invalid")
    raw = gh.bytes(f"/actions/artifacts/{selected['id']}/zip")
    observed = sha256_bytes(raw)
    if observed != digest:
        raise RuntimeError(
            f"{workflow} run {run_id} artifact digest mismatch provider={digest} downloaded={observed}"
        )
    return selected, raw


def pending_event_count(token: str) -> int:
    policy = strict_load((ROOT / "state_journal" / "POLICY.json").read_bytes())
    reader = GitHubReader(token, max_requests=policy["limits"]["max_read_requests"])
    artifacts = getattr(reader, "list_recent_journal_artifacts", reader.list_recent_artifacts)(
        policy["artifact_scan_start"], max_pages=policy["limits"]["max_artifact_pages"]
    )
    state = restore_snapshot(reader, artifacts, current_run=os.environ.get("GITHUB_RUN_ID", "step23-soak"))
    if state is None:
        raise RuntimeError("Step23 pending-event check found no canonical snapshot")
    archive_ids = archived_artifact_ids(load_active_manifest(ROOT))
    return len(_pending_events(state, artifacts, archived_ids=archive_ids))


def scheduled_runs(gh: GH, workflows: set[str], exact_sha: str, start: datetime) -> dict[str, list[dict[str, Any]]]:
    # A Step-23 window is intentionally small. Query only that bounded window so
    # one API page is a stable snapshot; do not re-read page 1 while new runs are
    # arriving, which previously turned normal progress into pagination drift.
    start_iso = start.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    created_filter = quote(f">={start_iso}", safe="")
    doc = gh.get(f"/actions/runs?branch=main&event=schedule&created={created_filter}&per_page=100")
    rows = doc.get("workflow_runs")
    if not isinstance(rows, list):
        raise RuntimeError("scheduled run listing malformed")
    total = doc.get("total_count", len(rows))
    if type(total) is not int or total < len(rows):
        raise RuntimeError("scheduled run listing total invalid")
    if total > 100:
        raise RuntimeError("scheduled run listing exceeds bounded one-page cap")

    seen: set[int] = set()
    previous_time = None
    out = {name: [] for name in workflows}
    for row in rows:
        created = parse_time(row["created_at"])
        run_id = int(row["id"])
        if run_id in seen or (previous_time is not None and created > previous_time):
            raise RuntimeError("scheduled run snapshot ordering invalid")
        previous_time = created
        seen.add(run_id)
        name = row.get("name")
        if name not in workflows or row.get("head_sha") != exact_sha or created < start:
            continue
        out[name].append(row)
    for name in out:
        out[name].sort(key=lambda r: (parse_time(r["created_at"]), int(r["id"])))
    return out

def evidence_window(rows: list[dict], minimum: int, workflow: str) -> list[dict]:
    # Scan every raw run for failures before selecting a bounded receipt set.
    # Additional successes do not need duplicate artifact downloads. Retain
    # cancellation successors and the newest dashboard/handler/Hunter samples.
    successes = [r for r in rows if r.get("status") == "completed" and r.get("conclusion") == "success"]
    selected = {r["id"]: r for r in successes[:minimum]}
    tail = minimum if workflow in {"portfolio-autonomous-scheduler", "hunter-autonomous-cycle"} else 1
    selected.update({r["id"]: r for r in successes[-tail:]})
    for row in rows:
        if row.get("conclusion") == "cancelled":
            successor = cancellation_is_coalesced(row, rows)
            if successor is None:
                raise RuntimeError("unresolved cancellation in evidence window")
            selected[row["id"]] = row
            selected[successor["id"]] = successor
    return sorted(selected.values(), key=lambda r: (parse_time(r["created_at"]), r["id"]))


def cancellation_is_coalesced(row: dict[str, Any], successors: list[dict[str, Any]]) -> dict[str, Any] | None:
    if row.get("conclusion") != "cancelled":
        return None
    created = parse_time(row["created_at"])
    completed = parse_time(row["updated_at"])
    # Only short, pre-work-style cancellations may be treated as coalesced.
    # Longer cancellations reset the soak rather than being relabeled.
    if (completed - created).total_seconds() > 90:
        return None
    later = [
        s for s in successors
        if s.get("status") == "completed"
        and s.get("conclusion") == "success"
        and parse_time(s["created_at"]) > created
    ]
    return later[0] if later else None


def find_real_resets(grouped: dict[str, list[dict[str, Any]]]) -> list[tuple[datetime, str]]:
    failures: list[tuple[datetime, str]] = []
    for workflow, rows in grouped.items():
        for row in rows:
            if row.get("status") != "completed":
                continue
            conclusion = row.get("conclusion")
            if conclusion == "success":
                continue
            if conclusion == "cancelled":
                successor = cancellation_is_coalesced(row, rows)
                if successor is not None:
                    continue
            failures.append(
                (
                    parse_time(row["updated_at"]),
                    f"{workflow} run {row['id']} conclusion={conclusion}",
                )
            )
    return sorted(failures, key=lambda item: item[0])


def find_real_reset(grouped: dict[str, list[dict[str, Any]]]) -> tuple[datetime, str] | None:
    failures = find_real_resets(grouped)
    return failures[-1] if failures else None

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--output-meta", type=Path, required=True)
    ap.add_argument("--output-receipt", type=Path, required=True)
    ap.add_argument("--timeout-seconds", type=int, default=15000)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    exact_sha = cfg["exact_main_sha"]
    workflows = set(cfg["required_workflows"])
    required_handlers = set(cfg["required_handler_types"])
    minimum = int(cfg["required_successes_per_workflow"])
    poll = int(cfg.get("poll_seconds", 45))
    max_resets = int(cfg.get("max_resets", 5))
    effective_start = parse_time(cfg["soak_start"])
    window_start = effective_start
    window_deadline = window_start + timedelta(seconds=int(cfg["max_soak_duration_seconds"]))
    remaining_window = (window_deadline - datetime.now(timezone.utc)).total_seconds()
    if remaining_window <= 0:
        raise RuntimeError("STEP23_SOAK_WINDOW_EXPIRED")
    token = os.environ["GITHUB_TOKEN"]
    gh = GH(os.environ["GITHUB_REPOSITORY"], token)
    deadline = time.monotonic() + min(args.timeout_seconds, remaining_window)
    resets: list[dict[str, Any]] = []
    artifact_cache: dict[tuple[str, int], tuple[dict[str, Any], bytes]] = {}

    def assert_main() -> None:
        observed = gh.get("/branches/main")["commit"]["sha"]
        if observed != exact_sha:
            raise RuntimeError(f"STEP23_MAIN_MOVED expected={exact_sha} observed={observed}")

    assert_main()
    pending_start = pending_event_count(token)
    print(json.dumps({"status": "SOAK_STARTED", "exact_main_sha": exact_sha, "pending_events_start": pending_start}))

    class PendingObservation(Exception):
        pass

    def waiting(value: dict) -> None:
        print(json.dumps(value, sort_keys=True))
        if args.once:
            value.update(schema_version="1.0.0", exact_main_sha=exact_sha,
                         configured_soak_start=cfg["soak_start"],
                         effective_soak_start=effective_start.isoformat(),
                         resets=resets, generated_at=iso_now(), acceptance_complete=False)
            args.output_meta.parent.mkdir(parents=True, exist_ok=True)
            args.output_meta.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
            raise PendingObservation()
        time.sleep(poll)

    try:
        while time.monotonic() < deadline:
            assert_main()
            grouped = scheduled_runs(gh, workflows, exact_sha, effective_start)
            reset_events = find_real_resets(grouped)
            if reset_events:
                previous_start = effective_start
                for reset_at, reason in reset_events:
                    resets.append(
                        {
                            "previous_start": previous_start.isoformat().replace("+00:00", "Z"),
                            "reset_at": reset_at.isoformat().replace("+00:00", "Z"),
                            "reason": reason,
                        }
                    )
                    previous_start = reset_at
                if len(resets) > max_resets:
                    raise RuntimeError("STEP23_MAX_RESETS_EXCEEDED")
                effective_start = reset_events[-1][0]
                pending_start = pending_event_count(token)
                print(json.dumps({
                    "status": "SOAK_RESET",
                    "reason": reset_events[-1][1],
                    "new_start": effective_start.isoformat().replace("+00:00", "Z"),
                    "reset_count": len(resets),
                }))
                continue

            success_counts = {
                name: sum(
                    1 for row in rows
                    if row.get("status") == "completed" and row.get("conclusion") == "success"
                )
                for name, rows in grouped.items()
            }
            if any(count < minimum for count in success_counts.values()):
                waiting({"status": "WAITING_FOR_SCHEDULED_CYCLES", "counts": success_counts})
                continue

            # Do not freeze a final window while an already-created included run is still active.
            active = [
                (name, row["id"])
                for name, rows in grouped.items()
                for row in rows
                if row.get("status") != "completed"
            ]
            if active:
                waiting({"status": "WAITING_FOR_INCLUDED_RUNS", "active": active})
                continue

            run_rows: list[dict[str, Any]] = []
            deep: dict[tuple[str, int], tuple[dict[str, Any], bytes]] = {}
            try:
                for workflow in sorted(workflows):
                    rows = evidence_window(grouped[workflow], minimum, workflow)
                    for row in rows:
                        conclusion = row.get("conclusion")
                        if conclusion == "success":
                            key = (workflow, int(row["id"]))
                            if key not in artifact_cache:
                                artifact_cache[key] = select_artifact(gh, workflow, int(row["id"]), exact_sha)
                            deep[key] = artifact_cache[key]
                            run_rows.append(
                                {
                                    "workflow": workflow,
                                    "event": "schedule",
                                    "classification": "SUCCESS",
                                    "classification_reason": "COMPLETED_SUCCESSFULLY_WITH_TRACEABLE_ARTIFACT",
                                    "conclusion": "success",
                                    "created_at": row["created_at"],
                                    "completed_at": row["updated_at"],
                                    "superseding_run_id": None,
                                    "run_id": int(row["id"]),
                                    "head_sha": exact_sha,
                                    "artifact_hash": deep[key][0]["digest"],
                                }
                            )
                        elif conclusion == "cancelled":
                            successor = cancellation_is_coalesced(row, rows)
                            if successor is None:
                                raise RuntimeError(f"unresolved cancellation {workflow} run {row['id']}")
                            run_rows.append(
                                {
                                    "workflow": workflow,
                                    "event": "schedule",
                                    "classification": "CANCELLED_COALESCED",
                                    "classification_reason": "SHORT_PREWORK_CANCELLATION_SUPERSEDED_BY_LATER_SUCCESS",
                                    "conclusion": "cancelled",
                                    "created_at": row["created_at"],
                                    "completed_at": row["updated_at"],
                                    "superseding_run_id": int(successor["id"]),
                                    "run_id": int(row["id"]),
                                    "head_sha": exact_sha,
                                    "artifact_hash": None,
                                }
                            )
                        else:
                            raise RuntimeError(f"unexpected non-success remained in final window: {workflow} {row['id']} {conclusion}")
            except RuntimeError as exc:
                waiting({"status": "WAITING_FOR_TRACEABLE_ARTIFACTS", "reason": str(exc)})
                continue

            run_rows.sort(key=lambda r: (parse_time(r["created_at"]), r["run_id"]))
            successes_by_workflow = {
                name: [r for r in run_rows if r["workflow"] == name and r["classification"] == "SUCCESS"]
                for name in workflows
            }

            # Three monotonic canonical samples, each from a successful scheduled reducer run.
            canonical_samples = []
            try:
                for row in successes_by_workflow["portfolio-state-reducer"][:minimum]:
                    meta, raw = deep[("portfolio-state-reducer", row["run_id"])]
                    snapshot = zip_json(raw, "snapshot.json")
                    canonical_samples.append(
                        {
                            "run_id": row["run_id"],
                            "observed_at": row["completed_at"],
                            "sequence": int(snapshot["sequence"]),
                            "state_hash": snapshot["state_hash"],
                            "source_sha": exact_sha,
                        }
                    )
            except Exception as exc:
                waiting({"status": "WAITING_FOR_CANONICAL_SAMPLES", "reason": str(exc)})
                continue

            # Real handler execution evidence must come from successful scheduled
            # scheduler runs. The exact Step-23 handler-proof schedule publishes a
            # dedicated artifact; normal scheduler receipts remain a conservative
            # fallback. Every consumed ZIP is independently rehashed.
            handler_evidence: list[dict[str, Any]] = []
            seen_handlers: set[tuple[str, str]] = set()
            try:
                for row in successes_by_workflow["portfolio-autonomous-scheduler"]:
                    meta, raw = deep[("portfolio-autonomous-scheduler", row["run_id"])]

                    artifacts = gh.get(f"/actions/runs/{row['run_id']}/artifacts?per_page=100").get("artifacts", [])
                    handler_rows = [
                        a for a in artifacts
                        if a.get("expired") is False and a.get("name") == "portfolio-step23-handler-acceptance"
                    ]
                    if len(handler_rows) > 1:
                        raise RuntimeError(f"scheduler run {row['run_id']} handler artifact ambiguous")
                    if len(handler_rows) == 1:
                        hmeta = handler_rows[0]
                        hdigest = hmeta.get("digest")
                        if not (isinstance(hdigest, str) and hdigest.startswith("sha256:") and len(hdigest) == 71):
                            raise RuntimeError(f"scheduler run {row['run_id']} handler provider digest invalid")
                        hraw = gh.bytes(f"/actions/artifacts/{hmeta['id']}/zip")
                        hobserved = sha256_bytes(hraw)
                        if hobserved != hdigest:
                            raise RuntimeError(
                                f"scheduler run {row['run_id']} handler artifact digest mismatch provider={hdigest} downloaded={hobserved}"
                            )
                        proof = zip_json(hraw, "step23_handler_acceptance.json")
                        if proof.get("status") != "PASS" or proof.get("main_sha") != exact_sha:
                            raise RuntimeError(f"scheduler run {row['run_id']} handler proof invalid")
                        for receipt in proof.get("handler_executions") or []:
                            kind = receipt.get("kind")
                            execution_id = receipt.get("execution_id")
                            if kind not in required_handlers or receipt.get("status") != "SUCCESS":
                                continue
                            ident = (kind, str(execution_id))
                            if not execution_id or ident in seen_handlers:
                                continue
                            seen_handlers.add(ident)
                            handler_evidence.append(
                                {
                                    "kind": kind,
                                    "status": "COMPLETED",
                                    "run_id": row["run_id"],
                                    "execution_id": str(execution_id),
                                    "head_sha": exact_sha,
                                    "artifact_hash": hdigest,
                                    "result_kind": receipt.get("result_kind"),
                                }
                            )

                    receipts = zip_json(raw, "execution_receipts.json")
                    if not isinstance(receipts, list):
                        raise RuntimeError("scheduler execution_receipts.json is not a list")
                    for receipt in receipts:
                        kind = receipt.get("work_type")
                        execution_id = receipt.get("execution_id")
                        if kind not in required_handlers or receipt.get("status") != "SUCCESS":
                            continue
                        ident = (kind, str(execution_id))
                        if not execution_id or ident in seen_handlers:
                            continue
                        seen_handlers.add(ident)
                        handler_evidence.append(
                            {
                                "kind": kind,
                                "status": "COMPLETED",
                                "run_id": row["run_id"],
                                "execution_id": str(execution_id),
                                "head_sha": exact_sha,
                                "artifact_hash": meta["digest"],
                                "result_kind": receipt.get("result_kind"),
                            }
                        )
            except Exception as exc:
                waiting({"status": "WAITING_FOR_HANDLER_ARTIFACTS", "reason": str(exc)})
                continue
            handler_counts = {kind: sum(1 for r in handler_evidence if r["kind"] == kind) for kind in required_handlers}
            if any(handler_counts[kind] < 1 for kind in required_handlers):
                waiting({"status": "WAITING_FOR_REQUIRED_HANDLERS", "counts": handler_counts})
                continue

            # Hunter substantive work must be findings/proposals from successful scheduled Hunter cycles.
            hunter_evidence: list[dict[str, Any]] = []
            seen_hunter: set[str] = set()
            try:
                for row in successes_by_workflow["hunter-autonomous-cycle"]:
                    meta, raw = deep[("hunter-autonomous-cycle", row["run_id"])]
                    cycle = zip_json(raw, "hunt_cycle_receipt.json")
                    if cycle.get("status") != "PASS":
                        continue
                    candidates = []
                    for item in cycle.get("findings") or []:
                        if isinstance(item, dict) and item.get("finding_id"):
                            candidates.append(item["finding_id"])
                        elif isinstance(item, str) and item:
                            candidates.append(item)
                    for item in cycle.get("experiment_proposals") or []:
                        if isinstance(item, dict) and item.get("proposal_id"):
                            candidates.append(item["proposal_id"])
                        elif isinstance(item, str) and item:
                            candidates.append(item)
                    work_id = next((x for x in candidates if x not in seen_hunter), None)
                    if work_id is None:
                        continue
                    seen_hunter.add(work_id)
                    hunter_evidence.append(
                        {
                            "run_id": row["run_id"],
                            "work_id": work_id,
                            "substantive": True,
                            "heartbeat_only": False,
                            "head_sha": exact_sha,
                            "artifact_hash": meta["digest"],
                        }
                    )
            except Exception as exc:
                waiting({"status": "WAITING_FOR_HUNTER_ARTIFACTS", "reason": str(exc)})
                continue
            if not hunter_evidence:
                waiting({"status": "WAITING_FOR_SUBSTANTIVE_HUNTER_WORK"})
                continue

            # Latest successful scheduled command-center cycle must be recent and traceable.
            page_successes = successes_by_workflow["command-center-pages"]
            latest_page = page_successes[-1]
            dashboard_meta, _ = deep[("command-center-pages", latest_page["run_id"])]
            dashboard_age = (datetime.now(timezone.utc) - parse_time(latest_page["completed_at"])).total_seconds()
            dashboard_fresh = dashboard_age <= 5400
            if not dashboard_fresh:
                waiting({"status": "WAITING_FOR_FRESH_DASHBOARD", "age_seconds": dashboard_age})
                continue

            try:
                pending_final = pending_event_count(token)
            except Exception as exc:
                waiting({"status": "WAITING_FOR_PENDING_EVENT_CHECK", "reason": str(exc)})
                continue
            if pending_final != 0:
                waiting({"status": "WAITING_FOR_PENDING_EVENTS_TO_DRAIN", "pending": pending_final})
                continue

            assert_main()
            receipt = bind_receipt(
                {
                    "schema_version": "1.0.0",
                    "step": 23,
                    "status": "PASS",
                    "exact_main_sha": exact_sha,
                    "run_classification_policy": "EXPLICIT",
                    "hash_traceability_pass": True,
                    "dashboard_fresh": True,
                    "dashboard_hash": dashboard_meta["digest"],
                    "runs": run_rows,
                    "canonical_samples": canonical_samples,
                    "pending_events_start": pending_start,
                    "pending_events_final": 0,
                    "handler_execution_counts": handler_counts,
                    "handler_execution_evidence": handler_evidence,
                    "hunter_substantive_work_count": len(hunter_evidence),
                    "hunter_substantive_work_evidence": hunter_evidence,
                    "soak_start": effective_start.isoformat().replace("+00:00", "Z"),
                    "soak_window_start": window_start.isoformat().replace("+00:00", "Z"),
                    "soak_deadline": window_deadline.isoformat().replace("+00:00", "Z"),
                    "soak_resets": resets,
                    "generated_at": iso_now(),
                }
            )
            if datetime.now(timezone.utc) > window_deadline:
                raise RuntimeError("STEP23_SOAK_WINDOW_EXPIRED")
            validate_step23(receipt)
            meta = {
                "schema_version": "1.0.0",
                "status": "PASS",
                "exact_main_sha": exact_sha,
                "configured_soak_start": cfg["soak_start"],
                "effective_soak_start": receipt["soak_start"],
                "resets": resets,
                "observed_scheduled_run_ids": {name: [r["id"] for r in grouped[name]] for name in sorted(workflows)},
                "successful_run_counts": {
                    name: len(successes_by_workflow[name]) for name in sorted(workflows)
                },
                "handler_counts": handler_counts,
                "hunter_substantive_work_count": len(hunter_evidence),
                "pending_events_start": pending_start,
                "pending_events_final": 0,
                "receipt_hash": receipt["receipt_hash"],
                "generated_at": receipt["generated_at"],
            }
            args.output_meta.parent.mkdir(parents=True, exist_ok=True)
            args.output_meta.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            args.output_receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({"status": "PASS", "receipt_hash": receipt["receipt_hash"], "exact_main_sha": exact_sha}, sort_keys=True))
            return

    except PendingObservation:
        return

    raise RuntimeError("STEP23_SOAK_TIMEOUT")


if __name__ == "__main__":
    main()
