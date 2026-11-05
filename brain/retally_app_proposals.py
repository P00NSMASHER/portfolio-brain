"""Open an already validated RETALLY writer branch using the Portfolio runtime App."""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from urllib.parse import quote

from governance.validate_boundaries import candidate_pr_authority

REPO = "P00NSMASHER/github-value-hunt-ledger"
API = f"repos/{REPO}"
ARTIFACT = "retally-app-request-v1"
WRITERS = {
    "technology": ("technology-intelligence.yml", {"push"}),
    "scout": ("public-repo-hunter.yml", {"schedule", "workflow_dispatch", "push",
                                                "repository_dispatch"}),
    "catalog": ("catalog-append.yml", {"push"}),
    "integrator": ("integrator-sync.yml", {"push"}),
}
SHA = re.compile(r"[0-9a-f]{40}")
APP_BOT = 343751880
SCOUT_WORKFLOW = "public-repo-hunter.yml"
SCOUT_WORKER = re.compile(r"intelligence/scout_queue/(HUNTER-(?:0[1-9]|1[0-4]))\.json")


def api(path, *, payload=None, binary=False):
    method = "POST" if payload is not None else "GET"
    if method == "POST" and path not in {"pulls", "dispatches"}:
        raise ValueError("Only PR creation and scoped Scout recovery are authorized")
    args = ["gh", "api", "--method", method, API + "/" + path]
    if payload is not None:
        args.extend(["--input", "-"])
    raw = subprocess.run(args, input=json.dumps(payload).encode() if payload else None,
                         capture_output=True, check=True, timeout=30).stdout
    return raw if binary else (json.loads(raw) if raw else None)


def read_request(artifact, raw):
    if len(raw) != artifact["size_in_bytes"] or artifact["digest"] != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ValueError("Proposal artifact digest or size mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (len(entries) != 1 or entries[0].filename != "retally-app-request.json"
                or not 0 < entries[0].file_size <= 2048):
            raise ValueError("Unexpected proposal artifact layout")
        return json.loads(archive.read(entries[0]))


def check_request(request, run, main):
    lane = request["lane"]
    if lane not in WRITERS:
        raise ValueError("Unknown writer lane")
    workflow, events = WRITERS[lane]
    branch = f"automation/retally-{lane}-{run['id']}-{run['run_attempt']}"
    if (request.get("version") != 1 or request["branch"] != branch
            or run["path"] != ".github/workflows/" + workflow or run["event"] not in events
            or run["repository"]["full_name"] != REPO or run["head_repository"]["full_name"] != REPO
            or run["head_branch"] != "main" or run["conclusion"] != "success"
            or not SHA.fullmatch(request["head"]) or not SHA.fullmatch(request["base"])
            or type(request["file_count"]) is not int or not 0 < request["file_count"] < 300
            or not re.fullmatch(r"[a-f0-9]{64}" if lane == "scout" else "", request["scout_fingerprint"])):
        raise ValueError("Request does not match a successful source writer")
    authority = candidate_pr_authority("PRJ-011", "REPO-001", branch)
    if not authority["token_mint_allowed"]:
        raise ValueError("Project candidate authority denied")
    return request["base"] == main


def validate_branch(request, main):
    branch = quote(request["branch"], safe="")
    existing = api(f"pulls?state=all&head=P00NSMASHER%3A{branch}&base=main&per_page=1")
    if existing:
        record = existing[0]
        if (record["head"]["sha"] != request["head"]
                or record["base"]["sha"] != request["base"]):
            raise ValueError("Existing proposal does not match the writer request")
        files = api(f"pulls/{int(record['number'])}/files?per_page=100")
        if (len(files) != request["file_count"]
                or len({f["filename"] for f in files}) != len(files)
                or any(f["status"] not in {"modified", "added"}
                       or not re.fullmatch(r"(?!\.)(?!.*(?:/\.|//))[A-Za-z0-9_./-]+\.(?:md|json|jsonl|txt|csv)",
                                           f["filename"])
                       for f in files)):
            raise ValueError("Existing proposal files differ from the writer request")
        return files, True
    head = request["head"]
    if api("git/ref/heads/" + request["branch"])["object"]["sha"] != head:
        raise ValueError("Generated branch moved")
    commit = api(f"git/commits/{head}")
    if [p["sha"] for p in commit["parents"]] != [request["base"]]:
        raise ValueError("Generated commit is not a direct child of its recorded base")
    diff = api(f"compare/{request['base']}...{head}")
    files = diff["files"]
    if (diff["status"] != "ahead" or diff["ahead_by"] != 1 or diff["behind_by"] != 0
            or len(files) != request["file_count"] or len({f["filename"] for f in files}) != len(files)
            or any(f["status"] not in {"modified", "added"}
                   or not re.fullmatch(r"(?!\.)(?!.*(?:/\.|//))[A-Za-z0-9_./-]+\.(?:md|json|jsonl|txt|csv)", f["filename"])
                   for f in files)):
        raise ValueError("Generated diff differs from the writer request")
    if request["base"] == main and [p["sha"] for p in commit["parents"]] != [main]:
        raise ValueError("Generated commit is not a direct child of current main")
    return files, False


def inspect_request(artifact):
    origin = artifact["workflow_run"]
    if artifact["name"] != ARTIFACT or artifact["expired"] or origin["head_branch"] != "main":
        return None
    if not 0 < artifact["size_in_bytes"] <= 8192:
        raise ValueError("Unexpected request archive size")
    run = api(f"actions/runs/{origin['id']}")
    if (run["path"] not in {".github/workflows/" + name for name, _ in WRITERS.values()}
            or run["conclusion"] != "success" or run["head_branch"] != "main"):
        return None
    request = read_request(artifact, api(f"actions/artifacts/{artifact['id']}/zip", binary=True))
    main = api("branches/main")["commit"]["sha"]
    check_request(request, run, main)
    files, existing = validate_branch(request, main)
    worker = None
    if request["lane"] == "scout":
        workers = {match.group(1) for item in files
                   if (match := SCOUT_WORKER.fullmatch(item["filename"]))}
        if len(workers) != 1:
            raise ValueError("Scout request does not identify exactly one worker queue")
        worker = workers.pop()
    return request, main, worker, existing


def current_request(artifact):
    inspected = inspect_request(artifact)
    if inspected is None:
        return None
    request, main, _, existing = inspected
    return request if request["base"] == main and not existing else None


def dispatch_recovery(worker, expected_main):
    if not re.fullmatch(r"HUNTER-(?:0[1-9]|1[0-4])", worker):
        raise ValueError("Invalid Scout recovery worker")
    if api("branches/main")["commit"]["sha"] != expected_main:
        raise ValueError("Main moved before Scout recovery dispatch")
    for status in ("queued", "in_progress"):
        active = api(f"actions/workflows/{SCOUT_WORKFLOW}/runs?event=workflow_dispatch&status={status}&per_page=1")
        if active["workflow_runs"]:
            raise ValueError("A manual Scout run is already active")
    api("dispatches", payload={"event_type": "retally-scout-recovery-v1",
                               "client_payload": {"worker": worker,
                                                  "expected_main": expected_main}})
    print(f"Requested source-bound refresh for stale {worker} receipt at {expected_main}")


def create(request):
    lane = request["lane"]
    body = ("RETALLY validated this generated branch in its source writer. Its protected merger "
            "requires the native pull-request release gate and a separate exact-commit release run.")
    if lane == "scout":
        body += "\n\n<!-- scout-semantic-sha256:" + request["scout_fingerprint"] + " -->"
    pr = api("pulls", payload={"head": request["branch"], "base": "main", "draft": False,
             "title": f"Automated {lane} evidence refresh ({request['head'][:12]})", "body": body})
    record = api(f"pulls/{int(pr['number'])}")
    if (record["user"]["id"] != APP_BOT or record["user"]["login"] != "portfolio-brain-v8-runtime[bot]"
            or record["head"]["repo"]["full_name"] != REPO or record["head"]["sha"] != request["head"]
            or record["base"]["ref"] != "main" or record["base"]["sha"] != request["base"]
            or record["state"] != "open"):
        raise ValueError("Created PR did not reconcile with the approved source")
    print(f"App opened {REPO}#{record['number']} at {request['head']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", type=int)
    parser.add_argument("--recover")
    args = parser.parse_args()
    if args.publish is not None:
        request = current_request(api(f"actions/artifacts/{args.publish}"))
        if request:
            create(request)
        return
    if args.recover is not None:
        worker, expected_main = args.recover.split(":", 1)
        dispatch_recovery(worker, expected_main)
        return
    listing = api(f"actions/artifacts?name={ARTIFACT}&per_page=100")
    seen_workers = set()
    for artifact in listing["artifacts"]:
        try:
            inspected = inspect_request(artifact)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            print(f"Rejected invalid RETALLY artifact {artifact.get('id', 'unknown')}: {exc}", file=sys.stderr)
            continue
        if inspected is None:
            continue
        request, main, worker, existing = inspected
        if existing:
            if worker:
                seen_workers.add(worker)
            continue
        if request["base"] == main:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
                print(f"artifact={int(artifact['id'])}", file=out)
            return
        if worker and worker not in seen_workers:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
                print(f"recovery={worker}:{main}", file=out)
            return
        if worker:
            seen_workers.add(worker)
    print("No current unsubmitted RETALLY proposal")


if __name__ == "__main__":
    main()
