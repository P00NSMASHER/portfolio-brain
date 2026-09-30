"""Prove reducer projection matches every authoritative legacy state domain."""
from __future__ import annotations
import json
from pathlib import Path
from state_journal.contracts import DOMAINS, digest, require
from state_journal.legacy import restore_all
from hunting.proposal_state import normalize_state as normalize_proposal_state

ROOT = Path(__file__).resolve().parents[1]


def verify(projected: dict, work: Path) -> dict:
    require(isinstance(projected, dict) and set(projected) == set(DOMAINS), "Projection domain coverage mismatch")
    legacy, refs = restore_all(ROOT, work)
    rows = {}
    for domain in sorted(DOMAINS):
        projected_state = projected[domain]
        legacy_state = legacy[domain]
        if domain == "proposals":
            # Match the production validator's migration of pre-origins artifacts.
            projected_state = normalize_proposal_state(projected_state)
            legacy_state = normalize_proposal_state(legacy_state)
        projected_hash = digest(projected_state)
        legacy_hash = digest(legacy_state)
        require(projected_hash == legacy_hash, f"LEGACY_PARITY_MISMATCH:{domain}")
        rows[domain] = {
            "projection_hash": projected_hash,
            "legacy_hash": legacy_hash,
            "legacy_source": refs[domain],
        }
    return {"status": "PASS", "domains": rows}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=Path("state_journal/out/parity-work"))
    args = parser.parse_args()
    payload = json.loads(args.projection.read_text())
    if payload.get("states"):
        payload = payload["states"]
    receipt = verify(payload, args.work)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
