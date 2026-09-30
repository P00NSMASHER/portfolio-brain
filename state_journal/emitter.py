"""Write a run-scoped immutable event only for successfully published domains.

This is migration instrumentation, not a replacement for existing persistence.
The enclosing workflow supplies actual upload step outcomes. No output file or
PASS-shaped receipt is by itself sufficient to say a state was published.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from state_journal.contracts import DOMAINS, PRODUCERS, canonical, fields, require, strict_load
from state_journal.events import make_change, make_event


def domain_paths(root: Path, producer: str, domain: str) -> tuple[Path, Path, Path | None]:
    _, before, after, seed = DOMAINS[domain]
    if producer in {"model-value-proof", "continuous-learning-bootstrap", "verified-feedback-bootstrap"} and domain == "hunter":
        after = "value_proof/out/hunter_state.json"
    if producer == "operator-console" and domain == "scheduler":
        before = "dashboard/live/scheduler_state.json"
    return root / before, root / after, root / seed if seed else None


def capture(root: Path, producer: str, run_id: str, source_sha: str, published: dict,
            *, run_attempt: int | None = None) -> dict | None:
    require(producer in PRODUCERS, "Unenrolled producer")
    require(isinstance(published, dict) and set(published) == PRODUCERS[producer][1], "Publication outcomes must cover the producer's exact domains")
    require(all(type(v) is bool for v in published.values()), "Upload outcomes must be explicit booleans")
    changes = []
    for domain in sorted(published):
        if not published[domain]:
            continue
        before_path, after_path, seed_path = domain_paths(root, producer, domain)
        require(after_path.is_file(), f"Published {domain} output is missing")
        if not before_path.is_file():
            # Only use the SAME checked-in seed used by this production module;
            # do not invent runtime baselines or recover from malformed input.
            require(seed_path is not None and seed_path.is_file(), f"{domain} has no captured predecessor")
            before_path = seed_path
        before = strict_load(before_path.read_bytes())
        after = strict_load(after_path.read_bytes())
        proofs = {}
        if domain == "runtime":
            receipt = after_path.parent / "cycle_receipt.json"
            require(receipt.is_file(), "Runtime companion receipt is missing")
            proofs = {"cycle_receipt": strict_load(receipt.read_bytes())}
        # Retain no-op publications too: they are observations, not success credit.
        changes.append(make_change(domain, before, after, proofs=proofs))
    return make_event(producer, run_id, source_sha, changes, run_attempt=run_attempt) if changes else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", choices=sorted(PRODUCERS), required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("state_journal/out/event"))
    args = parser.parse_args()
    require(os.environ.get("GITHUB_REF") == "refs/heads/main", "Production event capture requires main, never a PR checkout")
    published = strict_load(os.environ.get("JOURNAL_PUBLISHED_DOMAINS", "{}").encode())
    attempt_raw = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    require(attempt_raw.isdigit() and int(attempt_raw) > 0, "GITHUB_RUN_ATTEMPT required for production event capture")
    event = capture(
        args.root, args.producer, os.environ.get("GITHUB_RUN_ID", ""),
        os.environ.get("GITHUB_SHA", ""), published, run_attempt=int(attempt_raw)
    )
    if event is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        target = args.output_dir / "event.json"
        payload = canonical(event) + b"\n"
        if target.exists():
            require(target.read_bytes() == payload, "Local immutable event overwrite refused")
        else:
            with target.open("xb") as handle:
                handle.write(payload)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"emitted={'true' if event is not None else 'false'}\n")
    print(json.dumps({"emitted": event is not None, "event_id": event["event_id"] if event else None, "production_backend_changed": False}))


if __name__ == "__main__": main()
