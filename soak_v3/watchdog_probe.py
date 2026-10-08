"""Independently verify the *provider chain* behind a GitHub scheduled watchdog core.

A bot actor, manual dispatch, or embedded JSON claim is insufficient on its own.
The parent must be a genuine completed GitHub schedule with a successful dispatch
step; BOTH artifact ZIPs and the remotely persisted SQLite must be inspected.
This collector cannot return soak PASS or mutate any repository.
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile

from soak_v3.audit import EvidenceError, REQUIRED_STEPS, require, sha40, utc, verify_artifact, verify_sqlite
from soak_v3.remote_probe import GitHubReadOnly, git_blob_hash

BOT = "github-actions[bot]"
CORE_PATH = ".github/workflows/brain-cycle.yml"
CLOCK_PATH = ".github/workflows/brain-clock.yml"
STEP = "Dispatch one overdue core without inventing a PASS"

def validate_link(core, clock, origin, clock_job, decision, *, source_sha):
    """Provider/receipts cross-check; never trust origin's flags by themselves."""
    sha40(source_sha)
    require(core.get("event") == "workflow_dispatch" and
            core.get("status") == "completed" and core.get("conclusion") == "success" and
            core.get("run_attempt") == 1 and core.get("actor",{}).get("login") == BOT,
            "CORE_IS_NOT_AUTOMATIC_BOT_DISPATCH")
    require(core.get("head_sha") == source_sha and core.get("head_branch") == "main" and
            core.get("path") == CORE_PATH, "CORE_SOURCE_MISMATCH")
    require(origin.get("kind") == "github_schedule" and origin.get("source_sha") == source_sha and
            origin.get("clock_run_id") == clock.get("id") and
            origin.get("core_actor") == BOT and origin.get("soak_pass") is False,
            "CORE_CLOCK_ORIGIN_UNVERIFIED")
    require(clock.get("name") == "brain-clock-v2" and clock.get("event") == "schedule" and
            clock.get("path") == CLOCK_PATH and clock.get("head_sha") == source_sha and
            clock.get("head_branch") == "main" and clock.get("run_attempt") == 1 and
            clock.get("status") == "completed" and clock.get("conclusion") == "success",
            "PARENT_IS_NOT_GENUINE_SUCCESSFUL_SCHEDULE")
    created=utc(clock.get("created_at"))
    child=utc(core.get("created_at"))
    require(0 <= (child-created).total_seconds() <= 1200, "CLOCK_CORE_DELIVERY_NOT_CORRELATED")
    require(clock_job.get("name") == "scheduled-watchdog" and
            clock_job.get("status") == "completed" and clock_job.get("conclusion") == "success",
            "CLOCK_WATCHDOG_JOB_NOT_SUCCESSFUL")
    steps={x.get("name"):x.get("conclusion") for x in clock_job.get("steps",[]) if isinstance(x,dict)}
    require(steps.get(STEP) == "success", "CLOCK_DISPATCH_STEP_DID_NOT_SUCCEED")
    require(decision.get("status") == "DUE" and decision.get("dispatch") is True and
            decision.get("source_sha") == source_sha and decision.get("soak_pass") is False,
            "CLOCK_DUE_DECISION_NOT_VERIFIED")
    return {"kind":"github_schedule","source_sha":source_sha,
            "clock_run_id":clock["id"],"provider_scheduler_verified":True,
            "clock_job_verified":True,"core_receipt_verified":True,
            "core_actor_verified":True}

def one_artifact(api, run_id, *, name, sha):
    doc=api.json(f"/actions/runs/{run_id}/artifacts?per_page=100")
    items=doc.get("artifacts")
    require(doc.get("total_count")==1 and isinstance(items,list) and len(items)==1,
            "ARTIFACT_IDENTITY_AMBIGUOUS")
    item=items[0]
    require(item.get("expired") is False and item.get("name")==name and
            item.get("workflow_run",{}).get("id")==run_id and
            item.get("workflow_run",{}).get("head_sha")==sha, "ARTIFACT_WRONG_OR_EXPIRED")
    require(isinstance(item.get("digest"),str) and item["digest"].startswith("sha256:"),
            "ARTIFACT_DIGEST_UNAVAILABLE")
    raw=api.get(f"/actions/artifacts/{item['id']}/zip",limit=20_000_000)
    require(hashlib.sha256(raw).hexdigest()==item["digest"][7:],"ARTIFACT_DIGEST_MISMATCH")
    return item, raw

def read_zip_json(raw, path):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            require(len(z.namelist())<=100 and len(set(z.namelist()))==len(z.namelist()),
                    "ARTIFACT_ZIP_UNBOUNDED")
            require(sum(x.file_size for x in z.infolist())<=4_000_000, "ARTIFACT_ZIP_BOMB")
            return json.loads(z.read(path))
    except (ValueError, KeyError, zipfile.BadZipFile, OSError) as exc:
        raise EvidenceError("ARTIFACT_REQUIRED_RECEIPT_MISSING") from exc

def verify_watchdog_core(api, run_id, source_sha):
    require(type(run_id) is int and run_id>0,"CORE_RUN_ID_INVALID")
    sha40(source_sha)
    core=api.json(f"/actions/runs/{run_id}")
    require(core.get("id")==run_id,"CORE_PROVIDER_ID_MISMATCH")
    require(api.json("/branches/main").get("commit",{}).get("sha")==source_sha,
            "CURRENT_MAIN_CHANGED")
    cj=api.json(f"/actions/runs/{run_id}/jobs?per_page=100")
    require(cj.get("total_count")==1 and len(cj.get("jobs",[]))==1,"CORE_JOBS_INCOMPLETE")
    core_job=cj["jobs"][0]
    require(core_job.get("name")=="monitor" and core_job.get("conclusion")=="success" and
            core_job.get("status")=="completed","CORE_MONITOR_NOT_SUCCESSFUL")
    core_steps={s.get("name"):s.get("conclusion") for s in core_job.get("steps",[]) if isinstance(s,dict)}
    require(all(core_steps.get(s)=="success" for s in REQUIRED_STEPS) and
            core_steps.get("Validate GitHub-native watchdog scheduling origin")=="success",
            "CORE_MANDATORY_STEP_MISSING")
    core_item,core_zip=one_artifact(api,run_id,
        name=f"brain-v2-cycle-{source_sha}-{run_id}-1",sha=source_sha)
    origin=read_zip_json(core_zip,"watchdog-origin.json")
    delivery=read_zip_json(core_zip,"delivery.json")
    clock_id=origin.get("clock_run_id")
    require(type(clock_id) is int and clock_id>0,"CLOCK_ID_MISSING")
    clock=api.json(f"/actions/runs/{clock_id}")
    cj=api.json(f"/actions/runs/{clock_id}/jobs?per_page=100")
    require(cj.get("total_count")==1 and len(cj.get("jobs",[]))==1,"CLOCK_JOBS_INCOMPLETE")
    clock_item,clock_zip=one_artifact(api,clock_id,
        name=f"brain-v3-watchdog-{clock_id}-1",sha=source_sha)
    decision=read_zip_json(clock_zip,"decision.json")
    bound=validate_link(core,clock,origin,cj["jobs"][0],decision,source_sha=source_sha)
    state_commit=sha40(delivery.get("state_commit"))
    state_parent=sha40(delivery.get("state_parent"))
    gitcommit=api.json(f"/git/commits/{state_commit}")
    require(gitcommit.get("sha")==state_commit and
            [x.get("sha") for x in gitcommit.get("parents",[])]==[state_parent],
            "STATE_COMMIT_PARENT_WRONG")
    state=api.json(f"/contents/state.sqlite?ref={state_commit}")
    require(state.get("encoding")=="base64" and isinstance(state.get("content"),str),
            "REMOTE_STATE_UNAVAILABLE")
    try:
        raw=base64.b64decode(state["content"].replace("\n",""),validate=True)
    except (ValueError,base64.binascii.Error) as exc:
        raise EvidenceError("REMOTE_STATE_BAD_BASE64") from exc
    require(git_blob_hash(raw)==state.get("sha"),"REMOTE_GIT_BLOB_IDENTITY_MISMATCH")
    with tempfile.TemporaryDirectory() as tmp:
        zpath=Path(tmp)/"core.zip"
        spath=Path(tmp)/"state.sqlite"
        zpath.write_bytes(core_zip)
        spath.write_bytes(raw)
        ar=verify_artifact(zpath,core_item["digest"],run_id=run_id,source_sha=source_sha,
                            state_parent=state_parent,state_commit=state_commit)
        sr=verify_sqlite(spath,expected_sequence=ar["state_sequence"],
                          expected_chain=ar["canonical_hash"],expected_source=source_sha)
    return {"status":"VERIFIED_GITHUB_NATIVE_WATCHDOG_CORE","source_sha":source_sha,
            "run_id":run_id,"clock_run_id":clock_id,"external_clock":bound,
            "core_artifact_id":core_item["id"],"clock_artifact_id":clock_item["id"],
            "state_commit":state_commit,"state_parent":state_parent,
            "canonical_hash":sr["canonical_hash"],"state_sequence":sr["sequence"],
            "pending_events":0,"soak_pass":False}
