"""V8 terminal-readiness reviewer. Read-only, source-pinned, no release authority.

Run from an isolated reviewed checkout with GH_TOKEN scoped to GitHub reads.
The optional SQLite replay requires separately checked-out immutable production
source and terminal state trees. Original Cloudflare provider corroboration
remains an independent, mandatory external check: this script never self-
certifies the complete acceptance or repairs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

REPOSITORY = "P00NSMASHER/portfolio-brain"
FINAL_SOURCE = "1a310ebfd0bf3aadffc74ae178582f0c235c9ab9"
MINIMUM_SPAN = 21_600
MAXIMUM_GAP = 5_400
MAX_PAGES = 10
MAX_ORIGINAL_RUNS = 80
MAX_ORIGINAL_GETS = 400
MAX_ZIP = 5_000_000
SOURCE_RE = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED_STEPS = (
    "Bind execution to unchanged current main",
    "Restore dedicated durable state branch",
    "Validate restoration and capture publication parent",
    "Exact-SHA deterministic preflight",
    "Read-only public project monitoring",
    "Bounded public code and opportunity research",
    "Evidence-bound deterministic experiment",
    "Verify authoritative state and zero event backlog",
    "Verify main and state parent before publication",
    "Verify and pack durable state into bounded Git blobs",
    "Publish one nonsecret state transaction without force",
    "Preserve verifiable execution evidence",
)
ORIGINS = (
    "Verify independently signed Cloudflare Cron provenance",
    "Validate GitHub-native watchdog scheduling origin",
    "Verify external clock provenance when supplied",
)


class Hold(ValueError):
    pass


def require(value, message):
    if not value:
        raise Hold(message)


def dt(value):
    require(type(value) is str and value.endswith("Z"), "UNTRUSTED_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise Hold("UNTRUSTED_TIMESTAMP") from None
    require(parsed.tzinfo == timezone.utc, "TIMESTAMP_NOT_UTC")
    return parsed


def strict_json(raw):
    def unique(rows):
        value = {}
        for key, item in rows:
            require(key not in value, "DUPLICATE_ORIGINAL_JSON_KEY")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)


class OriginalGitHub:
    """Only original GitHub GET endpoints; no GitHub mutations or user URLs."""

    def __init__(self):
        require(bool(os.environ.get("GH_TOKEN")), "GITHUB_READ_TOKEN_UNAVAILABLE")
        self.calls = 0

    @staticmethod
    def allowed(suffix):
        return bool(
            suffix == "branches/main"
            or re.fullmatch(r"actions/runs\?per_page=100&page=[1-9][0-9]?", suffix)
            or re.fullmatch(r"actions/runs/[1-9][0-9]{0,15}", suffix)
            or re.fullmatch(r"actions/runs/[1-9][0-9]{0,15}/jobs\?per_page=100", suffix)
            or re.fullmatch(r"actions/runs/[1-9][0-9]{0,15}/artifacts\?per_page=100", suffix)
            or re.fullmatch(r"git/commits/[0-9a-f]{40}", suffix)
        )

    def get(self, suffix):
        require(self.calls < MAX_ORIGINAL_GETS and self.allowed(suffix),
                "ORIGINAL_PROVIDER_REQUEST_OUT_OF_SCOPE")
        self.calls += 1
        path = "repos/" + REPOSITORY + "/" + suffix
        try:
            raw = subprocess.check_output(["gh", "api", path], timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            raise Hold("ORIGINAL_PROVIDER_GET_UNAVAILABLE") from None
        require(len(raw) <= 6_000_000, "ORIGINAL_RESPONSE_TOO_LARGE")
        return strict_json(raw)

    def artifact_zip(self, artifact_id):
        require(type(artifact_id) is int and 0 < artifact_id < 10**16,
                "ORIGINAL_ARTIFACT_ID_INVALID")
        self.calls += 1
        require(self.calls <= MAX_ORIGINAL_GETS, "ORIGINAL_READ_BUDGET_EXCEEDED")
        path = "repos/" + REPOSITORY + "/actions/artifacts/" + str(artifact_id) + "/zip"
        try:
            data = subprocess.check_output(["gh", "api", path], timeout=45)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            raise Hold("ORIGINAL_ARTIFACT_DOWNLOAD_UNAVAILABLE") from None
        require(0 < len(data) <= MAX_ZIP, "ORIGINAL_ZIP_NOT_BOUNDED")
        return data


def original_census(api):
    """List ALL workflows until earlier than first same-source core."""
    rows = []
    reached_older_source = False
    for page in range(1, MAX_PAGES + 1):
        result = api.get(f"actions/runs?per_page=100&page={page}")
        events = result.get("workflow_runs") if type(result) is dict else None
        require(type(result) is dict and type(result.get("total_count")) is int
                and type(events) is list and all(type(x) is dict for x in events),
                "ORIGINAL_RUN_LIST_SCHEMA")
        if not events:
            reached_older_source = True
            break
        for item in events:
            # Source is immutable per original run, not a timestamp inferred
            # from scheduled worker ACKs or a task monitor's observation.
            if (item.get("name") == "brain-cycle-v2" and
                    item.get("head_sha") == FINAL_SOURCE and
                    item.get("head_branch") == "main"):
                rows.append(item)
            # Source was deployed in a guarded merge after earlier source.
            if (item.get("name") == "brain-cycle-v2" and
                    item.get("head_branch") == "main" and
                    item.get("head_sha") != FINAL_SOURCE and
                    item.get("created_at", "") < "2026-10-17T08:28:26Z"):
                reached_older_source = True
        if reached_older_source:
            break
    require(reached_older_source, "RUN_CENSUS_PAGINATION_NOT_COMPLETE")
    require(len(rows) <= MAX_ORIGINAL_RUNS, "ORIGINAL_RUN_CENSUS_OVER_BUDGET")
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", 0)))


def checked_original_run(api, row):
    rid = row.get("id")
    require(type(rid) is int and 0 < rid < 10**16, "ORIGINAL_RUN_ID_INVALID")
    genuine = api.get("actions/runs/" + str(rid))
    require(type(genuine) is dict and genuine.get("id") == rid
            and genuine.get("head_sha") == FINAL_SOURCE
            and genuine.get("head_branch") == "main"
            and genuine.get("name") == "brain-cycle-v2"
            and genuine.get("path") == ".github/workflows/brain-cycle.yml",
            "RUN_SOURCE_OR_IDENTITY_CHANGED")
    event = genuine.get("event")
    # Push is *excluded* and cannot start or lengthen an automatic window.
    if event == "push":
        return None
    require(event in {"schedule", "workflow_dispatch"},
            "UNVERIFIED_MANUAL_ORIGIN_WITHIN_WINDOW")
    require(genuine.get("status") == "completed"
            and genuine.get("conclusion") == "success"
            and genuine.get("run_attempt") == 1,
            "ORIGINAL_AUTOMATIC_RUN_NOT_SUCCESS_FIRST_ATTEMPT")
    jobs = api.get("actions/runs/" + str(rid) + "/jobs?per_page=100")
    data = jobs.get("jobs") if type(jobs) is dict else None
    require(type(jobs) is dict and jobs.get("total_count") == 1
            and type(data) is list and len(data) == 1,
            "ORIGINAL_JOB_CENSUS_NOT_ONE")
    job = data[0]
    require(job.get("name") == "monitor" and job.get("status") == "completed"
            and job.get("conclusion") == "success"
            and job.get("run_attempt") in (None, 1)
            and type(job.get("steps")) is list, "ORIGINAL_MONITOR_JOB_FAILED")
    stages = {step.get("name"): step.get("conclusion")
              for step in job["steps"] if type(step) is dict}
    require(all(stages.get(n) == "success" for n in REQUIRED_STEPS),
            "ORIGINAL_MANDATORY_STEP_FAILED")
    origin = "NATIVE_SCHEDULE"
    if event == "workflow_dispatch":
        require(any(stages.get(n) == "success" for n in ORIGINS),
                "UNVERIFIED_CLOUDFLARE_OR_WATCHDOG_DISPATCH")
        if stages.get("Verify independently signed Cloudflare Cron provenance") == "success":
            origin = "CLOUDFLARE_SIGNED"
        else:
            origin = "INDEPENDENT_GITHUB_OR_EXTERNAL_CLOCK"
    return dict(run_id=rid, event=event, origin=origin,
                completed=dt(job.get("completed_at")))


def checked_zip(api, rid):
    meta = api.get("actions/runs/" + str(rid) + "/artifacts?per_page=100")
    items = meta.get("artifacts") if type(meta) is dict else None
    require(type(meta) is dict and meta.get("total_count") == 1
            and type(items) is list and len(items) == 1,
            "ORIGINAL_ARTIFACT_CENSUS_NOT_ONE")
    item = items[0]
    require(item.get("expired") is False
            and item.get("name") == f"brain-v2-cycle-{FINAL_SOURCE}-{rid}-1"
            and type(item.get("digest")) is str
            and re.fullmatch("sha256:[0-9a-f]{64}", item["digest"])
            and type(item.get("id")) is int,
            "ORIGINAL_ARTIFACT_PROVIDER_SCHEMA")
    data = api.artifact_zip(item["id"])
    require(len(data) == item.get("size_in_bytes")
            and "sha256:" + hashlib.sha256(data).hexdigest() == item["digest"],
            "ORIGINAL_ZIP_BYTE_OR_PROVIDER_HASH_MISMATCH")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = z.namelist()
            require(len(members) == len(set(members))
                    and z.testzip() is None, "ORIGINAL_ZIP_CRC_OR_DUPLICATE")
            for required in ("delivery.json", "doctor/report.json",
                             "state-publication.json"):
                require(required in members, "MANDATORY_ORIGINAL_ARTIFACT_MISSING")
            delivery = strict_json(z.read("delivery.json"))
            doctor = strict_json(z.read("doctor/report.json"))
            published = strict_json(z.read("state-publication.json"))
            signed_envelope = (
                strict_json(z.read("cloudflare-origin.json"))
                if "cloudflare-origin.json" in members else None
            )
    except (zipfile.BadZipFile, KeyError, UnicodeError, ValueError) as exc:
        raise Hold("ORIGINAL_ZIP_CONTENT_INVALID") from None
    require(type(delivery) is dict and type(doctor) is dict
            and type(published) is dict
            and delivery.get("run_id") == str(rid)
            and delivery.get("run_attempt") == "1"
            and delivery.get("source_sha") == FINAL_SOURCE
            and delivery.get("publication_verified") is True
            and delivery.get("soak_completed") is False
            and doctor.get("source_sha") == FINAL_SOURCE
            and doctor.get("status") == "PASS"
            and doctor.get("pending_events") == 0
            and doctor.get("verified_canonical_state") is True
            and type(doctor.get("state_sequence")) is int
            and type(doctor.get("canonical_hash")) is str
            and re.fullmatch(r"[0-9a-f]{64}", doctor["canonical_hash"])
            and type(published.get("raw_sha256")) is str,
            "ORIGINAL_REPORT_OR_DELIVERY_INVALID")
    return dict(delivery=delivery, doctor=doctor, publication=published,
                signed_cloudflare_origin=signed_envelope,
                zip_digest=item["digest"], artifact_id=item["id"])


def evaluate(api):
    base = api.get("branches/main")
    require(type(base) is dict and base.get("commit", {}).get("sha") == FINAL_SOURCE
            and base.get("protected") is True,
            "CURRENT_PROTECTED_MAIN_SOURCE_MOVED")
    listing = original_census(api)
    complete = []
    parent = None
    last_seq = -1
    for row in listing:
        event = checked_original_run(api, row)
        if event is None:
            continue
        evidence = checked_zip(api, event["run_id"])
        receipt, doctor = evidence["delivery"], evidence["doctor"]
        if event["origin"] == "CLOUDFLARE_SIGNED":
            signed = evidence["signed_cloudflare_origin"]
            require(type(signed) is dict
                    and signed.get("status") == "CLOUDFLARE_SIGNED_ORIGIN_VERIFIED"
                    and signed.get("signed_origin") is True
                    and signed.get("source_sha") == FINAL_SOURCE
                    and signed.get("soak_pass") is False
                    and type(signed.get("slot")) is int
                    and type(signed.get("scheduled_at")) is str,
                    "ORIGINAL_CLOUDFLARE_SIGNED_ARTIFACT_MISSING")
        first_parent = receipt.get("state_parent")
        child = receipt.get("state_commit")
        require(type(first_parent) is str and SOURCE_RE.fullmatch(first_parent)
                and type(child) is str and SOURCE_RE.fullmatch(child)
                and (parent is None or first_parent == parent),
                "ORIGINAL_STATE_LINEAGE_GAP")
        commit = api.get("git/commits/" + child)
        require(type(commit) is dict and commit.get("sha") == child
                and type(commit.get("parents")) is list
                and len(commit["parents"]) == 1
                and commit["parents"][0].get("sha") == first_parent,
                "ORIGINAL_GIT_STATE_ANCESTRY_MISMATCH")
        require(doctor["state_sequence"] > last_seq,
                "ORIGINAL_EVENT_SEQUENCE_NOT_INCREASING")
        last_seq = doctor["state_sequence"]
        parent = child
        complete.append({**event, **evidence})
    if not complete:
        return {"status":"WAITING_FIRST_ORIGINAL_AUTOMATIC_COMPLETION",
                "production_source": FINAL_SOURCE,
                "acceptance_pass": False, "completed_cores": 0}
    times = [r["completed"] for r in complete]
    gaps = [(end-start).total_seconds() for start,end in zip(times,times[1:])]
    span = (times[-1]-times[0]).total_seconds()
    require(all(v > 0 and v <= MAXIMUM_GAP for v in gaps),
            "ORIGINAL_QUALIFYING_GAP_EXCEEDED")
    common = {
        "production_source": FINAL_SOURCE,
        "anchor_run": complete[0]["run_id"],
        "anchor_completion_utc": times[0].isoformat(),
        "latest_run": complete[-1]["run_id"],
        "latest_completion_utc": times[-1].isoformat(),
        "completion_span_seconds": int(span),
        "maximum_gap_seconds": int(max(gaps) if gaps else 0),
        "verified_original_cores": len(complete),
        "last_state_commit": parent,
        "last_sequence": last_seq,
        "last_canonical_hash": complete[-1]["doctor"]["canonical_hash"],
        "last_raw_sha256": complete[-1]["publication"]["raw_sha256"],
        "acceptance_pass": False,
    }
    if span < MINIMUM_SPAN:
        return {"status": "WINDOW_RUNNING_NOT_ACCEPTED",
                "seconds_remaining_minimum": int(MINIMUM_SPAN-span),
                **common}
    return {"status": "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
            "still_required": [
                "independent Cloudflare provider original scheduled-event readback",
                "terminal pinned Git chunks / raw SQLite ledger / report replay",
                "independent separately reviewed acceptance and real repair outcome"],
            **common}


def replay_terminal(*, source_dir, state_dir, evidence):
    require(evidence.get("status") == "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
            "SIX_HOUR_PROVIDER_CENSUS_NOT_VERIFIED")
    source = Path(source_dir).resolve()
    state = Path(state_dir).resolve()
    def rev(path):
        try:
            return subprocess.check_output(
                ["git","-C",str(path),"rev-parse","HEAD"],text=True,timeout=10
            ).strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise Hold("IMMUTABLE_SOURCE_CHECKOUT_MISSING") from None
    require(rev(source) == FINAL_SOURCE
            and rev(state) == evidence["last_state_commit"],
            "PINNED_PRODUCTION_OR_TERMINAL_SHA_MISMATCH")
    require((state/"state-manifest.json").is_file()
            and (state/"state-chunks").is_dir()
            and not (state/"state.sqlite").exists(),
            "STATE_SNAPSHOT_NOT_PRISTINE")
    sys.path.insert(0,str(source))
    from brain.state_archive import restore
    from brain.core import Store, digest
    from soak_v3.audit import verify_sqlite
    manifest = restore(state)
    database = state/"state.sqlite"
    require(manifest.get("raw_sha256") == evidence["last_raw_sha256"],
            "RESTORED_RAW_STATE_MISMATCH")
    strict = verify_sqlite(
        database, expected_sequence=evidence["last_sequence"],
        expected_chain=evidence["last_canonical_hash"],
        expected_source=FINAL_SOURCE,
        max_bytes=120_512_512, strict_event_ids=True)
    require(strict.get("status") == "PASS", "INDEPENDENT_SQLITE_REPLAY_FAILED")
    db = Store(database,visibility="PUBLIC")
    try:
        row = db.db.execute(
            "SELECT created_at,hash FROM reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
        require(row is not None, "LATEST_CANONICAL_REPORT_MISSING")
        report = db.read_report(FINAL_SOURCE, now=row["created_at"])
        require(report.get("status") == "PASS"
                and report.get("state_sequence") == evidence["last_sequence"]
                and report.get("canonical_hash") == evidence["last_canonical_hash"]
                and report.get("pending_events") == 0
                and digest(report) == row["hash"],
                "DETERMINISTIC_LATEST_REPORT_REPLAY_FAILED")
    finally:
        db.close()
    return {"status":"ORIGINAL_TERMINAL_RAW_SQLITE_REPLAY_VERIFIED",
            "terminal_source_sha":FINAL_SOURCE,
            "terminal_state_commit":evidence["last_state_commit"],
            "restored_sqlite_sha256":strict["sha256"],
            "sequence":evidence["last_sequence"],
            "canonical_hash":evidence["last_canonical_hash"],
            "pending_events":0,
            "authorizes_production_release":False,
            "independent_cloudflare_originals_still_required":True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir")
    parser.add_argument("--terminal-dir")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    require(bool(args.source_dir) == bool(args.terminal_dir),
            "BOTH_IMMUTABLE_CHECKOUTS_REQUIRED_TO_REPLAY")
    api=OriginalGitHub()
    proof=evaluate(api)
    if args.terminal_dir:
        proof["terminal_replay"]=replay_terminal(
            source_dir=args.source_dir,state_dir=args.terminal_dir,
            evidence=proof)
    proof.update(provider_reads=api.calls,
        external_cloudflare_provider_accepted=False,
        unattended_repair_certified=False,
        release_or_merge_authorized=False)
    args.output.write_text(json.dumps(proof,indent=2,sort_keys=True)+"\n")
    print("V8 source-bound terminal preflight:",proof["status"])


if __name__=="__main__":
    try:
        main()
    except Exception:
        raise SystemExit("V8_TERMINAL_PREFLIGHT_FAILED_CLOSED; NO_ACCEPTANCE") from None
