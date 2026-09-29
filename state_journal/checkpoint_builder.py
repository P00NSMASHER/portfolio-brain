"""Build a source-bound migration checkpoint from validated legacy state."""
from __future__ import annotations
import argparse
import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from state_journal.contracts import canonical, digest, require
from state_journal.legacy import restore_all
from state_journal.reducer import checkpoint, validate_checkpoint

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path, proof: Path, work: Path) -> dict:
    source_sha = os.environ.get("CHECKPOINT_SOURCE_SHA", "")
    require(len(source_sha) == 40, "Exact checkpoint source SHA required")
    states, refs = restore_all(ROOT, work)
    doc = checkpoint(states, refs)
    validate_checkpoint(doc)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical(doc) + b"\n"
    output.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0) if output.suffix == ".gz" else payload)
    receipt = {
        "status": "PASS",
        "mode": "SOURCE_BOUND_LEGACY_CHECKPOINT",
        "source_sha": source_sha,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checkpoint_hash": doc["checkpoint_hash"],
        "domain_hashes": {k: digest(v) for k, v in sorted(states.items())},
    }
    proof.parent.mkdir(parents=True, exist_ok=True)
    proof.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=Path("state_journal/out/checkpoint-work"))
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.proof, args.work), sort_keys=True))


if __name__ == "__main__":
    main()
