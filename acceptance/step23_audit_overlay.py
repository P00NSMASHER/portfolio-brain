"""Read-only supplemental audit of a frozen main; never merge this lane during a soak."""
from __future__ import annotations
import argparse, ast, hashlib, json, os, shutil, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

TARGET = "ca2ae77fa0314777bbc8591e3b2507b2effa43b5"
START = "2026-10-05T22:00:00Z"
END = "2026-10-05T23:00:00Z"
EXPECTED_COLLECTOR = "afb62a02e887ec55220c99186d03a0b5beda0893"
EXPECTED_TEST = "edcf7fb1583fafadb742be17e0e0d06cb97991d8"
WORKFLOWS = ["portfolio-state-reducer", "runtime-hourly-sync",
 "portfolio-autonomous-scheduler", "hunter-autonomous-cycle", "agent-heartbeat-sweep",
 "portfolio-cost-watchdog", "portfolio-notification-cycle", "command-center-pages"]

IMPORT = """from acceptance.soak_observation import (
    ObservationChanged, scheduled_runs as stable_scheduled_runs,
    reset_history, final_census_unchanged, write_failure_progress,
)
"""
OLD_RESET = '''            grouped = scheduled_runs(gh, workflows, exact_sha, effective_start)
            reset = find_real_reset(grouped)
            if reset is not None:
                reset_at, reason = reset
                resets.append(
                    {
                        "previous_start": effective_start.isoformat().replace("+00:00", "Z"),
                        "reset_at": reset_at.isoformat().replace("+00:00", "Z"),
                        "reason": reason,
                    }
                )
                if len(resets) > max_resets:
                    raise RuntimeError("STEP23_MAX_RESETS_EXCEEDED")
                effective_start = reset_at
                pending_start = pending_event_count(token)
                print(json.dumps({"status": "SOAK_RESET", "reason": reason, "new_start": resets[-1]["reset_at"]}))
                continue
'''
NEW_RESET = '''            try:
                all_grouped = scheduled_runs(gh, workflows, exact_sha, window_start)
            except ObservationChanged as exc:
                waiting({"status": "WAITING_FOR_STABLE_RUN_LIST", "reason": str(exc)})
                continue
            observed_resets, observed_start = reset_history(
                all_grouped, window_start, max_resets, cancellation_is_coalesced,
            )
            if observed_resets != resets:
                resets = observed_resets
                effective_start = observed_start
                pending_start = pending_event_count(token)
                print(json.dumps({"status": "SOAK_RESET", "reset_count": len(resets),
                                  "new_start": effective_start.isoformat()}))
            grouped = {
                name: [row for row in rows if parse_time(row["created_at"]) >= effective_start]
                for name, rows in all_grouped.items()
            }
'''
OLD_FINAL = '''            assert_main()
            receipt = bind_receipt(
'''
NEW_FINAL = '''            assert_main()
            try:
                final_grouped = scheduled_runs(gh, workflows, exact_sha, window_start)
            except ObservationChanged as exc:
                waiting({"status": "WAITING_FOR_STABLE_FINAL_CENSUS", "reason": str(exc)})
                continue
            if not final_census_unchanged(all_grouped, final_grouped):
                waiting({"status": "WAITING_FOR_STABLE_FINAL_CENSUS"})
                continue
            assert_main()
            receipt = bind_receipt(
'''
OLD_ENTRY = '''if __name__ == "__main__":
    main()
'''
NEW_ENTRY = '''if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import sys
        write_failure_progress(sys.argv[1:], exc)
        raise
'''


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Patch precondition failed: {label}; source changed, no files written")
    return text.replace(old, new, 1)


def transform_collector(text: str) -> str:
    tree = ast.parse(text)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "scheduled_runs"]
    if len(nodes) != 1:
        raise RuntimeError("Expected exactly one scheduled_runs implementation")
    node = nodes[0]
    lines = text.splitlines(keepends=True)
    replacement = '''def scheduled_runs(gh: GH, workflows: set[str], exact_sha: str, start: datetime) -> dict[str, list[dict[str, Any]]]:
    # Membership races produce a pending observation. Status progress is normal.
    return stable_scheduled_runs(gh, workflows, exact_sha, start, max_attempts=1)
'''
    text = "".join(lines[:node.lineno-1]) + replacement + "".join(lines[node.end_lineno:])
    text = replace_once(text, "from acceptance.final_acceptance import bind_receipt, validate_step23\n",
                        "from acceptance.final_acceptance import bind_receipt, validate_step23\n" + IMPORT, "imports")
    text = replace_once(text, OLD_RESET, NEW_RESET, "reset history")
    text = replace_once(text, OLD_FINAL, NEW_FINAL, "final census")
    text = replace_once(text, "    args = ap.parse_args()\n",
                        "    args = ap.parse_args()\n    args.output_receipt.unlink(missing_ok=True)\n", "stale local receipt")
    text = replace_once(text, OLD_ENTRY, NEW_ENTRY, "failure progress")
    ast.parse(text)
    return text



def api(path: str) -> dict:
    if not path.startswith("/") or ".." in path or "://" in path:
        raise RuntimeError("unsafe audit API path")
    req = urllib.request.Request(
        "https://api.github.com/repos/P00NSMASHER/portfolio-brain" + path,
        headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                 "Accept": "application/vnd.github+json", "User-Agent": "step23-read-only-audit"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def apply_overlay(root: Path, observer_root: Path) -> None:
    observed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if observed != TARGET:
        raise RuntimeError("audit checkout is not the pinned main SHA")
    collector = root / "acceptance/step23_live_collect.py"
    fixture = root / "tests/test_step23_live_collect.py"
    if git_blob(collector.read_bytes()) != EXPECTED_COLLECTOR or git_blob(fixture.read_bytes()) != EXPECTED_TEST:
        raise RuntimeError("audit source drift; no overlay applied")
    changed = transform_collector(collector.read_text())
    old = '"event": "schedule", "status": "completed", "conclusion": conclusion,'
    new = '"event": "schedule", "head_branch": "main", "status": "completed", "conclusion": conclusion,'
    fixed_fixture = replace_once(fixture.read_text(), old, new, "provider fixture branch")
    # Changes exist only in this disposable read-only runner checkout.
    for rel in ("acceptance/soak_observation.py", "tests/test_soak_observation.py"):
        if (root / rel).exists():
            raise RuntimeError("audit overlay destination unexpectedly exists")
    collector.write_text(changed)
    fixture.write_text(fixed_fixture)
    for rel in ("acceptance/soak_observation.py", "tests/test_soak_observation.py"):
        shutil.copyfile(observer_root / rel, root / rel)
    for pattern in ("test_soak_observation.py", "test_step23_live_collect.py"):
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"],
                       cwd=root, check=True, timeout=60)


def run_audit(root: Path, observer_root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    deadline = datetime.fromisoformat(END.replace("Z", "+00:00"))
    if datetime.now(timezone.utc) >= deadline:
        raise RuntimeError("STEP23_SOAK_WINDOW_EXPIRED")
    # Require independent exact-head review of this supplemental observer too.
    candidate = os.environ["AUDIT_CANDIDATE_SHA"]
    if len(candidate) != 40 or any(c not in "0123456789abcdef" for c in candidate):
        raise RuntimeError("invalid audit candidate SHA")
    verified = False
    for _ in range(40):
        if datetime.now(timezone.utc) >= deadline:
            raise RuntimeError("STEP23_SOAK_WINDOW_EXPIRED")
        doc = api(f"/commits/{candidate}/check-runs?per_page=100")
        if doc.get("total_count", 0) >= 100:
            raise RuntimeError("audit verification listing incomplete")
        latest = []
        for name, app in (("validate", 15368), ("portfolio-phase1-gate", 5121826)):
            rows = [r for r in doc.get("check_runs", [])
                    if r.get("name") == name and r.get("app", {}).get("id") == app
                    and r.get("head_sha") == candidate]
            latest.append(max(rows, key=lambda r: r["id"]) if rows else None)
        if any(r and r.get("status") == "completed" and r.get("conclusion") != "success" for r in latest):
            raise RuntimeError("AUDIT_EXACT_HEAD_VERIFICATION_FAILED")
        if all(r and r.get("status") == "completed" and r.get("conclusion") == "success" for r in latest):
            verified = True
            break
        time.sleep(15)
    if not verified:
        raise RuntimeError("AUDIT_EXACT_HEAD_VERIFICATION_TIMEOUT")
    if api("/branches/main")["commit"]["sha"] != TARGET:
        raise RuntimeError("STEP23_MAIN_MOVED")
    apply_overlay(root, observer_root)
    cfg = dict(exact_main_sha=TARGET, soak_start=START, required_workflows=WORKFLOWS,
               required_handler_types=["REPAIR", "TEST", "VERIFICATION"],
               required_successes_per_workflow=3, max_soak_duration_seconds=3600,
               poll_seconds=60, max_resets=5)
    config = output / "config.json"
    meta, receipt = output / "progress.json", output / "receipt.json"
    config.write_text(json.dumps(cfg, indent=2) + "\n")
    (output / "audit_scope.json").write_text(json.dumps(dict(
        target_main_sha=TARGET, audit_candidate_sha=candidate, window_start=START, deadline=END,
        observer_started_at=datetime.now(timezone.utc).isoformat(),
        observation_scope="READ_ONLY_BRANCH_OVERLAY", repository_mutated=False,
        original_collector_blob=EXPECTED_COLLECTOR, acceptance_thresholds_changed=False,
    ), indent=2) + "\n")
    while datetime.now(timezone.utc) < deadline:
        if api("/branches/main")["commit"]["sha"] != TARGET:
            raise RuntimeError("STEP23_MAIN_MOVED")
        seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
        cmd = [sys.executable, "-m", "acceptance.step23_live_collect", "--config", str(config),
               "--output-meta", str(meta), "--output-receipt", str(receipt),
               "--timeout-seconds", "180", "--once"]
        subprocess.run(cmd, cwd=root, check=True, timeout=max(1, min(210, seconds)))
        progress = json.loads(meta.read_text())
        print(json.dumps({"audit_status": progress.get("status"),
                          "counts": progress.get("counts", progress.get("successful_run_counts"))}), flush=True)
        if receipt.exists():
            if progress.get("status") != "PASS":
                raise RuntimeError("audit receipt and progress disagree")
            print("STRICT_BRANCH_AUDIT_PASS", flush=True)
            return
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            time.sleep(min(90, remaining))
    raise RuntimeError("STEP23_SOAK_WINDOW_EXPIRED")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--observer-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        run_audit(args.root.resolve(), args.observer_root.resolve(), args.output.resolve())
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        code = str(exc).split(" ", 1)[0]
        if code not in {"STEP23_SOAK_WINDOW_EXPIRED", "STEP23_MAIN_MOVED",
                        "AUDIT_EXACT_HEAD_VERIFICATION_FAILED", "AUDIT_EXACT_HEAD_VERIFICATION_TIMEOUT"}:
            code = "AUDIT_FAILED_CLOSED"
        (args.output / "audit_failure.json").write_text(json.dumps(dict(
            status=code, target_main_sha=TARGET, acceptance_complete=False,
            observed_at=datetime.now(timezone.utc).isoformat(),
        ), indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
