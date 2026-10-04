"""Read-only recurring progress; no authority or completion from green jobs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from acceptance.step23_live_collect import GH, iso_now, main as collect_soak
from verification.step24_security_review import static_review, combine

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "acceptance/out"


def observe() -> None:
    gh = GH(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    current = gh.get("/branches/main")["commit"]["sha"]
    if current != os.environ["GITHUB_SHA"]:
        raise RuntimeError("observer checkout is not exact current main")
    commit = gh.get("/commits/" + current)
    policy = json.loads((ROOT / "acceptance/FINAL_ACCEPTANCE_POLICY.json").read_text())["step23"]
    config = {
        "exact_main_sha": current,
        "soak_start": commit["commit"]["committer"]["date"],
        "required_workflows": policy["required_workflows"],
        "required_handler_types": policy["required_handler_types"],
        "required_successes_per_workflow": policy["min_successful_scheduled_cycles_per_workflow"],
        "max_soak_duration_seconds": policy["max_soak_duration_seconds"],
        "poll_seconds": 1,
        "max_resets": 5,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "step23_config.json").write_text(json.dumps(config, indent=2) + "\n")
    # Static review is preparation only. Fresh live evidence and an independent
    # reviewer remain required; do not manufacture signoff from this observer.
    security = combine(static_review(ROOT), None)
    (OUT / "step24_preparation.json").write_text(json.dumps(security, indent=2) + "\n")
    argv = sys.argv
    try:
        sys.argv = [argv[0], "--config", str(OUT / "step23_config.json"),
                    "--output-meta", str(OUT / "step23_progress.json"),
                    "--output-receipt", str(OUT / "step23_receipt.json"),
                    "--timeout-seconds", "180", "--once"]
        collect_soak()
    except Exception as exc:
        (OUT / "step23_progress.json").write_text(json.dumps({
            "schema_version": "1.0.0", "status": "BLOCKED", "reason": str(exc),
            "exact_main_sha": current, "acceptance_complete": False,
            "generated_at": iso_now(),
        }, indent=2) + "\n")
        raise
    finally:
        sys.argv = argv


if __name__ == "__main__":
    observe()
