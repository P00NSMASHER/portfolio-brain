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

REGISTRY = Path(__file__).resolve().parents[2] / "repair" / "OWNER_DECISIONS.json"
DECISIONS = {"AWAITING_CHAT_DECISION", "APPROVED_IN_CHAT", "DECLINED", "DEFERRED"}
SHA = re.compile(r"[0-9a-f]{40}")
ROUTES = re.compile(r"(?:pulls/[1-9]\d*|actions/runs/[1-9]\d*(?:/jobs\?per_page=100)?|"
                    r"commits/[a-f0-9]{40}/(?:check-runs|pulls)\?per_page=100|"
                    r"contents/\.github/workflows/[A-Za-z0-9_-]+\.ya?ml\?ref=[a-f0-9]{40})")


def require(value, reason):
    if not value:
        raise ValueError(reason)


class Original:
    def __init__(self, token, repositories):
        self.opener = urllib.request.build_opener(NoRedirect())
        self.token = token
        self.repositories = frozenset(repositories)

    def get(self, repo, route):
        require(repo in self.repositories and ROUTES.fullmatch(route), "unreviewed provider route")
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


def linked_pr(payload, repo, number):
    return any(pr["number"] == number and
               pr["url"] == f"https://api.github.com/repos/{repo}/pulls/{number}"
               for pr in payload["pull_requests"])


def open_pr(row, record, api):
    repo, head, number = row["repository"], row["head"], row["existing_pr"]
    checks = api.get(repo, "commits/" + head + "/check-runs?per_page=100")
    require(checks["total_count"] == len(checks["check_runs"]), "incomplete check census")
    matches = [c for c in checks["check_runs"] if c["head_sha"] == head
               and c["app"]["id"] == 15368 and c["name"] == record["job"]
               and linked_pr(c, repo, number)]
    require(len(matches) <= 1, "ambiguous current check")
    if not matches or matches[0]["status"] != "completed" or matches[0]["conclusion"] not in {
            "failure", "timed_out", "success"}:
        row.update(state="OPEN_AWAITING_TARGET_CHECK",
                   request="Wait for a conclusive result from the named check on the existing PR head.")
        return
    check = matches[0]
    route = re.fullmatch(re.escape(f"https://github.com/{repo}/actions/runs/")
                         + r"([1-9][0-9]*)/job/" + str(check["id"]), check["details_url"])
    require(route, "unrecognized check job URL")
    run_id = int(route.group(1))
    run = api.get(repo, "actions/runs/" + str(run_id))
    require(run["id"] == run_id and run["repository"]["full_name"] == repo
            and run["head_repository"]["full_name"] == repo and run["head_sha"] == head
            and run["event"] == "pull_request" and linked_pr(run, repo, number)
            and run["workflow_id"] == record["workflow_id"] and run["path"] == record["workflow_path"],
            "current check belongs to another workflow or PR")
    row["current_check"] = check["details_url"]
    if check["conclusion"] == "success":
        row.update(state="OPEN_WITH_EXISTING_OWNER",
                   request="The named check passes on the current head. Leave delivery with the existing PR owner.")
    else:
        row.update(state="BLOCKED", blocker=check["details_url"])


def observe(record, api):
    repo, pr_number = record["repository"], record["existing_pr"]
    prefix = "https://github.com/" + repo
    row = {k: record[k] for k in ("id", "repository", "problem", "owner", "owner_decision",
                                  "chat_approval", "approved_scope", "request", "acceptance", "existing_pr")}
    row.update(registered_request=record["request"], state="EVIDENCE_UNAVAILABLE", source=prefix + "/pull/" + str(pr_number),
               original_evidence=f"{prefix}/actions/runs/{record['original_run']}/job/{record['original_job']}",
               behavior_verified=False, delivered_by=None)
    try:
        pr = api.get(repo, "pulls/" + str(pr_number))
        require(pr["number"] == pr_number and pr["base"]["repo"]["full_name"] == repo
                and pr["head"]["repo"]["full_name"] == repo and pr["base"]["ref"] == "main"
                and SHA.fullmatch(pr["head"]["sha"]), "PR changed target")
        row.update(head=pr["head"]["sha"], pr_author=pr["user"]["login"])
        original, failed = original_job(api, repo, record["original_run"], record["original_head"],
                                 record["workflow_id"], record["workflow_path"], {"pull_request"},
                                 record["job"], record["failed_step"], "failure")
        require(failed["id"] == record["original_job"], "original job changed")
        associated = linked_pr(original, repo, pr_number)
        # GitHub may clear a merged PR's historical run links. Require a unique
        # original-commit association and the same originating branch in that case.
        if not original["pull_requests"] and pr["merged"] and original["head_branch"] == pr["head"]["ref"]:
            links = api.get(repo, "commits/" + record["original_head"] + "/pulls?per_page=100")
            associated = len(links) == 1 and linked_pr({"pull_requests": links}, repo, pr_number)
        require(associated, "original failure does not belong to recorded PR")
        if not pr["merged"]:
            if pr["state"] == "closed":
                row.update(state="CLOSED_WITHOUT_DELIVERY",
                           request="The existing PR closed without merging. Review whether to pursue the recorded problem.")
            else:
                open_pr(row, record, api)
            return row
        require(pr["state"] == "closed" and SHA.fullmatch(pr["merge_commit_sha"]), "merge not confirmed")
        row.update(state="MERGED_AWAITING_TARGET_PROOF", merge_sha=pr["merge_commit_sha"],
                   merged_by=pr["merged_by"]["login"],
                   request="Verify the stated acceptance on the released target at the recorded merge commit.")
        proof = record.get("postrelease_workflow")
        if proof:
            # This owner-reviewed target workflow must actually exercise the stated acceptance.
            # A normal release, build, PR check, or historical Brain receipt cannot stand in.
            acceptance = digest([record[k] for k in ("id", "repository", "existing_pr", "problem", "acceptance")])
            if proof.get("acceptance_sha256") != acceptance:
                row["request"] = "Review the post-release probe against the current target and acceptance."
                return row
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
                       delivered_by=pr["merged_by"]["login"], proof=job["html_url"],
                       request="Review the original post-release behavior evidence for the recorded acceptance.")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        row.update(state="EVIDENCE_UNAVAILABLE",
                   request="Recheck the original target evidence before acting on this decision.")
    return row


def changes(db, rows):
    db.execute("CREATE TABLE IF NOT EXISTS owner_decision (id TEXT PRIMARY KEY, material TEXT, "
               "record TEXT NOT NULL, pending INTEGER NOT NULL)")
    def fingerprint(row):
        return digest([row.get(k) for k in ("repository", "problem", "state", "owner_decision", "owner",
                                            "existing_pr", "request", "acceptance", "chat_approval",
                                            "approved_scope", "proof")]
                      + [row.get("registered_request", row.get("request"))])

    identifiers = []
    for row in rows:
        prior = db.execute("SELECT record FROM owner_decision WHERE id=?", (row["id"],)).fetchone()
        if not prior and row["state"] in {"ORIGINAL_FAILURE_HISTORICAL", "ORIGINAL_FAILURE_RECHECK_REQUIRED"}:
            continue
        previous = json.loads(prior[0]) if prior else None
        if previous and "incident_run" in row:
            last_run = previous.get("incident_run", 0)
            if row["incident_run"] < last_run:
                continue
            if (row["incident_run"] == last_run and previous["state"] == "ORIGINAL_FAILURE_HISTORICAL"
                    and row["state"] != previous["state"]):
                continue  # Reopening a historical failure requires a newly authenticated failed job.
        identifiers.append(row["id"])
        material = fingerprint(row)
        changed = previous is None or material != fingerprint(previous)
        db.execute("INSERT INTO owner_decision VALUES (?,?,?,1) ON CONFLICT(id) DO UPDATE SET "
                   "material=excluded.material, record=excluded.record, pending=CASE WHEN ? THEN 1 "
                   "ELSE owner_decision.pending END WHERE owner_decision.record != excluded.record",
                   (row["id"], material, canonical(row), changed))
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
    observation = verdict["items"][0]
    for job in cycle["owner_jobs"]:
        if job["work_id"] != item["work_id"]:
            continue
        proof = job["failure_evidence"]
        if (proof.get("status") != "ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED"
                or proof["job_id"] != item["job_id"] or proof["run_id"] != item["run_id"]):
            continue
        names = sorted(s["name"] for s in proof["failed_steps"])
        repo = job["repository"]
        if not proof.get("workflow_path") or not proof.get("job_name"):
            continue
        key = digest([repo, proof["workflow_path"], proof["job_name"], names])
        state = "ORIGINAL_FAILURE_NEEDS_TRIAGE"
        request = "Recheck the original failure, active owner and open PRs before proposing a fix."
        if observation["status"] in {"SOURCE_CHANGED_ORIGINAL_FAILURE_HISTORICAL",
                                     "LATER_SAME_SOURCE_WORKFLOW_SUCCESS_ORIGINAL_FAILURE_HISTORICAL"}:
            state = "ORIGINAL_FAILURE_HISTORICAL"
            request = "Retire the original failure from triage. A product repair has not been verified."
        elif not observation["reproduction_candidate"]:
            state = "ORIGINAL_FAILURE_RECHECK_REQUIRED"
            request = "Hold triage until the current target evidence can be confirmed."
        yield {"id": key, "repository": repo, "state": state, "incident_run": proof["run_id"],
               "currentness": observation["status"], "latest_run_id": observation["latest_run_id"],
               "source": proof["url"], "source_sha": proof["source_sha"], "problem": ", ".join(names),
               "owner": job["owner"], "owner_decision": "AWAITING_CHAT_DECISION", "existing_pr": None,
               "request": request,
               "acceptance": "Reproduce the failed behavior and verify it on the target after delivery.",
               "behavior_verified": False, "delivered_by": None}


def registered_rows(records, api, rotation, rows):
    """Rotate one active original-target readback. Preserve all other durable decisions."""
    active = sorted(r["id"] for r in records if r.get("original_run") and
                    r["owner_decision"] not in {"DECLINED", "DEFERRED"})
    selected = active[rotation % len(active)] if active else None
    seen = set()
    for record in records:
        ident = record["id"]
        require(ident not in seen and record["owner_decision"] in DECISIONS
                and re.fullmatch(r"P00NSMASHER/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", record["repository"])
                and (record["owner_decision"] != "APPROVED_IN_CHAT" or
                     (record["chat_approval"] and record["approved_scope"])),
                "duplicate target, invalid decision or missing chat approval scope")
        seen.add(ident)
        if ident == selected:
            rows[ident] = observe(record, api)
        elif ident in active:
            rows.pop(ident, None)
        else:
            row = rows.get(ident, {"state": "OWNER_DECISION_RECORDED",
                                   "behavior_verified": False, "delivered_by": None})
            for key in ("id", "repository", "problem", "owner", "owner_decision", "chat_approval",
                        "approved_scope", "existing_pr", "request", "acceptance"):
                row[key] = record[key]
            row["source"] = record.get("source") or (
                f"https://github.com/{record['repository']}/pull/{record['existing_pr']}"
                if record["existing_pr"] else f"https://github.com/{record['repository']}")
            rows[ident] = row
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("db", "cycle", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    ledger = strict_load(REGISTRY)
    require(ledger["version"] == 1 and isinstance(ledger["records"], list), "invalid decision registry")
    records = ledger["records"]
    token = os.environ.get("GITHUB_TOKEN", "")
    rotation = int(os.environ.get("GITHUB_RUN_NUMBER", "0"))
    api = Original(token, [r["repository"] for r in records])
    currentness = origin_currentness.PublicGitHub(token)
    rows = {item["id"]: item for item in incidents(strict_load(args.cycle), currentness, rotation)}
    registered_rows(records, api, rotation, rows)
    with sqlite3.connect(args.db) as db:
        result = changes(db, rows.values())
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
