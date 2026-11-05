"""Source-bound, read-only GitHub engineering result and backlog dashboard.

Every counted outcome is tied to original GitHub PR/check/run data. Samples
never pretend to be exhaustive; deployments and billing costs stay UNKNOWN
without independent production/billing evidence. This module changes nothing.
"""
from __future__ import annotations
from datetime import datetime, timezone
from html import escape
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request

from brain.v10.engineering_factory import verified_automatic_origin
from brain.v11 import downstream_outcomes, cycle_evidence, value_funnel

REPO = "P00NSMASHER/portfolio-brain"
ROOT = "https://api.github.com/repos/" + REPO + "/"
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESPONSE = 1_800_000
MAX_READS = 20
# Bounded original provider job readbacks. This is a recent sample, never an
# exhaustive source-acceptance certification or elapsed-time observation.
MAX_CORE_CENSUS = 5
TRUSTED_CORE_WORKFLOW = ".github/workflows/brain-cycle.yml"
REQUIRED = {"validate": 15368, "portfolio-phase1-gate": 5121826}
RETIREMENT = re.compile(r"\b(?:12[\s-]*h(?:our)?|six[\s-]*hour|soak|source[\s-]*acceptance)\b", re.I)
NEVER_AUTO_CLOSE = {210, 689, 811}
OPEN_INCIDENT = re.compile(r"\b(?:failure|failures|failed|outage|incident|errors?|repair|repairs|blocked|blocker|unverified)\b", re.I)


class ReportError(ValueError):
    pass


def check(value, message):
    if not value:
        raise ReportError(message)


class GitHubReadOnly:
    """Single-host allowlisted GET transport with bounded pages and timeout."""
    def __init__(self, token):
        check(type(token) is str and 20 <= len(token) <= 4096,
              "RESULTS_TOKEN_MISSING")
        self.token, self.count = token, 0

    def get(self, route):
        check(type(route) is str
              and (route in {"branches/main", "pulls?state=all&per_page=30",
                             "issues?state=open&per_page=60",
                             "actions/runs?per_page=30", "rulesets/24182301",
                             "branches/brain-state-v2"}
                   or re.fullmatch(r"commits/[0-9a-f]{40}/check-runs\?per_page=100",
                                   route) is not None
                   or re.fullmatch(r"actions/runs/[1-9][0-9]{0,11}/jobs\?per_page=100",
                                   route) is not None),
              "RESULTS_ROUTE_DENIED")
        self.count += 1
        check(self.count <= MAX_READS, "RESULTS_READ_BUDGET_EXCEEDED")
        req = urllib.request.Request(ROOT + route, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + self.token,
            "User-Agent": "portfolio-brain-v11-observation-only",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        # Redirects cannot carry credentials to a different host.
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=10) as response:
                check(response.status == 200, "RESULTS_PROVIDER_STATUS")
                raw = response.read(MAX_RESPONSE + 1)
        except (OSError, urllib.request.URLError) as exc:
            raise ReportError("RESULTS_PROVIDER_UNAVAILABLE") from exc
        check(len(raw) <= MAX_RESPONSE, "RESULTS_PROVIDER_RESPONSE_BOUND")
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ReportError("RESULTS_PROVIDER_JSON_INVALID") from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _check_issuer(rows, sha, name, issuer):
    matches = [r for r in rows if type(r) is dict and r.get("name") == name]
    return (len(matches) == 1
            and matches[0].get("head_sha") == sha
            and matches[0].get("status") == "completed"
            and matches[0].get("conclusion") == "success"
            and matches[0].get("app", {}).get("id") == issuer)


def _verification(api, head):
    check(type(head) is str and SHA.fullmatch(head) is not None,
          "RESULTS_PR_HEAD_INVALID")
    document = api.get("commits/" + head + "/check-runs?per_page=100")
    rows = document.get("check_runs") if type(document) is dict else None
    if (type(rows) is not list or type(document.get("total_count")) is not int
            or len(rows) != document["total_count"] or len(rows) >= 100):
        return "UNKNOWN_CHECK_CENSUS_INCOMPLETE"
    return ("VERIFIED_BOTH_APPS"
            if all(_check_issuer(rows, head, name, issuer)
                   for name, issuer in REQUIRED.items())
            else "NOT_BOTH_APPS_VERIFIED")


def _issue_class(row):
    number = row.get("number")
    title = row.get("title")
    check(type(number) is int and type(title) is str,
          "RESULTS_ISSUE_INVALID")
    if number in NEVER_AUTO_CLOSE:
        return "ACTIVE_REVIEW_REQUIRED"
    # An obsolete waiting rule does not erase an original failed repair.
    # Title is the owning issue classification; arbitrary body mentions of
    # historical source acceptance never retire unrelated active incidents.
    if OPEN_INCIDENT.search(title):
        return "OPEN_INCIDENT_REVIEW_REQUIRED"
    if RETIREMENT.search(title):
        return "RETIRED_POLICY_REVIEW_CANDIDATE"
    return "ACTIVE_OR_UNRECONCILED"



def _original_core_verdict(api, row, source_sha):
    """Only original GitHub job and authenticated schedule may count as core."""
    if not (type(row) is dict and row.get("name") == "brain-cycle-v2"
            and row.get("path") == TRUSTED_CORE_WORKFLOW
            and row.get("head_sha") == source_sha
            and row.get("head_branch") == "main"
            and type(row.get("repository")) is dict
            and row["repository"].get("full_name") == REPO
            and type(row.get("run_attempt")) is int and row["run_attempt"] == 1
            and row.get("status") == "completed"
            and row.get("conclusion") in {"success", "failure", "timed_out"}
            and row.get("event") in {"schedule", "workflow_dispatch"}
            and type(row.get("id")) is int and 0 < row["id"] < 10**12):
        return "SOURCE_ORIGIN_UNVERIFIED"
    jobs = api.get("actions/runs/" + str(row["id"]) + "/jobs?per_page=100")
    records = jobs.get("jobs") if type(jobs) is dict else None
    if not (type(records) is list
            and type(jobs.get("total_count")) is int
            and len(records) == jobs["total_count"] < 100):
        return "JOB_CENSUS_INCOMPLETE"
    matching = [j for j in records if type(j) is dict and
                j.get("name") == "monitor"]
    if len(matching) != 1:
        return "ORIGINAL_MONITOR_UNVERIFIED"
    job = matching[0]
    if not (job.get("run_id") == row["id"]
            and job.get("run_attempt") == 1
            and job.get("head_sha") == source_sha
            and job.get("status") == "completed"
            and job.get("conclusion") == row["conclusion"]
            and type(job.get("steps")) is list
            and len(job["steps"]) > 0
            and verified_automatic_origin(row["event"], job["steps"])):
        return "AUTOMATIC_CORE_PROVENANCE_UNVERIFIED"
    return "ORIGINAL_SUCCESS" if row["conclusion"] == "success" else "ORIGINAL_FAILURE"


def report(api, *, expected_main, generated_at):
    check(type(expected_main) is str and SHA.fullmatch(expected_main) is not None,
          "RESULTS_MAIN_INVALID")
    check(type(generated_at) is str and generated_at.endswith("Z"),
          "RESULTS_TIME_INVALID")
    main = api.get("branches/main")
    check(type(main) is dict and main.get("protected") is True
          and main.get("commit", {}).get("sha") == expected_main,
          "RESULTS_MAIN_MOVED")
    rules = api.get("rulesets/24182301")
    check(type(rules) is dict and rules.get("enforcement") == "active"
          and rules.get("conditions", {}).get("ref_name", {}).get("include") ==
          ["refs/heads/main"]
          and ("bypass_actors" not in rules or rules["bypass_actors"] == []),
          "RESULTS_PROTECTION_NOT_CONFIRMED")
    statuses = [r["parameters"] for r in rules.get("rules", [])
                if r.get("type") == "required_status_checks"]
    check(len(statuses) == 1
          and statuses[0].get("strict_required_status_checks_policy") is True
          and {(v.get("context"), v.get("integration_id")) for v in
               statuses[0].get("required_status_checks", [])} >=
          set(REQUIRED.items()), "RESULTS_REQUIRED_CHECKS_CHANGED")
    prs = api.get("pulls?state=all&per_page=30")
    issues = api.get("issues?state=open&per_page=60")
    runs_document = api.get("actions/runs?per_page=30")
    check(type(prs) is list and len(prs) <= 30
          and type(issues) is list and len(issues) <= 60
          and type(runs_document) is dict
          and type(runs_document.get("workflow_runs")) is list
          and len(runs_document["workflow_runs"]) <= 30,
          "RESULTS_PROVIDER_SAMPLE_INVALID")
    # Treat all counts as sampled, never global repo totals.
    merged = [p for p in prs if type(p) is dict
              and p.get("merged_at") and p.get("merge_commit_sha")]
    verified_rows = []
    for p in merged[:8]:
        head = p.get("head", {}).get("sha")
        if type(head) is str and SHA.fullmatch(head):
            status = _verification(api, head)
        else:
            status = "UNKNOWN_PR_HEAD"
        verified_rows.append({
            "number": p.get("number"),
            "title": str(p.get("title") or "")[:160],
            "merged_sha": p.get("merge_commit_sha"),
            "head_sha": head,
            "verification": status,
            "merged_at": p.get("merged_at"),
            "downstream_completion": "UNVERIFIED_NO_LIVE_REPLAY",
        })
    open_issues = []
    for row in issues:
        if type(row) is not dict or "pull_request" in row:
            continue
        state = _issue_class(row)
        open_issues.append({"number": row["number"],
                            "title": row["title"][:160], "classification": state,
                            "updated_at": row.get("updated_at")})
    recent_runs = [
        {"name": run.get("name"), "run_id": run.get("id"),
         "conclusion": run.get("conclusion"), "status": run.get("status")}
        for run in runs_document["workflow_runs"]
        if type(run) is dict and run.get("head_sha") == expected_main
    ]
    relevant_cores = [
        run for run in runs_document["workflow_runs"]
        if type(run) is dict and run.get("name") == "brain-cycle-v2"
        and run.get("head_sha") == expected_main
        and run.get("status") == "completed"
        and run.get("conclusion") in {"success", "failure", "timed_out"}
    ]
    core_verifications = [
        {"run_id": run.get("id"), "event": run.get("event"),
         "outcome": _original_core_verdict(api, run, expected_main)}
        for run in relevant_cores[:MAX_CORE_CENSUS]
    ]
    repair_prs = [p for p in prs if type(p) is dict and
                  (str(p.get("title") or "").lower().startswith(("fix", "repair"))
                   or str(p.get("head", {}).get("ref", "")).startswith("auto-repair/"))]
    return {
        "schema_version": 1, "authority": "OBSERVE_ONLY",
        "repository": REPO, "main_sha": expected_main,
        "generated_at": generated_at,
        "source": "ORIGINAL_GITHUB_API",
        "ruleset_bypass_visibility": ("VERIFIED_EMPTY" if "bypass_actors" in rules
                                       else "NOT_VISIBLE_TO_TOKEN"),
        "coverage": {"pull_requests": "PARTIAL_OR_UNKNOWN" if len(prs) == 30 else "RECENT_SAMPLE_ONLY",
                     "issues": "PARTIAL" if len(issues) == 60 else "OPEN_ISSUES_SAMPLE",
                     "run_history": "LATEST_30_MAX",
                     "core_runs_checked": len(core_verifications),
                     "core_runs_unchecked": max(0, len(relevant_cores) - MAX_CORE_CENSUS),
                     "checked_merged_prs": len(verified_rows)},
        "metrics": {
            "repair_prs_seen_in_sample": len(repair_prs),
            "repair_prs_merged_in_sample": sum(bool(p.get("merged_at")) for p in repair_prs),
            "merged_prs_seen_in_sample": len(merged),
            "merged_prs_verified_by_both_apps": sum(
                x["verification"] == "VERIFIED_BOTH_APPS" for x in verified_rows),
            "main_cycle_successes_in_sample": sum(
                x["outcome"] == "ORIGINAL_SUCCESS" for x in core_verifications),
            "main_cycle_failures_in_sample": sum(
                x["outcome"] == "ORIGINAL_FAILURE" for x in core_verifications),
            "unverified_main_cycle_runs_in_sample": sum(
                not x["outcome"].startswith("ORIGINAL_")
                for x in core_verifications),
            "open_issue_sample": len(open_issues),
            "historical_retired_issue_candidates": sum(
                x["classification"] == "RETIRED_POLICY_REVIEW_CANDIDATE"
                for x in open_issues),
            "open_incident_review_count": sum(
                x["classification"] == "OPEN_INCIDENT_REVIEW_REQUIRED"
                for x in open_issues),
            "production_deployments_verified": None,
            "actual_operating_cost_usd": None,
            "all_repo_repairs_completed": None,
        },
        "uncertainty": {
            "production_deployments_verified": "NO_PRODUCTION_RECEIPT_READ",
            "all_repo_repairs_completed": "UNREGISTERED_TARGETS_NOT_CENSUSED",
            "actual_operating_cost_usd": "NO_BILLING_PROVIDER_DATA",
            "retired_issue_candidates": "REVIEW_ONLY_NOT_AUTOCLOSED",
            "green_actions": "WORKFLOW_SUCCESS_IS_NOT_REPAIR_OR_BUSINESS_OUTCOME",
            "verified_core_scope": "FIRST_ATTEMPT_SOURCE_AND_AUTHENTIC_ORIGIN_ONLY",
            "unverified_core_runs": "NOT_COUNTED_AS_SUCCESS_OR_FAILURE",
        },
        "merged_pr_evidence": verified_rows,
        "backlog_evidence": sorted(
            open_issues, key=lambda x: (
                {"OPEN_INCIDENT_REVIEW_REQUIRED": 0,
                 "ACTIVE_REVIEW_REQUIRED": 1,
                 "ACTIVE_OR_UNRECONCILED": 2,
                 "RETIRED_POLICY_REVIEW_CANDIDATE": 3}.get(x["classification"], 4),
                x["number"])),
        "core_run_evidence": recent_runs[:12],
        "core_run_verifications": core_verifications,
    }


def html_report(data):
    """Standalone local HTML artifact, escaped and with no scripts or network."""
    m = data["metrics"]
    def number(value):
        return "UNKNOWN" if value is None else str(value)
    cards = "".join(
        "<div class='card'><small>" + escape(key.replace("_", " ").title()) +
        "</small><strong>" + escape(number(value)) + "</strong></div>"
        for key, value in m.items())
    def table(rows, cols, url_field=None):
        head = "".join("<th>" + escape(k.replace("_", " ").title()) + "</th>"
                       for k in cols)
        body = []
        for row in rows:
            cells = []
            for key in cols:
                value = row.get(key)
                content = escape(number(value))
                if key == "number" and type(value) is int:
                    target = "issues" if url_field == "issues" else "pull"
                    content = "<a href='https://github.com/" + REPO + "/" + target + \
                              "/" + str(value) + "'>" + content + "</a>"
                cells.append("<td>" + content + "</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return ("<table><thead><tr>" + head + "</tr></thead><tbody>" +
                "".join(body) + "</tbody></table>")
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio Brain: Verified Execution Results</title>
<style>body{font:15px system-ui,sans-serif;max-width:1100px;margin:36px auto;
padding:0 18px;background:#f6f7f9;color:#202b35}h1{font-size:30px}
h2{margin-top:32px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
gap:10px}.card{border:1px solid #dce2e7;background:white;border-radius:12px;
padding:16px}.card small{display:block;color:#5d6d79;margin-bottom:8px}
.card strong{font-size:25px}table{width:100%;border-collapse:collapse;background:white}
th,td{text-align:left;border:1px solid #dfe5e8;padding:10px;vertical-align:top}
th{background:#e8edf1}a{color:#175e92}.note{font-size:13px;color:#546575}
</style><main><h1>Portfolio Brain: Verified Execution Results</h1>""" + (
        "<p class='note'>Source: original GitHub API | Main: <code>" +
        escape(data["main_sha"]) + "</code> | Generated: " +
        escape(data["generated_at"]) + ". Read-only; sampled results, not global totals.</p>"
        "<section class='grid'>" + cards + "</section>" +
        ("<h2>Original core: storage and useful work</h2>" +
         table([data["cycle_accounting"]],
               ["run_id", "state_growth_raw_bytes", "raw_headroom_bytes",
                "compressed_headroom_bytes", "observed_new_source_candidates",
                "unchanged_source_events_coalesced", "unreleased_owner_jobs",
                "activity_classification", "state_tip_status"])
         if "cycle_accounting" in data else "") +
        ("<h2>Discovery to delivery: verified evidence</h2>" +
         table([data["outcome_funnel"]],
               ["discovered_source_revisions", "operator_linked_review_candidates",
                "independently_verified_reviews", "source_linked_protected_merges",
                "source_linked_live_behavior_repairs", "verified_customer_revenue",
                "verified_saved_engineering_hours"])
         if "outcome_funnel" in data else "") +
        "<h2>Original merged PR evidence</h2>" +
        table(data["merged_pr_evidence"],
              ["number", "title", "verification", "downstream_completion", "merged_at"]) +
        ("<h2>Registered real-world repair verification</h2>" +
         table(data["downstream_completion"]["results"],
               ["pr_number", "repository", "status", "reason"]) +
         "<p class='note'>Only preapproved registered candidates are inspected. "
         "No approved candidates is not a verified zero across the portfolio.</p>"
         if "downstream_completion" in data else "") +
        "<h2>Open-issue backlog and retired-policy candidates</h2>" +
        table(data["backlog_evidence"],
              ["number", "title", "classification"], url_field="issues") +
        "<p class='note'>Candidates are NOT automatically closed. Old failure "
        "records remain authoritative. No green check proves deployment or revenue.</p>"
        "</main></html>")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-main", required=True)
    parser.add_argument("--json", required=True)
    parser.add_argument("--html", required=True)
    parser.add_argument("--core-artifacts")
    parser.add_argument("--core-run-id", type=int)
    parser.add_argument("--core-run-attempt", type=int)
    args = parser.parse_args(argv)
    try:
        at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        api = GitHubReadOnly(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", ""))
        outcome = report(api, expected_main=args.expected_main, generated_at=at)
        # Existing after-core read-only job: independently replay only targets
        # recorded on this protected exact-source checkout, never infer
        # success from the dashboard's PR/check sample.
        candidate_file = Path("repair/V11_DOWNSTREAM_CANDIDATES.json")
        check(candidate_file.is_file() and not candidate_file.is_symlink()
              and 0 < candidate_file.stat().st_size <= 4096,
              "RESULTS_DOWNSTREAM_REGISTRY_MISSING_OR_UNSAFE")
        registered = downstream_outcomes._json(
            candidate_file.read_text(encoding="utf-8"),
            "RESULTS_DOWNSTREAM_REGISTRY_INVALID")
        result = downstream_outcomes.replay_registered_targets(
            registered,
            lambda: downstream_outcomes.GitHubReadOnly(
                os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")),
            downstream_outcomes.live_get)
        outcome["downstream_completion"] = result
        outcome["metrics"]["registered_real_world_repairs_verified"] = (
            result["verified_real_world_repairs"])
        outcome["metrics"]["registered_repairs_held"] = (
            result["unverified_candidates"])
        knowledge = Path("brain/REUSE_KNOWLEDGE.json")
        links_file = Path("repair/V11_OUTCOME_LINKS.json")
        check(knowledge.is_file() and not knowledge.is_symlink()
              and 0 < knowledge.stat().st_size <= 128_000
              and links_file.is_file() and not links_file.is_symlink()
              and 0 < links_file.stat().st_size <= 12_000,
              "RESULTS_FUNNEL_SOURCE_MISSING_OR_UNSAFE")
        funnel = value_funnel.summarize(
            json.loads(knowledge.read_text(encoding="utf-8")),
            json.loads(links_file.read_text(encoding="utf-8")),
            outcome["merged_pr_evidence"], result)
        outcome["outcome_funnel"] = funnel
        outcome["metrics"]["discovered_source_revisions"] = funnel["discovered_source_revisions"]
        outcome["metrics"]["source_linked_protected_merges"] = funnel["source_linked_protected_merges"]
        outcome["metrics"]["source_linked_live_behavior_repairs"] = funnel["source_linked_live_behavior_repairs"]
        outcome["metrics"]["independently_verified_reviews"] = funnel["independently_verified_reviews"]
        outcome["metrics"]["verified_customer_revenue"] = funnel["verified_customer_revenue"]
        parameters = (args.core_artifacts, args.core_run_id, args.core_run_attempt)
        check(all(value is None for value in parameters) or
              all(value is not None for value in parameters),
              "RESULTS_CORE_EVIDENCE_PARAMETERS_INCOMPLETE")
        if args.core_artifacts is not None:
            account = cycle_evidence.inspect(
                args.core_artifacts, source_sha=args.expected_main,
                run_id=args.core_run_id, run_attempt=args.core_run_attempt)
            tip = api.get("branches/brain-state-v2")
            check(type(tip) is dict and type(tip.get("commit")) is dict
                  and type(tip["commit"].get("sha")) is str
                  and SHA.fullmatch(tip["commit"]["sha"]),
                  "RESULTS_STATE_TIP_UNVERIFIED")
            account["state_tip_status"] = (
                "LATEST_COMMIT_CONFIRMED" if
                tip["commit"]["sha"] == account["state_commit"] else
                "HISTORICAL_DELIVERY_NOT_CURRENT")
            outcome["cycle_accounting"] = account
            outcome["metrics"]["core_cycle_growth_raw_bytes"] = account["state_growth_raw_bytes"]
            outcome["metrics"]["core_cycle_new_candidates"] = account["observed_new_source_candidates"]
            outcome["metrics"]["core_cycle_coalesced_unchanged"] = account["unchanged_source_events_coalesced"]
            outcome["metrics"]["core_cycle_functional_release_verified"] = None
        for name, body in ((args.json, json.dumps(outcome, indent=2, sort_keys=True) + "\n"),
                           (args.html, html_report(outcome))):
            path = Path(name)
            check(path.parent.is_dir() and not path.exists() and not path.is_symlink(),
                  "RESULTS_OUTPUT_PATH_INVALID")
            with path.open("x", encoding="utf-8") as fp:
                fp.write(body)
        print(json.dumps({"status": "SAMPLED_PROVIDER_EVIDENCE_SAVED",
                          "main_sha": args.expected_main,
                          "production_verified": False, "provider_writes": 0}))
        return 0
    except (ReportError, OSError, ValueError):
        print(json.dumps({"status": "RESULTS_UNAVAILABLE_NOT_ZERO",
                          "provider_writes": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
