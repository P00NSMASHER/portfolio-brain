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


def _write_private_bundle(output, contents):
    """Publish three private files without truncating existing destination inodes.

    Individual renames are atomic, but a three-file bundle is not one atomic
    filesystem transaction. Publish machine-readable JSON LAST so an
    interrupted render does not advance its canonical receipt prematurely.
    """
    out = Path(output)
    require(set(contents) == set(_REPORT_NAMES), "REPORT_OUTPUT_SCHEMA_INVALID")
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
        for name in _REPORT_NAMES:
            _assert_private_target(directory, name)
        if created:
            os.fchmod(directory, 0o700)
        else:
            require(
                stat.S_IMODE(os.fstat(directory).st_mode) == 0o700,
                "REPORT_OUTPUT_EXISTING_DIRECTORY_NOT_PRIVATE",
            )

        try:
            for name in _REPORT_NAMES:
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


def write_report(report, output):
    raw=json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)
    lines=["# Portfolio Brain", "", f'Status: {report.get("status", "UNKNOWN")}', "", f'Source: {report.get("source_sha", "UNAVAILABLE")}', "", "Read-only research. Structural code evidence is not proof of production usefulness or revenue.", ""]
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
