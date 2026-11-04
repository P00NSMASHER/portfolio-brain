"""Open an already validated RETALLY writer branch using the Portfolio runtime App."""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from urllib.parse import quote

from governance.validate_boundaries import candidate_pr_authority

REPO = "P00NSMASHER/github-value-hunt-ledger"
API = f"repos/{REPO}"
ARTIFACT = "retally-app-request-v1"
WRITERS = {
    "technology": ("technology-intelligence.yml", {"push"}),
    "scout": ("public-repo-hunter.yml", {"schedule", "workflow_dispatch"}),
    "catalog": ("catalog-append.yml", {"push"}),
    "integrator": ("integrator-sync.yml", {"push"}),
}
SHA = re.compile(r"[0-9a-f]{40}")
APP_BOT = 343751880


def api(path, *, payload=None, binary=False):
    method = "POST" if payload is not None else "GET"
    if method == "POST" and path != "pulls":
        raise ValueError("Only PR creation is authorized")
    args = ["gh", "api", "--method", method, API + "/" + path]
    if payload is not None:
        args.extend(["--input", "-"])
    raw = subprocess.run(args, input=json.dumps(payload).encode() if payload else None,
                         capture_output=True, check=True, timeout=30).stdout
    return raw if binary else json.loads(raw)


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


def current_request(artifact):
    origin = artifact["workflow_run"]
    if artifact["name"] != ARTIFACT or artifact["expired"] or origin["head_branch"] != "main":
        return None
    if not 0 < artifact["size_in_bytes"] <= 8192:
        raise ValueError("Unexpected request archive size")
    run = api(f"actions/runs/{origin['id']}")
    if (run["path"] not in {".github/workflows/" + name for name, _ in WRITERS.values()}
            or run["conclusion"] != "success" or run["head_branch"] != "main"):
        return None
    raw = api(f"actions/artifacts/{artifact['id']}/zip", binary=True)
    request = read_request(artifact, raw)
    main = api("branches/main")["commit"]["sha"]
    if request.get("base") != main:
        return None
    if not check_request(request, run, main):
        return None
    branch = quote(request["branch"], safe="")
    existing = api(f"pulls?state=all&head=P00NSMASHER%3A{branch}&base=main&per_page=1")
    if existing:
        return None
    head = request["head"]
    if api("git/ref/heads/" + request["branch"])["object"]["sha"] != head:
        raise ValueError("Generated branch moved")
    commit = api(f"git/commits/{head}")
    if [p["sha"] for p in commit["parents"]] != [main]:
        raise ValueError("Generated commit is not a direct child of current main")
    diff = api(f"compare/{main}...{head}")
    files = diff["files"]
    if (diff["status"] != "ahead" or diff["ahead_by"] != 1 or diff["behind_by"] != 0
            or len(files) != request["file_count"] or len({f["filename"] for f in files}) != len(files)
            or any(f["status"] not in {"modified", "added"}
                   or not re.fullmatch(r"(?!\.)(?!.*(?:/\.|//))[A-Za-z0-9_./-]+\.(?:md|json|jsonl|txt|csv)", f["filename"])
                   for f in files)):
        raise ValueError("Generated diff differs from the writer request")
    return request


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
    args = parser.parse_args()
    if args.publish is not None:
        request = current_request(api(f"actions/artifacts/{args.publish}"))
        if request:
            create(request)
        return
    listing = api(f"actions/artifacts?name={ARTIFACT}&per_page=100")
    for artifact in listing["artifacts"]:
        if current_request(artifact):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
                print(f"artifact={int(artifact['id'])}", file=out)
            return
    print("No current unsubmitted RETALLY proposal")


if __name__ == "__main__":
    main()
