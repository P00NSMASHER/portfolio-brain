"""Independent, fail-closed Portfolio Brain soak evidence evaluator.

The evaluator NEVER creates workload success. Its inputs must come from separate
GitHub API reads and cryptographically verified artifacts. Manual dispatches do
not earn automatic-delivery credit. Intended for a read-only acceptance auditor,
not the workload producer or the authoritative acceptance receipt writer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import zipfile

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_STEPS = frozenset({
    "Bind execution to unchanged current main",
    "Restore dedicated durable state branch",
    "Validate restoration and capture publication parent",
    "Exact-SHA deterministic preflight",
    "Read-only public project monitoring",
    "Bounded public code and opportunity research",
    "Evidence-bound deterministic experiment",
    "Verify authoritative state and zero event backlog",
    "Verify main and state parent before publication",
    "Publish one nonsecret state transaction without force",
    "Preserve verifiable execution evidence",
})
MIN_CYCLES = 3
MIN_SPAN_SECONDS = 7200
V5_MIN_SPAN_SECONDS = 21600  # Six hours on one exact protected source.
MAX_GAP_SECONDS = 5400

class EvidenceError(ValueError):
    """Unverifiable evidence is a BLOCKED result, never an inferred PASS."""

def require(condition, code):
    if not condition:
        raise EvidenceError(code)

def utc(value):
    require(isinstance(value, str) and value.endswith("Z"), "TIME_MUST_BE_EXPLICIT_UTC")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EvidenceError("TIME_INVALID") from exc
    require(result.utcoffset().total_seconds() == 0, "TIME_NOT_UTC")
    return result

def sha40(value):
    require(isinstance(value, str) and HEX40.fullmatch(value), "GIT_SHA_INVALID")
    return value

def sha64(value):
    require(isinstance(value, str) and HEX64.fullmatch(value), "SHA256_INVALID")
    return value

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def verify_sqlite(path, *, expected_sequence, expected_chain, expected_source):
    """Read immutable downloaded state without opening a writable DB or trusting reports.

    The caller must separately bind bytes to the GitHub state commit it fetched.
    Opening an arbitrary user-supplied DB path is not proof of remote publication.
    """
    sha40(expected_source)
    sha64(expected_chain)
    require(type(expected_sequence) is int and expected_sequence >= 0, "SEQUENCE_INVALID")
    raw = Path(path).read_bytes()
    require(0 < len(raw) <= 25_000_000, "STATE_SIZE_INVALID")
    sqlite_sha256 = hashlib.sha256(raw).hexdigest()
    conn = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        require(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLITE_CORRUPT")
        schema = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        visibility = conn.execute("SELECT value FROM meta WHERE key='visibility'").fetchone()
        require(schema and schema[0] == "2" and visibility and visibility[0] == "PUBLIC", "STATE_SCHEMA_OR_VISIBILITY_INVALID")
        rows = conn.execute("SELECT e.*,l.prev_hash,l.chain_hash FROM events e LEFT JOIN ledger l USING(seq) ORDER BY seq").fetchall()
        watermark = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
        require((watermark[0] if watermark else 0) == len(rows), "STATE_EVENT_TAIL_MISSING")
        require(len(rows) == expected_sequence, "STATE_SEQUENCE_MISMATCH")
        require(conn.execute("SELECT count(*) FROM events WHERE status='PENDING'").fetchone()[0] == 0, "STATE_PENDING_EVENTS")
        require(conn.execute("SELECT count(*) FROM ledger").fetchone()[0] == len(rows), "STATE_LEDGER_MISMATCH")
        prior = "0" * 64
        for seq, row in enumerate(rows, start=1):
            require(row["seq"] == seq and row["status"] == "APPLIED", "STATE_EVENT_GAP")
            try:
                event = json.loads(row["body"])
            except (ValueError, TypeError) as exc:
                raise EvidenceError("STATE_EVENT_JSON_INVALID") from exc
            require(event.get("visibility") == "PUBLIC" and row["id"] == event.get("id"), "STATE_EVENT_IDENTITY_INVALID")
            require(digest(event) == row["hash"], "STATE_EVENT_DIGEST_INVALID")
            require(row["prev_hash"] == prior, "STATE_CHAIN_PARENT_INVALID")
            prior = digest({"seq": seq, "event_hash": row["hash"], "previous": prior})
            require(row["chain_hash"] == prior, "STATE_CHAIN_DIGEST_INVALID")
        require(prior == expected_chain, "STATE_CANONICAL_HASH_MISMATCH")
        latest = conn.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        require(latest is not None, "STATE_REPORT_MISSING")
        report = json.loads(latest["body"])
        require(digest(report) == latest["hash"], "STATE_REPORT_DIGEST_INVALID")
        require(latest["seq"] == expected_sequence and latest["chain_hash"] == prior, "STATE_REPORT_LINEAGE_INVALID")
        require(latest["source_sha"] == expected_source, "STATE_REPORT_SOURCE_INVALID")
        require(report.get("pending_events") == 0 and report.get("status") == "PASS", "STATE_REPORT_NOT_READY")
        require(report.get("state_sequence") == expected_sequence and report.get("canonical_hash") == prior, "STATE_REPORT_FACTS_INVALID")
        return {"status": "PASS", "sha256": sqlite_sha256, "sequence": expected_sequence,
                "canonical_hash": prior, "pending_events": 0, "source_sha": expected_source}
    except sqlite3.DatabaseError as exc:
        raise EvidenceError("SQLITE_READ_FAILED") from exc
    finally:
        conn.close()

def verify_artifact(path, expected_digest, *, run_id, source_sha, state_parent, state_commit):
    """Check GitHub API artifact SHA256 and embedded real delivery/doctor receipts."""
    sha40(source_sha)
    sha40(state_parent)
    sha40(state_commit)
    require(type(run_id) is int and run_id > 0, "RUN_ID_INVALID")
    require(isinstance(expected_digest, str) and expected_digest.startswith("sha256:"), "ARTIFACT_DIGEST_FORMAT")
    sha64(expected_digest[7:])
    raw = Path(path).read_bytes()
    require(0 < len(raw) < 20_000_000, "ARTIFACT_SIZE_INVALID")
    require(hashlib.sha256(raw).hexdigest() == expected_digest[7:], "ARTIFACT_SHA256_MISMATCH")
    try:
        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()
            require(len(names) <= 100 and len(set(names)) == len(names), "ARTIFACT_DUPLICATE_OR_UNBOUNDED")
            require(all(not n.startswith("/") and ".." not in Path(n).parts for n in names), "ARTIFACT_UNSAFE_PATH")
            require(sum(i.file_size for i in z.infolist()) <= 4_000_000, "ARTIFACT_UNBOUNDED_UNCOMPRESSED")
            require(all(n in names for n in ("delivery.json", "doctor/report.json", "preflight/report.json")), "ARTIFACT_MISSING_REQUIRED_REPORT")
            delivery = json.loads(z.read("delivery.json"))
            doctor = json.loads(z.read("doctor/report.json"))
            preflight = json.loads(z.read("preflight/report.json"))
    except (zipfile.BadZipFile, ValueError, KeyError, OSError) as exc:
        raise EvidenceError("ARTIFACT_READ_FAILED") from exc
    require(delivery.get("source_sha") == source_sha and delivery.get("run_id") == str(run_id), "DELIVERY_SOURCE_OR_RUN_MISMATCH")
    require(delivery.get("state_parent") == state_parent and delivery.get("state_commit") == state_commit, "DELIVERY_STATE_LINEAGE_INVALID")
    require(delivery.get("publication_verified") is True and delivery.get("soak_completed") is False, "DELIVERY_NOT_VERIFIED")
    require(doctor.get("status") == "PASS" and doctor.get("pending_events") == 0, "DOCTOR_NOT_PASS")
    require(doctor.get("source_sha") == source_sha and preflight.get("source_sha") == source_sha, "ARTIFACT_REPORT_SHA_MISMATCH")
    require(preflight.get("status") == "PASS" and preflight.get("live_sources") == "NOT_TESTED", "PREFLIGHT_EVIDENCE_INVALID")
    require(doctor.get("workflow_delivery") == "NOT_TESTED_BY_LOCAL_DOCTOR", "DOCTOR_SCOPE_MISREPRESENTED")
    sha64(doctor.get("canonical_hash"))
    require(type(doctor.get("state_sequence")) is int, "DOCTOR_SEQUENCE_INVALID")
    return {"status": "PASS", "state_sequence": doctor["state_sequence"],
            "canonical_hash": doctor["canonical_hash"], "pending_events": 0,
            "artifact_sha256": expected_digest[7:]}

def verify_v5_artifact(path, expected_digest, *, run_id, source_sha,
                       state_parent, state_commit):
    """Require original ZIP integrity and all four mandatory workload receipts.

    This is a *local read-only* consistency check of provider-supplied bytes.
    A matching expected_digest is meaningful only if independently acquired
    from GitHub; the ZIP itself cannot prove its Cloudflare scheduler origin.
    """
    basic = verify_artifact(
        path, expected_digest, run_id=run_id, source_sha=source_sha,
        state_parent=state_parent, state_commit=state_commit,
    )
    try:
        with zipfile.ZipFile(path, "r") as archive:
            require(archive.testzip() is None, "V5_ARTIFACT_MEMBER_CRC_INVALID")
            names = set(archive.namelist())
            required = ("report/report.json", "research/report.json",
                        "experiment/report.json", "doctor/report.json")
            require(all(name in names for name in required),
                    "V5_WORKLOAD_RECEIPT_MISSING")
            docs = [json.loads(archive.read(name)) for name in required]
    except EvidenceError:
        # EvidenceError derives from ValueError. Preserve explicit fail-closed
        # missing-report and CRC error codes instead of relabeling them.
        raise
    except (zipfile.BadZipFile, ValueError, KeyError, OSError, RuntimeError) as exc:
        raise EvidenceError("V5_WORKLOAD_RECEIPT_UNREADABLE") from exc
    require(all(type(doc) is dict for doc in docs),
            "V5_WORKLOAD_RECEIPT_NOT_OBJECT")
    for kind, doc in zip(("monitor", "research", "experiment", "doctor"), docs):
        require(doc.get("status") == "PASS"
                and doc.get("source_sha") == source_sha
                and doc.get("pending_events") == 0,
                "V5_WORKLOAD_RECEIPT_NOT_PASS_" + kind.upper())
        require(type(doc.get("state_sequence")) is int
                and doc["state_sequence"] >= 0,
                "V5_WORKLOAD_SEQUENCE_INVALID")
        sha64(doc.get("canonical_hash"))
    monitor, research, experiment, doctor = docs
    require(
        type(monitor.get("operation")) is dict
        and monitor["operation"].get("name") == "monitor"
        and type(research.get("operation")) is dict
        and research["operation"].get("name") == "research",
        "V5_WORKLOAD_OPERATION_INVALID",
    )
    sequences = [doc["state_sequence"] for doc in docs]
    require(sequences == sorted(sequences)
            and experiment["state_sequence"] == doctor["state_sequence"]
            and doctor["state_sequence"] == basic["state_sequence"],
            "V5_WORKLOAD_SEQUENCE_DISAGREEMENT")
    require(experiment["canonical_hash"] == doctor["canonical_hash"]
            == basic["canonical_hash"],
            "V5_EXPERIMENT_DOCTOR_CHAIN_DISAGREEMENT")
    require(doctor.get("mandatory_workloads") == {
        "monitor": "PASS", "research": "PASS", "experiment": "PASS",
    }, "V5_DOCTOR_MANDATORY_WORKLOADS_INVALID")
    return {
        **basic,
        "workload_reports": "PASS",
        "member_crc": "PASS",
        "workload_sequences": {
            "monitor": sequences[0], "research": sequences[1],
            "experiment": sequences[2], "doctor": sequences[3],
        },
    }


@dataclass(frozen=True)
class Evaluation:
    status: str
    reason: str
    automatic_run_ids: tuple[int, ...]
    span_seconds: int
    maximum_gap_observed: int

def evaluate_window(records, *, source_sha, current_main, first_state_parent,
                    started_at, deadline_at, now, min_span_seconds=MIN_SPAN_SECONDS):
    """Fail closed on *all* exact-source runs, including inconvenient failures.

    Records are externally authenticated run/step/artifact/state attestations. This
    method intentionally cannot certify that unverified JSON originated at GitHub.
    """
    require(type(min_span_seconds) is int and min_span_seconds >= MIN_SPAN_SECONDS,
            "SOAK_MINIMUM_DURATION_INVALID")
    sha40(source_sha)
    sha40(current_main)
    sha40(first_state_parent)
    if source_sha != current_main:
        return Evaluation("FAIL", "MAIN_DRIFT", (), 0, 0)
    start, deadline, instant = utc(started_at), utc(deadline_at), utc(now)
    require(start < deadline and start <= instant, "SOAK_WINDOW_INVALID")
    require(isinstance(records, list), "SOAK_RECORDS_INVALID")
    if not records:
        return Evaluation("BLOCKED" if instant >= deadline else "WAITING", "NO_CYCLES", (), 0, 0)
    seen = set()
    applicable = []
    for r in records:
        require(type(r) is dict, "CYCLE_INVALID")
        run_id, attempt = r.get("run_id"), r.get("attempt")
        require(type(run_id) is int and run_id > 0 and type(attempt) is int and attempt >= 1, "CYCLE_ID_INVALID")
        require((run_id, attempt) not in seen, "CYCLE_DUPLICATE_ATTEMPT")
        seen.add((run_id, attempt))
        begin = utc(r.get("started_at"))
        unfinished = r.get("status") in {"queued", "in_progress", "pending", "waiting", "requested"}
        end = begin if unfinished and r.get("completed_at") is None else utc(r.get("completed_at"))
        # A completed automatic baseline anchors the acceptance start, even when
        # its verified execution began seconds before the recorded baseline time.
        require(begin <= end <= instant and end >= start, "CYCLE_TIME_INVALID")
        require(r.get("source_sha") == source_sha, "CYCLE_SOURCE_DRIFT")
        applicable.append((begin, end, r))
    applicable.sort(key=lambda x: (x[0], x[2]["run_id"], x[2]["attempt"]))
    automatic = []
    previous_state = first_state_parent
    prev_sequence = None
    for begin, end, r in applicable:
        if r.get("status") in {"queued", "in_progress", "pending", "waiting", "requested"}:
            return Evaluation("BLOCKED" if instant >= deadline else "WAITING", "CORE_EXECUTION_INCOMPLETE", tuple(x[1] for x in automatic), 0, 0)
        if r.get("status") != "completed" or r.get("conclusion") != "success":
            return Evaluation("FAIL", "CORE_EXECUTION_FAILED", tuple(x[1] for x in automatic), 0, 0)
        steps = r.get("steps")
        if type(steps) is not dict or any(steps.get(step) != "success" for step in REQUIRED_STEPS):
            return Evaluation("FAIL", "MANDATORY_STEP_FAILED_OR_MISSING", tuple(x[1] for x in automatic), 0, 0)
        artifact = r.get("artifact")
        if not isinstance(artifact, dict) or artifact.get("status") != "PASS":
            return Evaluation("BLOCKED", "ARTIFACT_NOT_VERIFIED", tuple(x[1] for x in automatic), 0, 0)
        state = r.get("state")
        if not isinstance(state, dict) or state.get("status") != "PASS":
            return Evaluation("BLOCKED", "REMOTE_STATE_NOT_VERIFIED", tuple(x[1] for x in automatic), 0, 0)
        if state.get("parent") != previous_state or not isinstance(state.get("commit"), str) or not HEX40.fullmatch(state["commit"]):
            return Evaluation("FAIL", "STATE_PARENT_CHAIN_BROKEN", tuple(x[1] for x in automatic), 0, 0)
        if state.get("sequence") != artifact.get("state_sequence") or state.get("canonical_hash") != artifact.get("canonical_hash"):
            return Evaluation("FAIL", "STATE_AND_ARTIFACT_DISAGREE", tuple(x[1] for x in automatic), 0, 0)
        if prev_sequence is not None and state["sequence"] < prev_sequence:
            return Evaluation("FAIL", "STATE_SEQUENCE_REGRESSED", tuple(x[1] for x in automatic), 0, 0)
        prev_sequence, previous_state = state["sequence"], state["commit"]
        if r.get("event") == "schedule":
            automatic.append((end, r["run_id"]))
        elif r.get("event") == "workflow_dispatch":
            # No self-declared boolean can turn a manual dispatch into an automatic run.
            clock = r.get("external_clock")
            if isinstance(clock, dict) and clock.get("kind") == "scheduled" and clock.get("independently_verified") is True and clock.get("actual_task_execution_verified") is True and clock.get("clock_job_verified") is True and clock.get("core_receipt_verified") is True and clock.get("source_sha") == source_sha:
                automatic.append((end, r["run_id"]))
            elif (isinstance(clock, dict) and clock.get("kind") == "github_schedule"
                    and clock.get("source_sha") == source_sha
                    and type(clock.get("clock_run_id")) is int and clock["clock_run_id"] > 0
                    and clock.get("provider_scheduler_verified") is True
                    and clock.get("clock_job_verified") is True
                    and clock.get("core_receipt_verified") is True
                    and clock.get("core_actor_verified") is True):
                # These booleans MUST come from the independent provider collector;
                # the pure evaluator can only return PRE_POSTVALIDATION, never PASS.
                automatic.append((end, r["run_id"]))
            elif (isinstance(clock, dict) and clock.get("kind") == "cloudflare_cron_v1"
                    and clock.get("source_sha") == source_sha
                    and clock.get("provider_cron_verified") is True
                    and clock.get("signed_origin_verified") is True
                    and clock.get("core_receipt_verified") is True
                    and clock.get("state_verified") is True):
                # These are independent provider/ZIP/SQLite attestations, never
                # assertions manufactured by the workload producer itself.
                automatic.append((end, r["run_id"]))
        elif r.get("event") != "push":
            return Evaluation("FAIL", "UNEXPECTED_CORE_EVENT", tuple(x[1] for x in automatic), 0, 0)
    automatic.sort()
    ids = tuple(x[1] for x in automatic)
    gaps = [int((automatic[i][0] - automatic[i-1][0]).total_seconds()) for i in range(1,len(automatic))]
    maximum = max(gaps, default=0)
    span = int((automatic[-1][0]-automatic[0][0]).total_seconds()) if automatic else 0
    if maximum > MAX_GAP_SECONDS:
        return Evaluation("FAIL","AUTOMATIC_DELIVERY_GAP_EXCEEDED",ids,span,maximum)
    # A missed second/third cycle is already a terminal failure at the original
    # 90-minute gap, even when fewer than three runs have arrived.
    # Once the two-hour span is legitimately complete, proceed to postvalidation.
    if automatic and span < min_span_seconds:
        elapsed_since_latest=(instant-automatic[-1][0]).total_seconds()
        if elapsed_since_latest > MAX_GAP_SECONDS:
            return Evaluation("FAIL","AUTOMATIC_DELIVERY_GAP_EXCEEDED",ids,span,
                              max(maximum,int(elapsed_since_latest)))
    if len(automatic) < MIN_CYCLES:
        return Evaluation("BLOCKED" if instant >= deadline else "WAITING",
                          "INSUFFICIENT_GENUINE_AUTOMATIC_CYCLES",ids,span,maximum)
    if span < min_span_seconds:
        return Evaluation("BLOCKED" if instant >= deadline else "WAITING", "SOAK_DURATION_INCOMPLETE", ids, span, maximum)
    if instant > deadline:
        return Evaluation("BLOCKED", "DEADLINE_EXPIRED_BEFORE_POST_VALIDATION", ids, span, maximum)
    return Evaluation("PRE_POSTVALIDATION", "POST_SOAK_INDEPENDENT_CHECKS_REQUIRED", ids, span, maximum)


def evaluate_v5_window(records, *, inventory, source_sha, current_main,
                       first_state_parent, started_at, deadline_at, now):
    """Evaluate *six-hour* V5 evidence using the existing fail-closed reducer.

    An inventory and run manifests are caller-supplied data. This pure function
    cannot authenticate them against GitHub or Cloudflare, verify raw ZIP bytes,
    or create a terminal acceptance receipt. The most it can return is
    PRE_POSTVALIDATION; an independent provider/artifact/state auditor is still
    mandatory. V3's existing two-hour function remains backward compatible.
    """
    sha40(source_sha)
    start, deadline, instant = utc(started_at), utc(deadline_at), utc(now)
    require(
        (deadline - start).total_seconds() >= V5_MIN_SPAN_SECONDS,
        "V5_WINDOW_SHORTER_THAN_SIX_HOURS",
    )
    require(type(records) is list, "V5_RECORDS_INVALID")
    require(
        type(inventory) is dict
        and inventory.get("coverage_complete") is True
        and inventory.get("provenance") == "GITHUB_API_PROVIDER_METADATA"
        and inventory.get("soak_pass") is False
        and type(inventory.get("core_runs")) is list,
        "V5_PROVIDER_INVENTORY_REQUIRED",
    )
    # The preflight census is not a cryptographic proof. Still refuse a
    # manifest which has *obviously* dropped a reported failed/queued core.
    expected = set()
    provider_rows = {}
    for item in inventory["core_runs"]:
        require(type(item) is dict, "V5_PROVIDER_INVENTORY_ROW_INVALID")
        run_id, attempt = item.get("run_id"), item.get("run_attempt", 1)
        require(type(run_id) is int and run_id > 0
                and type(attempt) is int and attempt > 0,
                "V5_PROVIDER_RUN_ID_INVALID")
        identity = (run_id, attempt)
        require(identity not in expected, "V5_PROVIDER_DUPLICATE_RUN")
        expected.add(identity)
        provider_rows[identity] = item
        require(type(item.get("head_sha")) is str
                and HEX40.fullmatch(item["head_sha"]),
                "V5_PROVIDER_RUN_SOURCE_INVALID")
        require(item.get("event") in {"push", "schedule", "workflow_dispatch"},
                "V5_PROVIDER_RUN_TRIGGER_INVALID")
        require(item.get("status") in {
            "completed", "queued", "in_progress", "pending", "waiting",
            "requested",
        }, "V5_PROVIDER_RUN_STATUS_INVALID")
        require(item["head_sha"] == source_sha,
                "V5_PROVIDER_RUN_SOURCE_MISMATCH")
        require(
            type(item.get("conclusion")) is str
            if item["status"] == "completed"
            else item.get("conclusion") is None,
            "V5_PROVIDER_RUN_CONCLUSION_INVALID",
        )
        created = utc(item.get("created_at"))
        require(start <= created <= instant, "V5_PROVIDER_RUN_TIME_INVALID")
    manifest = set()
    for record in records:
        require(type(record) is dict, "V5_RUN_MANIFEST_ROW_INVALID")
        identity = (record.get("run_id"), record.get("attempt"))
        require(type(identity[0]) is int and type(identity[1]) is int,
                "V5_RUN_MANIFEST_ID_INVALID")
        require(identity not in manifest, "V5_RUN_MANIFEST_DUPLICATE")
        manifest.add(identity)
    require(manifest == expected, "V5_CENSUS_RECORD_MISMATCH")
    for record in records:
        provider = provider_rows[(record["run_id"], record["attempt"])]
        require(
            record.get("source_sha") == provider["head_sha"]
            and record.get("event") == provider["event"]
            and record.get("status") == provider["status"]
            and record.get("conclusion") == provider.get("conclusion"),
            "V5_PROVIDER_MANIFEST_FACT_MISMATCH",
        )
        require(
            utc(provider["created_at"]) <= utc(record.get("started_at")),
            "V5_PROVIDER_STARTED_BEFORE_CREATED",
        )

    # Runtime decisions, hashes, completion gaps and error classifications
    # are delegated to the existing (independently tested) strict reducer.
    # Never return PASS here, regardless of forged self-declared booleans.
    return evaluate_window(
        records, source_sha=source_sha, current_main=current_main,
        first_state_parent=first_state_parent, started_at=started_at,
        deadline_at=deadline_at, now=now,
        min_span_seconds=V5_MIN_SPAN_SECONDS,
    )
