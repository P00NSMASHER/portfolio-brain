"""Read original target evidence and persist changes in the existing Brain state transaction.

The ledger records the owner's chat decision. No decision or GitHub event in
this module grants the scheduled runtime permission to create a PR or merge.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import urllib.request

from brain.v11.owner_inbox import canonical, digest, strict_load
from brain.v11 import origin_currentness, owner_inbox
from brain.v11.origin_currentness import NoRedirect
from brain.v9.batch_queue import PROJECTS

REGISTRY = Path(__file__).resolve().parents[2] / "repair" / "OWNER_DECISIONS.json"
DECISIONS = {"AWAITING_CHAT_DECISION", "APPROVED_IN_CHAT", "DECLINED", "DEFERRED"}
SHA = re.compile(r"[0-9a-f]{40}")
ROUTES = re.compile(r"(?:pulls/[1-9]\d*|actions/runs/[1-9]\d*(?:/jobs\?per_page=100)?|"
                    r"commits/[a-f0-9]{40}/check-runs\?per_page=100|"
                    r"contents/\.github/workflows/[A-Za-z0-9_-]+\.ya?ml\?ref=[a-f0-9]{40})")


def require(value, reason):
    if not value:
        raise ValueError(reason)


class Original:
    def __init__(self, token):
        self.opener = urllib.request.build_opener(NoRedirect())
        self.token = token

    def get(self, repo, route):
        require(repo in PROJECTS.values() and ROUTES.fullmatch(route), "unreviewed provider route")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "brain-owner-decisions"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(f"https://api.github.com/repos/{repo}/{route}", headers=headers)
        with self.opener.open(request, timeout=5) as response:
            body = response.read(1_000_001)
            require(response.status == 200 and len(body) <= 1_000_000, "incomplete provider response")
            return json.loads(body)


def original_job(api, repo, number, head, workflow_id, path, event, job_name, step_name, conclusion):
    route = "actions/runs/" + str(number)
    run = api.get(repo, route)
    require(run["id"] == number and run["repository"]["full_name"] == repo
            and run["head_repository"]["full_name"] == repo and run["head_sha"] == head
            and run["event"] in event and run["workflow_id"] == workflow_id and run["path"] == path
            and run["status"] == "completed" and run["conclusion"] == conclusion
            and run["run_attempt"] == 1, "original workflow identity or conclusion changed")
    census = api.get(repo, route + "/jobs?per_page=100")
    require(census["total_count"] == len(census["jobs"]), "incomplete job census")
    matches = [j for j in census["jobs"] if j["name"] == job_name and j["head_sha"] == head
               and j["run_id"] == number and j["run_attempt"] == 1 and j["conclusion"] == conclusion
               and any(s["name"] == step_name and s["conclusion"] == conclusion
                       and s["status"] == "completed" for s in j["steps"])]
    require(len(matches) == 1, "original behavior step not confirmed")
    return run, matches[0]


def observe(record, api):
    repo, pr_number = record["repository"], record["existing_pr"]
    prefix = "https://github.com/" + repo
    row = {k: record[k] for k in ("id", "repository", "problem", "owner", "owner_decision",
                                  "chat_approval", "approved_scope", "request", "acceptance", "existing_pr")}
    row.update(state="EVIDENCE_UNAVAILABLE", source=prefix + "/pull/" + str(pr_number),
               original_evidence=f"{prefix}/actions/runs/{record['original_run']}/job/{record['original_job']}",
               behavior_verified=False, delivered_by=None)
    try:
        pr = api.get(repo, "pulls/" + str(pr_number))
        require(pr["number"] == pr_number and pr["base"]["repo"]["full_name"] == repo
                and pr["head"]["repo"]["full_name"] == repo and pr["base"]["ref"] == "main"
                and SHA.fullmatch(pr["head"]["sha"]), "PR changed target")
        row.update(head=pr["head"]["sha"], pr_author=pr["user"]["login"])
        _, failed = original_job(api, repo, record["original_run"], record["original_head"],
                                 record["workflow_id"], record["workflow_path"], {"pull_request"},
                                 record["job"], record["failed_step"], "failure")
        require(failed["id"] == record["original_job"], "original failed job changed")
        if not pr["merged"]:
            if pr["state"] == "closed":
                row["state"] = "CLOSED_WITHOUT_DELIVERY"
            else:
                checks = api.get(repo, "commits/" + row["head"] + "/check-runs?per_page=100")
                require(checks["total_count"] == len(checks["check_runs"]), "incomplete check census")
                matches = [c for c in checks["check_runs"] if c["head_sha"] == row["head"]
                           and c["app"]["id"] == 15368 and c["name"] == record["job"]]
                require(len(matches) <= 1, "ambiguous current check")
                row["state"] = "OPEN_WITH_EXISTING_OWNER"
                if matches and matches[0]["status"] == "completed" and matches[0]["conclusion"] == "failure":
                    row.update(state="BLOCKED", blocker=matches[0]["details_url"])
            return row
        require(pr["state"] == "closed" and SHA.fullmatch(pr["merge_commit_sha"]), "merge not confirmed")
        row.update(state="MERGED_AWAITING_TARGET_PROOF", merge_sha=pr["merge_commit_sha"],
                   merged_by=pr["merged_by"]["login"])
        proof = record.get("postrelease_workflow")
        if proof:
            # This owner-reviewed target workflow must actually exercise the stated acceptance.
            # A normal release, build, PR check, or historical Brain receipt cannot stand in.
            path = proof["path"]
            source = api.get(repo, "contents/" + path + "?ref=" + row["merge_sha"])
            require(source["path"] == path and source["sha"] == proof["reviewed_workflow_blob"]
                    and SHA.fullmatch(source["sha"]), "unreviewed behavior probe")
            run, job = original_job(api, repo, proof["run_id"], row["merge_sha"], proof["workflow_id"],
                                    path, {"push", "workflow_dispatch", "schedule"}, proof["job"],
                                    proof["behavior_step"], "success")
            require(run["head_branch"] == "main" and run["created_at"] >= pr["merged_at"],
                    "probe is not post-release")
            row.update(state="VERIFIED_ORIGINAL_TARGET_WORKFLOW", behavior_verified=True,
                       delivered_by=pr["merged_by"]["login"], proof=job["html_url"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        row["state"] = "EVIDENCE_UNAVAILABLE"
    return row


def changes(db, rows):
    db.execute("CREATE TABLE IF NOT EXISTS owner_decision (id TEXT PRIMARY KEY, material TEXT, "
               "record TEXT NOT NULL, pending INTEGER NOT NULL)")
    identifiers = []
    for row in rows:
        identifiers.append(row["id"])
        # Store the latest source while notifying only on a material decision transition.
        material = digest([row.get(k) for k in ("state", "owner_decision", "owner", "existing_pr",
                                                "request", "acceptance", "chat_approval", "approved_scope", "proof")])
        db.execute("INSERT INTO owner_decision VALUES (?,?,?,1) ON CONFLICT(id) DO UPDATE SET "
                   "material=excluded.material, record=excluded.record, pending=CASE WHEN "
                   "owner_decision.material != excluded.material THEN 1 ELSE owner_decision.pending END "
                   "WHERE owner_decision.record != excluded.record",
                   (row["id"], material, canonical(row)))
    # Only current evidence may release a pending notification after an earlier cap.
    placeholders = ",".join("?" for _ in identifiers) or "NULL"
    pending = f"FROM owner_decision WHERE pending=1 AND id IN ({placeholders})"
    due = [json.loads(r[0]) for r in db.execute(
        f"SELECT record {pending} ORDER BY rowid LIMIT 3", identifiers)]
    db.executemany("UPDATE owner_decision SET pending=0 WHERE id=?", [(r["id"],) for r in due])
    return {"version": 1, "decisions": due, "remaining": db.execute(
        f"SELECT count(*) {pending}", identifiers).fetchone()[0], "provider_writes": 0}


def incidents(cycle, currentness_api, rotation):
    if cycle.get("incident_gate") != "ORIGINAL_MAIN_FAILURE_PROOF_REQUIRED":
        return
    inbox = owner_inbox.build(cycle, expected_source=cycle["source_sha"])
    handoffs = inbox["original_failure_handoffs"]
    if not handoffs:
        return
    # One original target per core keeps the duplicated currentness reads bounded.
    item = handoffs[rotation % len(handoffs)]
    inbox["original_failure_handoffs"] = [item]
    del inbox["packet_sha256"]
    inbox["packet_sha256"] = digest(inbox)
    verdict = origin_currentness.evaluate(inbox, currentness_api)
    if not verdict["items"][0]["reproduction_candidate"]:
        return
    for job in cycle["owner_jobs"]:
        if job["work_id"] != item["work_id"]:
            continue
        proof = job["failure_evidence"]
        if proof.get("status") != "ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED":
            continue
        names = sorted(s["name"] for s in proof["failed_steps"])
        repo = job["repository"]
        if not proof.get("workflow_path") or not proof.get("job_name"):
            continue
        key = digest([repo, proof["workflow_path"], proof["job_name"], names])
        yield {"id": key, "repository": repo, "state": "ORIGINAL_FAILURE_NEEDS_TRIAGE",
               "source": proof["url"], "source_sha": proof["source_sha"], "problem": ", ".join(names),
               "owner": job["owner"], "owner_decision": "AWAITING_CHAT_DECISION", "existing_pr": None,
               "request": "Recheck the original failure, active owner and open PRs before proposing a fix.",
               "acceptance": "Reproduce the failed behavior and verify it on the target after delivery.",
               "behavior_verified": False, "delivered_by": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("db", "cycle", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    ledger = strict_load(REGISTRY)
    require(ledger["version"] == 1 and len(ledger["records"]) <= 6, "invalid decision registry")
    api = Original(os.environ.get("GITHUB_TOKEN", ""))
    currentness = origin_currentness.PublicGitHub(os.environ.get("GITHUB_TOKEN", ""))
    rows = {item["id"]: item for item in incidents(strict_load(args.cycle), currentness,
                                                   int(os.environ.get("GITHUB_RUN_NUMBER", "0")))}
    seen = set()
    for record in ledger["records"]:
        ident = record["id"]
        require(ident not in seen and record["owner_decision"] in DECISIONS
                and record["repository"] in PROJECTS.values()
                and (record["owner_decision"] != "APPROVED_IN_CHAT" or
                     (record["chat_approval"] and record["approved_scope"])),
                "duplicate target, invalid decision or missing chat approval scope")
        seen.add(ident)
        if "original_run" in record:
            rows[ident] = observe(record, api)
        else:
            row = rows.get(ident, {"state": "OWNER_DECISION_RECORDED",
                                   "behavior_verified": False, "delivered_by": None})
            for key in ("id", "repository", "source", "problem", "owner", "owner_decision",
                        "chat_approval", "approved_scope", "existing_pr", "request", "acceptance"):
                row[key] = record[key]
            rows[ident] = row
    with sqlite3.connect(args.db) as db:
        result = changes(db, rows.values())
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
