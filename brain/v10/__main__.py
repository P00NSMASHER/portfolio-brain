"""Execute a source-pinned v10 patch plan in isolation; optionally publish DRAFT.

Usage (on an authorized checkout, with Docker available):
  python -m brain.v10 --spec /tmp/fix.json --workspace . --receipt /tmp/fix-receipt.json
  python -m brain.v10 --spec /tmp/fix.json --workspace . --receipt /tmp/fix-receipt.json --publish --intent /tmp/fix-intent.json

Publication requires PORTFOLIO_RUNTIME_TOKEN scoped to this one repository.
The command never merges, deploys, activates observation or approves itself.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess

from brain.v10 import engineering_factory as factory

def _read_spec(path):
    candidate = Path(path)
    factory.require(candidate.is_file() and not candidate.is_symlink()
                    and candidate.stat().st_size <= 128 * 1024,
                    "FACTORY_MANIFEST_UNSAFE")
    raw = candidate.read_bytes()
    obj = factory._strict_json(raw)
    factory.validate_request(obj)
    return obj

def _checkout_sources(root, spec):
    workspace = Path(root)
    factory.require(not workspace.is_symlink(), "FACTORY_WORKSPACE_INVALID")
    root = workspace.resolve(strict=True)
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=15, check=False)
    factory.require(result.returncode == 0 and
                    result.stdout.strip() == spec["base_sha"],
                    "FACTORY_CHECKOUT_WRONG_SOURCE")
    sources = {}
    for change in spec["changes"]:
        target = root / change["path"]
        factory.require(target.is_file() and not target.is_symlink()
                        and target.resolve(strict=True).is_relative_to(root)
                        and all(not ancestor.is_symlink() for ancestor in target.parents
                                if ancestor != root and root in ancestor.parents),
                        "FACTORY_WORKTREE_SOURCE_CHANGED")
        sources[change["path"]] = target.read_bytes()
    return sources

def _write_receipt(path, receipt):
    output = Path(path)
    factory.require(output.parent.is_dir() and not output.is_symlink(),
                    "FACTORY_RECEIPT_PATH_UNSAFE")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        raise

def run(spec, workspace, *, publish=False, intent=None, receipt=None,
        token="", test_runner=None):
    spec = _read_spec(spec)
    originals = _checkout_sources(workspace, spec)
    candidate = factory.prepare(spec, originals)
    tests = factory.run_isolated_tests(
        workspace, candidate, **({"runner":test_runner} if test_runner else {}))
    output = {
        "schema_version": 1,
        "status": "ISOLATED_TESTS_PASSED_NOT_INDEPENDENT_CI",
        "source_sha": spec["base_sha"],
        "operation_id": candidate["operation_id"],
        "changed_paths": [row["path"] for row in candidate["changes"]],
        "original_failed_run_id": spec["failure_run_id"],
        "test_output_sha256": tests["output_sha256"],
        "independent_ci_verified": False,
        "merged": False, "deployed": False, "production_accepted": False,
    }
    if publish:
        factory.require(type(token) is str and 20 <= len(token) <= 4096,
                        "FACTORY_APP_TOKEN_MISSING")
        factory.require(intent is not None, "FACTORY_INTENT_PATH_REQUIRED")
        api = factory.GitHubTransport(token)
        outcome = factory.create_draft(api, spec, candidate, tests,
                                       intent_path=intent)
        output.update(outcome)
    if receipt is not None:
        _write_receipt(receipt, output)
    return output

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--intent")
    args = parser.parse_args(argv)
    try:
        result = run(args.spec, args.workspace, publish=args.publish,
                     intent=args.intent, receipt=args.receipt,
                     token=os.environ.get("PORTFOLIO_RUNTIME_TOKEN", ""))
        print(json.dumps({"status": result["status"],
                          "operation_id": result["operation_id"],
                          "production_accepted": False}, sort_keys=True))
        return 0
    except (factory.FactoryError, ValueError, OSError, subprocess.SubprocessError) as exc:
        code = str(exc) if isinstance(exc, factory.FactoryError) else "V10_FACTORY_FAILED"
        print(json.dumps({"status": "BLOCKED", "code": code,
                          "production_accepted": False}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
