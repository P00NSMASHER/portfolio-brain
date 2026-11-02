"""Bounded V10 repair-draft completion using native GitHub protected auto-merge.

Triggered only by real Foundation workflow_run on trusted main. No candidate
code is executed with credentials; no direct merge, force push, timer or
branch-ruleset modification. GitHub itself enforces BOTH pinned required checks.
An uncertain write is never retried automatically.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from brain.v9 import guarded_merge as gm
from brain.v10 import engineering_factory as factory

REPO = factory.REPOSITORY
ROOT = "repos/" + REPO + "/"
BRANCH = re.compile(r"auto-repair/v10-[0-9a-f]{16}\Z")
OPERATION = re.compile(r"BRAIN_V10_OPERATION_ID: ([0-9a-f]{64})\Z")
RECEIPT = re.compile(r"V10_RED_GREEN_RECEIPT_SHA256: ([0-9a-f]{64})\Z")
ORIGINAL = re.compile(r"Original run: ([1-9][0-9]{0,11})\Z")
# The dedicated runtime App is an origin boundary, not a nickname for every
# GitHub Actions job with broad repository tokens.
TRUSTED_BOTS = frozenset({"portfolio-brain-v8-runtime[bot]"})
# Only explicitly reviewed functional source files may enter bot-native
# auto-merge. Test changes, scheduler/authority, privileged runtime and
# versioned governance modules require an ordinary independently reviewed PR.
LOW_RISK_BRAIN_FILES = frozenset({
    "brain/changes.py", "brain/experiments.py", "brain/fair_ci_rotation.py",
    "brain/intelligence.py", "brain/mission.py", "brain/operational_outcomes.py",
    "brain/pr_intelligence.py", "brain/project_evidence.py", "brain/projects.py",
    "brain/render.py", "brain/transfer.py", "brain/upgrades.py",
    "brain/value_actions.py",
})
MAX_FILES = 4


class DeliveryDenied(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise DeliveryDenied(reason)


def _markers(body):
    need(type(body) is str and len(body) <= 10000, "V11_PR_BODY_INVALID")
    lines = body.splitlines()
    def unique(pattern):
        matches = [m.group(1) for line in lines if (m := pattern.fullmatch(line))]
        need(len(matches) == 1, "V11_MISSING_OR_DUPLICATE_PROOF")
        return matches[0]
    return unique(OPERATION), unique(RECEIPT), int(unique(ORIGINAL))


def _original_failed_run(api, run_id, main):
    run = api.get(ROOT + "actions/runs/" + str(run_id))
    need(type(run) is dict and run.get("id") == run_id
         and run.get("name") == "brain-cycle-v2"
         and run.get("path") == ".github/workflows/brain-cycle.yml"
         and run.get("repository", {}).get("full_name") == REPO
         and run.get("head_sha") == main and run.get("head_branch") == "main"
         and run.get("status") == "completed"
         and run.get("conclusion") in {"failure", "timed_out"}
         and run.get("run_attempt") == 1
         and run.get("event") in {"schedule", "workflow_dispatch"},
         "V11_ORIGINAL_FAILURE_UNVERIFIED")
    data = api.get(ROOT + "actions/runs/" + str(run_id) + "/jobs?per_page=100")
    jobs = data.get("jobs") if type(data) is dict else None
    need(type(jobs) is list and type(data.get("total_count")) is int
         and data["total_count"] == len(jobs) < 100,
         "V11_ORIGINAL_JOB_CENSUS_INCOMPLETE")
    need(any(
        type(row) is dict and row.get("name") == "monitor"
        and row.get("run_id") == run_id and row.get("run_attempt") == 1
        and row.get("head_sha") == main and row.get("status") == "completed"
        and row.get("conclusion") in {"failure", "timed_out"}
        and factory.verified_automatic_origin(run.get("event"), row.get("steps"))
        and any(type(step) is dict
                and step.get("conclusion") in {"failure", "timed_out"}
                for step in row.get("steps", []))
        for row in jobs
    ), "V11_ORIGINAL_FAILED_STEP_OR_AUTOMATIC_ORIGIN_MISSING")


def _verify_files(api, number, head, expected):
    need(type(expected) is int and 1 <= expected <= MAX_FILES,
         "V11_REPAIR_CHANGE_BOUND")
    files = api.get(ROOT + "pulls/" + str(number) + "/files?per_page=100")
    need(type(files) is list and len(files) == expected,
         "V11_REPAIR_FILES_INCOMPLETE")
    paths = []
    for row in files:
        need(type(row) is dict and row.get("status") in {"added", "modified"}
             and factory.safe_path(row.get("filename"))
             and type(row.get("sha")) is str
             and factory.VALID_SHA.fullmatch(row["sha"]) is not None,
             "V11_REPAIR_FILE_UNSAFE")
        path = row["filename"]
        # A forged bot provenance marker must never upgrade a source patch
        # to authority over verifier, repair policies, test suite, or runtime.
        if path.startswith("brain/"):
            need(path in LOW_RISK_BRAIN_FILES and row["status"] == "modified",
                 "V11_CONTROL_PLANE_REPAIR_REVIEW_REQUIRED")
        else:
            need(path.startswith("docs/") and path.endswith(".md")
                 and row["status"] == "modified",
                 "V11_TEST_OR_UNREVIEWED_FILE_MUTATION_FORBIDDEN")
        paths.append(path)
    need(len(paths) == len(set(paths))
         and any(p in LOW_RISK_BRAIN_FILES for p in paths),
         "V11_REPAIR_SCOPE_UNVERIFIED")
    # Git-tree proof rejects symlinks, submodules and nonregular tracked files.
    gm.checked_git_tree_files(api, head, files)
    return sorted(paths)


def _check_issuers(api, head):
    checks = api.get(ROOT + "commits/" + head + "/check-runs?per_page=100")
    rows = checks.get("check_runs") if type(checks) is dict else None
    need(type(rows) is list and type(checks.get("total_count")) is int
         and len(rows) == checks["total_count"] < 100,
         "V11_CHECK_CENSUS_INCOMPLETE")
    for name, issuer in gm.REQUIRED_CHECKS.items():
        matching = [r for r in rows if type(r) is dict and r.get("name") == name]
        if name == "portfolio-phase1-gate" and not matching:
            continue  # Its REAL required GitHub status gate still blocks merge.
        need(len(matching) == 1 and matching[0].get("head_sha") == head
             and matching[0].get("app", {}).get("id") == issuer,
             "V11_CHECK_ISSUER_OR_HEAD_INVALID")
        state = (matching[0].get("status"), matching[0].get("conclusion"))
        if name == "validate":
            need(state == ("completed", "success"),
                 "V11_FOUNDATION_NOT_PASSING")
        else:
            need(state in {("queued", None), ("in_progress", None),
                           ("completed", "success")},
                 "V11_INDEPENDENT_GATE_FAILED")


def _review_threads(api, node):
    d = api.graphql(gm.THREADS_QUERY, {"id": node})
    need(type(d) is dict and not d.get("errors"),
         "V11_THREADS_UNAVAILABLE")
    item = d.get("data", {}).get("node")
    threads = item.get("reviewThreads") if type(item) is dict and item.get("id") == node else None
    need(type(threads) is dict
         and threads.get("pageInfo", {}).get("hasNextPage") is False
         and type(threads.get("nodes")) is list
         and len(threads["nodes"]) <= 100
         and all(type(x) is dict and x.get("isResolved") is True
                 for x in threads["nodes"]),
         "V11_UNRESOLVED_REVIEW")


def evaluate(api, *, main_sha, event_head):
    """Read original GitHub facts; return eligible exact PR or no candidate."""
    gm.sha(main_sha)
    gm.sha(event_head)
    need(event_head != main_sha, "V11_MAIN_IS_NOT_PR_HEAD")
    info = api.get("repos/" + REPO)
    need(gm.native_auto_merge_enabled(api, info),
         "V11_NATIVE_AUTO_MERGE_DISABLED")
    rule = api.get(ROOT + "rulesets/" + str(gm.RULESET_ID))
    gm.ruleset_passes(api, rule)
    params = next((x["parameters"] for x in rule.get("rules", [])
                   if x.get("type") == "pull_request"), {})
    need(params.get("required_review_thread_resolution") is True,
         "V11_REVIEW_THREAD_PROTECTION_MISSING")
    main = api.get(ROOT + "branches/main")
    need(main.get("protected") is True
         and main.get("commit", {}).get("sha") == main_sha,
         "V11_MAIN_DRIFT")
    prs = api.get(ROOT + "pulls?state=open&per_page=100")
    need(type(prs) is list and len(prs) < 100,
         "V11_OPEN_PR_CENSUS_INCOMPLETE")
    matches = [p for p in prs if type(p) is dict
               and p.get("head", {}).get("sha") == event_head
               and BRANCH.fullmatch(p.get("head", {}).get("ref") or "")]
    if not matches:
        return {"status": "NO_V10_REPAIR_FOR_EVENT", "writes": 0}
    need(len(matches) == 1, "V11_AMBIGUOUS_EVENT_HEAD")
    number = matches[0].get("number")
    need(type(number) is int and 0 < number < 10**9,
         "V11_PR_NUMBER_INVALID")
    pr = api.get(ROOT + "pulls/" + str(number))
    need(pr.get("number") == number and pr.get("state") == "open"
         and pr.get("draft") is True and pr.get("merged") is False
         and pr.get("auto_merge") is None
         and pr.get("user", {}).get("login") in TRUSTED_BOTS
         and pr.get("base", {}).get("ref") == "main"
         and pr.get("base", {}).get("sha") == main_sha
         and pr.get("base", {}).get("repo", {}).get("full_name") == REPO
         and pr.get("head", {}).get("repo", {}).get("full_name") == REPO
         and pr.get("head", {}).get("sha") == event_head
         and type(pr.get("node_id")) is str
         and 10 < len(pr["node_id"]) < 200,
         "V11_PR_SOURCE_UNAUTHORIZED")
    operation, receipt, run_id = _markers(pr.get("body"))
    need(pr["head"]["ref"] == "auto-repair/v10-" + operation[:16]
         and len(receipt) == 64, "V11_FACTORY_PROVENANCE_MISMATCH")
    _original_failed_run(api, run_id, main_sha)
    paths = _verify_files(api, number, event_head, pr.get("changed_files"))
    _check_issuers(api, event_head)
    _review_threads(api, pr["node_id"])
    # Final race boundary: source, rules, threads and PR still agree.
    gm.ruleset_passes(api, api.get(ROOT + "rulesets/" + str(gm.RULESET_ID)))
    _review_threads(api, pr["node_id"])
    again = api.get(ROOT + "pulls/" + str(number))
    current = api.get(ROOT + "branches/main")
    need(current.get("commit", {}).get("sha") == main_sha
         and current.get("protected") is True
         and again.get("head", {}).get("sha") == event_head
         and again.get("base", {}).get("sha") == main_sha
         and again.get("draft") is True and again.get("auto_merge") is None
         and again.get("body") == pr.get("body"),
         "V11_FINAL_SOURCE_DRIFT")
    return {
        "status": "V10_REPAIR_ELIGIBLE_FOR_NATIVE_PROTECTION",
        "pr_number": number, "pr_node": pr["node_id"],
        "head_sha": event_head, "base_sha": main_sha,
        "paths": paths, "original_failure_run_id": run_id,
        "independent_merge_gate": "GITHUB_REQUIRED_APP_5121826",
        "writes": 0,
    }


def _gh(command, *, runner=subprocess.run):
    p = runner(["gh", *command], capture_output=True, text=True,
               timeout=30, check=False)
    need(p.returncode == 0, "V11_GITHUB_NATIVE_WRITE_UNCERTAIN")
    try:
        data = json.loads(p.stdout)
    except (ValueError, TypeError) as exc:
        raise DeliveryDenied("V11_GITHUB_WRITE_READBACK_REQUIRED") from exc
    need(type(data) is dict and not data.get("errors"),
         "V11_GITHUB_WRITE_READBACK_REQUIRED")
    return data


def enroll(api, plan, *, runner=subprocess.run):
    """Convert verified bot draft to ready, enroll native auto-merge exactly once."""
    need(plan.get("status") == "V10_REPAIR_ELIGIBLE_FOR_NATIVE_PROTECTION",
         "V11_INELIGIBLE_PLAN")
    node = plan["pr_node"]
    mutation = ("mutation($id: ID!) { markPullRequestReadyForReview("
                "input: {pullRequestId: $id}) { pullRequest { id isDraft } } }")
    # This marks ready only; GitHub branch protection continues gating merge.
    answer = _gh(["api", "graphql", "-f", "query=" + mutation,
                  "-f", "id=" + node], runner=runner)
    result = answer.get("data", {}).get("markPullRequestReadyForReview")
    need(type(result) is dict and result.get("pullRequest", {}).get("id") == node
         and result["pullRequest"].get("isDraft") is False,
         "V11_READY_READBACK_UNVERIFIED")
    pr = api.get(ROOT + "pulls/" + str(plan["pr_number"]))
    main = api.get(ROOT + "branches/main")
    need(pr.get("draft") is False
         and pr.get("head", {}).get("sha") == plan["head_sha"]
         and pr.get("base", {}).get("sha") == plan["base_sha"]
         and main.get("commit", {}).get("sha") == plan["base_sha"],
         "V11_READY_SOURCE_DRIFT_NO_ENROLLMENT")
    # Native GitHub auto-merge queues the merge until BOTH genuine pinned
    # checks pass. This CLI path NEVER invokes direct/force merge APIs.
    merge = subprocess.run(
        ["gh", "pr", "merge", str(plan["pr_number"]), "--auto", "--squash",
         "--repo", REPO],
        capture_output=True, text=True, timeout=30, check=False)
    need(merge.returncode == 0, "V11_NATIVE_ENROLLMENT_UNCERTAIN")
    checked = api.get(ROOT + "pulls/" + str(plan["pr_number"]))
    need(checked.get("head", {}).get("sha") == plan["head_sha"]
         and checked.get("base", {}).get("ref") == "main"
         and (checked.get("merged") is True
              or (type(checked.get("auto_merge")) is dict
                  and checked["auto_merge"].get("merge_method") == "squash")),
         "V11_NATIVE_ENROLLMENT_READBACK_UNVERIFIED")
    return {"status": "V11_NATIVE_GITHUB_PROTECTION_ENROLLED",
            "pr_number": plan["pr_number"], "head_sha": plan["head_sha"],
            "merged": checked.get("merged") is True,
            "production_deployed": False,
            "writes": 2, "requires_independent_check": True}


def main():
    # Called from trusted main only after the real Foundation event.
    source = os.environ.get("GITHUB_SHA", "")
    head = os.environ.get("V11_EVENT_HEAD", "")
    try:
        client = gm.GitHub(os.environ.get("GH_TOKEN", ""))
        decision = evaluate(client, main_sha=source, event_head=head)
        if decision["status"] == "NO_V10_REPAIR_FOR_EVENT":
            print(json.dumps(decision, sort_keys=True))
            return 0
        outcome = enroll(client, decision)
        print(json.dumps(outcome, sort_keys=True))
        return 0
    except (DeliveryDenied, gm.Denied, ValueError, OSError,
            subprocess.SubprocessError) as e:
        # A provider write can have succeeded even if its readback failed.
        # Never emit arbitrary provider text or claim a successful merge.
        status = "BLOCKED_OR_UNCERTAIN"
        code = str(e) if isinstance(e, (DeliveryDenied, gm.Denied)) else "V11_PROVIDER_UNAVAILABLE"
        print(json.dumps({"status": status, "reason": code,
                          "merge_verified": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
