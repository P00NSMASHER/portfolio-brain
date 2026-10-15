"""Offline, restart-safe continuation report for existing autonomous owners.

Previous history and original GitHub provider observations come from explicit
private input files. No network calls, source execution, provider mutations,
new scheduled tasks, payments, or secrets are performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain.core import BrainError, require
from brain.repair_followthrough import follow_through
from brain.render import write_report


def _safe_json(path):
    require(isinstance(path, Path) and path.is_file() and not path.is_symlink(),
            "REPAIR_CONTINUATION_SOURCE_FILE_UNSAFE")
    info = path.stat()
    require(info.st_nlink == 1 and 0 < info.st_size <= 1_000_000,
            "REPAIR_CONTINUATION_INPUT_OVERSIZED_OR_ALIAS")
    def unique(pairs):
        result = {}
        for name, value in pairs:
            require(name not in result, "REPAIR_CONTINUATION_DUPLICATE_JSON_KEY")
            result[name] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BrainError("REPAIR_CONTINUATION_INVALID_JSON") from exc


def main(argv=None):
    p = argparse.ArgumentParser(description="Offline owner repair follow-through")
    p.add_argument("--current", required=True, type=Path)
    p.add_argument("--history", type=Path)
    p.add_argument("--provider", type=Path)
    p.add_argument("--cycle", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    require(args.output != args.current and args.output != args.history
            and args.output != args.provider
            and not args.output.is_symlink(),
            "REPAIR_CONTINUATION_OUTPUT_OVERLAPS_INPUT")
    old = _safe_json(args.history) if args.history else None
    # An earlier private report.json can be reused directly on the next run;
    # no manual extraction, new persistent provider, or extra schedule needed.
    if type(old) is dict and "next_history" in old:
        old = old["next_history"]
    receipt = _safe_json(args.provider) if args.provider else None
    if type(receipt) is dict:
        require(receipt.get("scope") == "ORIGINAL_GITHUB_READ_ONLY_REPAIR_PROOFS"
                and receipt.get("automatic_merge_or_deployment_authority") is False
                and receipt.get("customer_or_external_action_authority") is False
                and type(receipt.get("proofs")) is list
                and receipt.get("original_api_response_not_signed") is True,
                "REPAIR_CONTINUATION_PROVIDER_ENVELOPE_UNTRUSTED")
        receipt = receipt["proofs"]
    result = follow_through(
        _safe_json(args.current), cycle=args.cycle,
        history=old,
        provider_receipts=receipt,
    )
    write_report(result, args.output)
    print(json.dumps({
        "status": result["status"],
        "selected": result["selected_count"],
        "unfinished": result["unfinished_count"],
        "technical_main_only": result["technical_main_verified_count"],
        "release_or_contact_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
