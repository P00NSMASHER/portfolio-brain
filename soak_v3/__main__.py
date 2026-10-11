"""Read-only command-line entry point for separately acquired soak evidence.

This is NOT the trusted GitHub collector and can never output a terminal PASS.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from soak_v3.audit import (
    EvidenceError, _strict_v5_receipt_json, evaluate_window,
    evaluate_v5_window, verify_artifact, verify_v5_artifact,
    verify_sqlite, verify_v5_sqlite,
)

V5_MANIFEST_MAX_BYTES = 8_000_000


def _load_v5_manifest(path):
    """Bound and strictly decode the original V5 evidence manifest once.

    This validates local JSON syntax/size only; the evidence collector must
    separately authenticate original GitHub/Cloudflare provider metadata.
    """
    before = path.stat()
    if not 0 < before.st_size <= V5_MANIFEST_MAX_BYTES:
        raise EvidenceError("V5_MANIFEST_SIZE_INVALID")
    with path.open("rb") as source:
        original = source.read(V5_MANIFEST_MAX_BYTES + 1)
    if len(original) != before.st_size:
        raise EvidenceError("V5_MANIFEST_SIZE_CHANGED_DURING_READ")
    return _strict_v5_receipt_json(original)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Non-authoritative soak evidence inspector")
    parser.add_argument("mode", choices=["artifact", "artifact-v5", "state", "state-v5", "window", "window-v5"])
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = (_load_v5_manifest(args.manifest)
                    if args.mode.endswith("-v5")
                    else json.loads(args.manifest.read_text()))
        if type(manifest) is not dict:
            raise EvidenceError("MANIFEST_NOT_OBJECT")
        if args.mode in {"artifact", "artifact-v5"}:
            verifier = verify_v5_artifact if args.mode == "artifact-v5" else verify_artifact
            result = verifier(manifest["path"], manifest["expected_digest"],
                                     run_id=manifest["run_id"], source_sha=manifest["source_sha"],
                                     state_parent=manifest["state_parent"], state_commit=manifest["state_commit"])
        elif args.mode in {"state", "state-v5"}:
            verifier = verify_v5_sqlite if args.mode == "state-v5" else verify_sqlite
            result = verifier(manifest["path"], expected_sequence=manifest["state_sequence"],
                              expected_chain=manifest["canonical_hash"], expected_source=manifest["source_sha"])
        else:
            evaluate = evaluate_v5_window if args.mode == "window-v5" else evaluate_window
            extras = {"inventory": manifest["inventory"]} if args.mode == "window-v5" else {}
            result = asdict(evaluate(manifest["runs"], source_sha=manifest["source_sha"],
                             current_main=manifest["current_main"],
                             first_state_parent=manifest["first_state_parent"],
                             started_at=manifest["started_at"], deadline_at=manifest["deadline_at"],
                             now=manifest["now"], **extras))
        print(json.dumps({"scope": "NONAUTHORITATIVE_EVIDENCE_INSPECTION", "result": result}, sort_keys=True))
        return 0
    except (EvidenceError, KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"scope": "NONAUTHORITATIVE_EVIDENCE_INSPECTION", "status": "BLOCKED",
                          "reason": str(exc)[:200]}, sort_keys=True))
        return 1

if __name__ == "__main__":
    sys.exit(main())
