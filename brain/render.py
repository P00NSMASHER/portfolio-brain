"""Private report publication with per-file atomic replacement.

Every output carries potentially sensitive source evidence. Validate all
existing targets before staging, never chmod unrelated directories/files, and
never write confidential bytes through a pre-existing destination alias.
"""
import html
import json
import os
import secrets
import stat
from pathlib import Path

from brain.core import BrainError, require


_REPORT_NAMES = ("report.md", "report.html", "report.json")
_TEST_LOG_NAMES = ("tests.txt",)


def _assert_private_target(directory, name):
    """Reject symlinks, hard links and non-regular target files."""
    try:
        old = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return
    require(
        stat.S_ISREG(old.st_mode) and old.st_nlink == 1,
        "REPORT_OUTPUT_SYMLINK_HARDLINK_OR_NONFILE_REFUSED",
    )


def _write_private_bundle(output, contents, *, names=_REPORT_NAMES):
    """Publish allowlisted private files without truncating destination inodes.

    Individual renames are atomic, but a three-file report is not one
    filesystem transaction. Machine-readable JSON is published LAST so
    interrupted renders cannot advance its canonical receipt prematurely.
    """
    out = Path(output)
    require(
        names in (_REPORT_NAMES, _TEST_LOG_NAMES)
        and set(contents) == set(names),
        "REPORT_OUTPUT_SCHEMA_INVALID",
    )
    for part in (out, *out.parents):
        require(not part.is_symlink(), "REPORT_OUTPUT_SYMLINK_DIRECTORY_REFUSED")

    created = False
    try:
        out.mkdir(parents=True, mode=0o700, exist_ok=False)
        created = True
    except FileExistsError:
        pass

    try:
        directory = os.open(out, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise BrainError("REPORT_OUTPUT_UNSAFE_DIRECTORY") from exc

    staged = []
    try:
        # Existing aliases are rejected before any new receipt is installed.
        for name in names:
            _assert_private_target(directory, name)
        if created:
            os.fchmod(directory, 0o700)
        else:
            require(
                stat.S_IMODE(os.fstat(directory).st_mode) == 0o700,
                "REPORT_OUTPUT_EXISTING_DIRECTORY_NOT_PRIVATE",
            )

        try:
            for name in names:
                temp_name = ".report-" + secrets.token_hex(12) + ".tmp"
                handle = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                staged.append((name, temp_name))
                with os.fdopen(handle, "w", encoding="utf-8") as target:
                    os.fchmod(target.fileno(), 0o600)
                    target.write(contents[name])
                    target.flush()
                    os.fsync(target.fileno())
            for name, temp_name in staged[:]:
                # Recheck against a target changed while the temp was written.
                _assert_private_target(directory, name)
                os.replace(
                    temp_name, name,
                    src_dir_fd=directory, dst_dir_fd=directory,
                )
                staged.remove((name, temp_name))
            os.fsync(directory)
        except OSError as exc:
            raise BrainError("REPORT_OUTPUT_PRIVATE_WRITE_FAILED") from exc
    finally:
        try:
            for _, temp_name in staged:
                try:
                    os.unlink(temp_name, dir_fd=directory)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory)


def write_private_test_log(output, contents):
    """Write only the preflight tests.txt using the report privacy contract."""
    require(type(contents) is str, "REPORT_OUTPUT_SCHEMA_INVALID")
    _write_private_bundle(output, {"tests.txt": contents}, names=_TEST_LOG_NAMES)


def investigation_summary_lines(receipt):
    """Human-readable private projection, never authority or a state update."""
    require(receipt.get("scope") == "READ_ONLY_AUTONOMOUS_CHECK_REVALIDATION",
            "INVESTIGATION_RECEIPT_SCOPE_INVALID")

    def safe(value):
        value = str(value).replace("\r", " ").replace("\n", " ")
        value = value.replace("\\", "\\\\")
        for char in ("*", "_", "[", "]", "<", ">", "`", "|"):
            value = value.replace(char, "\\" + char)
        return value

    def label(value):
        code = str(value)
        if code and len(code) <= 100 and all(char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_" for char in code):
            return "`" + code + "`"
        return safe(value)
    items = receipt.get("investigations", [])
    require(type(items) is list and len(items) <= 3, "INVESTIGATION_RECEIPT_LIMIT")
    lines = [
        "", "## Autonomous read-only check revalidation", "",
        "Observed checks are NOT root cause verification, production benefit or incident closure.",
        "No repairs, merges, permission grants, trades or downstream GitHub writes occurred.",
        f'Status: {label(receipt.get("status", "UNKNOWN"))}; '
        f'Eligible: {receipt.get("eligible_count", 0)}; '
        f'Investigated: {len(items)}; '
        f'Deferred: {receipt.get("deferred_count", 0)}; '
        f'Requests used: {receipt.get("requests_used", 0)}.',
    ]
    if not items:
        lines.append("No eligible failure was revalidated in this one-shot pass.")
    for row in items:
        lines.append(
            "- " + safe(row.get("repository", "UNKNOWN")) + ": "
            + label(row.get("outcome", "UNKNOWN"))
            + "; follow-up class "
            + label(row.get("follow_up_kind", "INITIAL_ADVERSE_TRANSITION"))
            + "; original revision " + safe(row.get("expected_revision", "UNKNOWN"))
            + "; newly observed revision " + safe(row.get("observed_revision") or "UNAVAILABLE")
            + "; original evidence " + safe((row.get("source_refs") or ["UNAVAILABLE"])[0])
        )
        for check in row.get("checks", []):
            lines.append(
                "  - Check " + safe(check.get("name", "UNKNOWN")) + ": "
                + label(check.get("outcome", "UNKNOWN"))
                + "; original evidence class "
                + label(check.get("original_evidence_class",
                                  row.get("follow_up_kind", "INITIAL_ADVERSE_TRANSITION")))
                + "; evidence " + safe(check.get("source_ref") or "UNAVAILABLE")
            )
            evidence = check.get("historical_observations")
            if evidence is not None:
                require(type(evidence) is dict,
                        "TEMPORAL_PRIVATE_EVIDENCE_OBJECT_INVALID")
                lines.append(
                    "    - Original ledger's recent completed samples: "
                    + safe(evidence.get("terminal_samples", "UNKNOWN"))
                    + "; consecutive adverse observations: "
                    + safe(evidence.get("adverse_streak_samples", "UNKNOWN"))
                    + "; first observed in this adverse sample streak: "
                    + safe(evidence.get("adverse_streak_first_observed_at") or "UNAVAILABLE")
                    + "; observed adverse/success changes: "
                    + safe(evidence.get("adverse_success_flips_observed", "UNKNOWN"))
                    + "; 12-sample display cap reached: "
                    + safe(evidence.get("capped_at_12_samples", "UNKNOWN"))
                )
    lines.append("Past sampled check conclusions are NOT continuous outage duration, root cause, or confirmed test flakiness.")
    lines.append("Any successful check is an observation, not an independently confirmed resolution.")
    return lines

def write_report(report, output):
    raw=json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)
    lines=["# Portfolio Brain", "", f'Status: {report.get("status", "UNKNOWN")}', "", f'Source: {report.get("source_sha", "UNAVAILABLE")}', "", "Read-only research. Structural code evidence is not proof of production usefulness or revenue.", ""]
    if report.get("scope") == "READ_ONLY_AUTONOMOUS_CHECK_REVALIDATION":
        lines.extend(investigation_summary_lines(report))
        from brain.review import review_lines
        lines.extend(review_lines(report))
    for repo in report.get("repositories",[]):
        failed=[x["name"] for x in repo["checks"] if x["conclusion"] not in {"success","neutral",None}]
        lines.append(f'- {repo["repository"]}: `{repo["head_sha"]}`; adverse checks: {", ".join(failed) or "none observed"}; [{repo["source_ref"]}]({repo["source_ref"]})')
    lines.extend(["", "## Repository changes since prior observation", ""])
    changes = report.get("repository_changes", [])
    if not changes:
        lines.append("No repository has two distinct observed snapshots yet.")
    for change in changes:
        facts = []
        if change["revision_changed"]:
            facts.append(
                f'revision {change["previous_revision"][:8]} → {change["current_revision"][:8]}'
            )
        tally = change["open_issue_pr_tally"]["net_delta"]
        if tally:
            facts.append(f'open GitHub issue/PR tally {tally:+d}')
        if change["check_deteriorations"]:
            names = ", ".join(row["name"] for row in change["check_deteriorations"])
            facts.append(f'observed adverse check transitions: {names}')
        if change["check_recoveries"]:
            names = ", ".join(row["name"] for row in change["check_recoveries"])
            facts.append(f'observed recovered check transitions: {names}')
        if change["check_comparison"] != "COMPARABLE":
            facts.append(f'check comparability: {change["check_comparison"]}')
        if change["evidence_quality"] == "ACTUAL_STALE_BASELINE":
            facts.append(
                "earlier snapshot exceeds the freshness window; "
                "the timing of these differences is not established"
            )
        lines.append(
            f'- {change["repository"]} ({change["previous_observed_at"]} to '
            f'{change["current_observed_at"]}; {change["evidence_quality"]}): '
            + ("; ".join(facts) if facts else "no measured changes")
        )
    lines.append(
        "GitHub's open_issues_count includes pull requests. Check transitions require "
        "the same commit and uniquely named completed checks; these are observations, "
        "not causes, verified usefulness, or revenue."
    )
    if (
        report.get("status") == "PASS"
        and report.get("scope") == "READ_ONLY_BUSINESS_PORTFOLIO_INTELLIGENCE"
    ):
        from brain.triage import decision_queue

        def _review_text(value):
            # Markdown is a separate consumer of original public metadata.
            # Prevent untrusted repository names/paths from injecting markup.
            sanitized = str(value).replace("\\", "\\\\")
            for char in ("`", "*", "_", "[", "]", "<", ">", "|"):
                sanitized = sanitized.replace(char, "\\" + char)
            return sanitized.replace("\n", " ").replace("\r", " ")

        queue = decision_queue(report)
        lines.extend(["", "## Evidence-gated decision queue (human review only)", ""])
        lines.append(
            "These are observations and proposed checks, NOT verified benefits, "
            "license permission, instructions to trade or authorization to execute."
        )
        if not queue["items"]:
            lines.append("No currently eligible evidence-backed review proposals.")
        for item in queue["items"]:
            context = item["metadata"].get(
                "repository", item["metadata"].get("target", "")
            )
            license_note = ""
            if item["category"] == "REVIEW_THIRD_PARTY_SOURCE":
                status = item["metadata"]["license_review_status"]
                license_note = (
                    " Declared license metadata: "
                    + _review_text(item["metadata"]["license_metadata_only"])
                    + " ("
                    + (
                        "missing/inconclusive; review rights before reuse"
                        if status == "MISSING_OR_INCONCLUSIVE_LICENSE_METADATA"
                        else "unverified declaration; review rights before reuse"
                    )
                    + ")."
                )
            # Keep every important caveat visible in the text a reviewer
            # actually reads; the pure queue does not grant any permission.
            all_limits = "; ".join(
                _review_text(limitation) for limitation in item["limitations"]
            )
            lines.append(
                "- Review " + str(item["review_order_not_value_rank"])
                + " [" + item["band"] + " / " + item["category"] + "] "
                + _review_text(context) + ": " + item["headline"]
                + " Next: " + item["next_step"]
                + " Evidence: " + _review_text(item["source_refs"][0])
                + "." + license_note + " Limitations: " + all_limits
            )
        lines.append(
            "The order is a deterministic review rule, not a probability, "
            "ROI estimate, adoption claim or urgency deadline. "
            "No provider queries, state writes or downstream actions occurred."
        )
    lines.extend(["", "## Reusable code to evaluate", ""])
    for candidate in report.get("reuse_candidates",[])[:10]:
        lines.append(f'- [{candidate["repository"]}/{candidate["path"]}]({candidate["source_ref"]}) — {candidate["target"]}; structural score {candidate["reuse_score"]}; license {candidate["license"]}; {candidate["utility_evidence"]}')
    lines.extend(["", "## Business opportunities", ""])
    for opportunity in report.get("business_opportunities",[]):
        lines.append(f'- {opportunity["target"]}: {opportunity["hypothesis"]} Customer demand {opportunity["customer_demand"]}; revenue {opportunity["revenue"]}.')
    lines.extend(["", "## Experiments", ""])
    for exp in report.get("learning",{}).get("experiments",[]):
        lines.append(f'- {exp["experiment"]}: {exp["dataset_kind"]}, {exp["cases"]} cases, equal outputs, {exp["baseline_operations"]} → {exp["candidate_operations"]} defined operations. {exp["scope"]}')
    html_text = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Portfolio Brain</title><style>body{font:16px system-ui;max-width:960px;margin:32px auto;padding:16px;color:#16304b;background:#f3f7fb}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:24px;border-radius:16px}</style><pre>' + html.escape("\n".join(lines)) + '</pre>')
    _write_private_bundle(output, {
        "report.md": "\n".join(lines) + "\n",
        "report.html": html_text,
        "report.json": raw + "\n",
    })
