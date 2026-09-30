#!/usr/bin/env python3
"""Read-only live proof for pinned upstream Portfolio Brain integrations.

Pin identity and live integration are intentionally separate proofs:
- pin identity proves the exact pinned revision/blob set still exists;
- live integration proves the current upstream interface is reachable,
  relevant blobs have not drifted, and the local adapter conformance smoke passes.

This module never writes upstream, grants authority, or executes upstream code.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
PIN_PATHS = {
    "truth_engine": ROOT / "truth" / "AI_BUSINESS_OS_TRUTH_ENGINE_PIN.json",
    "value_memory": ROOT / "memory" / "AI_BUSINESS_OS_VALUE_MEMORY_PIN.json",
    "hunter_bridge": ROOT / "hunting" / "AI_BUSINESS_OS_HUNTER_PIN.json",
    "learning_engine": ROOT / "learning" / "AI_BUSINESS_OS_LEARNING_ENGINE_PIN.json",
}


class UpstreamProbeError(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise UpstreamProbeError(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_pins() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, path in PIN_PATHS.items():
        pin = json.loads(path.read_text(encoding="utf-8"))
        require(pin.get("schema_version") == "1.0.0", f"{name} pin schema drifted")
        require(isinstance(pin.get("integration_id"), str) and pin["integration_id"], f"{name} integration id missing")
        require(isinstance(pin.get("source_repository"), str) and "/" in pin["source_repository"], f"{name} source repository invalid")
        require(SHA40.fullmatch(str(pin.get("source_revision", ""))) is not None, f"{name} source revision invalid")
        _components(name, pin)
        out[name] = pin
    return out


def _components(name: str, pin: dict[str, Any]) -> dict[str, str]:
    if "components" in pin:
        raw = pin["components"]
        require(isinstance(raw, dict) and raw, f"{name} components missing")
        out = {}
        for component_name, component in raw.items():
            require(isinstance(component, dict), f"{name}.{component_name} component invalid")
            path = component.get("path")
            blob = component.get("blob_sha")
            require(isinstance(path, str) and path, f"{name}.{component_name} path invalid")
            require(SHA40.fullmatch(str(blob or "")) is not None, f"{name}.{component_name} blob invalid")
            out[path] = blob
        return out
    required = {
        pin.get("source_path"): pin.get("source_blob_sha"),
        pin.get("source_test_path"): pin.get("source_test_blob_sha"),
    }
    out = {}
    for path, blob in required.items():
        require(isinstance(path, str) and path, f"{name} source path invalid")
        require(SHA40.fullmatch(str(blob or "")) is not None, f"{name} source blob invalid")
        out[path] = blob
    return out


def _api_get(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "portfolio-brain-upstream-read-only-probe/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            require(response.status == 200, f"GitHub read returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise UpstreamProbeError(f"GitHub read failed: {type(exc).__name__}") from exc
    require(isinstance(payload, dict), "GitHub read returned non-object")
    return payload


def _repo_url(repository: str, suffix: str = "") -> str:
    owner, name = repository.split("/", 1)
    base = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
    return base + suffix


def _tree_for_revision(repository: str, revision: str, get_json: Callable[[str], dict[str, Any]]) -> dict[str, str]:
    commit = get_json(_repo_url(repository, f"/git/commits/{revision}"))
    tree_sha = ((commit.get("tree") or {}).get("sha"))
    require(SHA40.fullmatch(str(tree_sha or "")) is not None, "upstream commit tree sha missing")
    tree = get_json(_repo_url(repository, f"/git/trees/{tree_sha}?recursive=1"))
    require(tree.get("truncated") is False, "upstream recursive tree was truncated")
    entries = tree.get("tree")
    require(isinstance(entries, list), "upstream tree entries missing")
    out: dict[str, str] = {}
    for item in entries:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path = item.get("path")
        sha = item.get("sha")
        if isinstance(path, str) and SHA40.fullmatch(str(sha or "")):
            out[path] = sha
    return out


def collect_live_state(
    pins: dict[str, dict[str, Any]],
    *,
    get_json: Callable[[str], dict[str, Any]] = _api_get,
) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, str], dict[str, dict[str, str]]]:
    pinned_trees: dict[tuple[str, str], dict[str, str]] = {}
    current_heads: dict[str, str] = {}
    current_trees: dict[str, dict[str, str]] = {}
    repositories = sorted({pin["source_repository"] for pin in pins.values()})
    for repository in repositories:
        revisions = sorted({pin["source_revision"] for pin in pins.values() if pin["source_repository"] == repository})
        for revision in revisions:
            pinned_trees[(repository, revision)] = _tree_for_revision(repository, revision, get_json)
        metadata = get_json(_repo_url(repository))
        default_branch = metadata.get("default_branch")
        require(isinstance(default_branch, str) and default_branch, "upstream default branch missing")
        ref = get_json(_repo_url(repository, f"/git/ref/heads/{urllib.parse.quote(default_branch, safe='')}"))
        current = ((ref.get("object") or {}).get("sha"))
        require(SHA40.fullmatch(str(current or "")) is not None, "upstream current head sha missing")
        current_heads[repository] = current
        current_trees[repository] = _tree_for_revision(repository, current, get_json)
    return pinned_trees, current_heads, current_trees


def _default_adapter_validators() -> dict[str, Callable[[], Any]]:
    from truth.validate_truth_integration import validate_truth_integration
    from memory.validate_value_memory import validate_shared_value_memory
    from hunting.validate_hunter import validate_hunter
    from learning.validate_learning import validate_learning

    return {
        "truth_engine": validate_truth_integration,
        "value_memory": validate_shared_value_memory,
        "hunter_bridge": validate_hunter,
        "learning_engine": validate_learning,
    }


def run_adapter_smokes(
    validators: dict[str, Callable[[], Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    validators = validators or _default_adapter_validators()
    results: dict[str, dict[str, Any]] = {}
    for name in sorted(PIN_PATHS):
        fn = validators.get(name)
        if fn is None:
            results[name] = {"status": "BLOCKED", "reason": "VALIDATOR_MISSING"}
            continue
        try:
            detail = fn()
            results[name] = {"status": "PASS", "detail": detail}
        except Exception as exc:  # proof must record fail-closed adapter errors
            results[name] = {
                "status": "BLOCKED",
                "reason": type(exc).__name__,
                "detail": str(exc)[:400],
            }
    return results


def evaluate_proofs(
    pins: dict[str, dict[str, Any]],
    pinned_trees: dict[tuple[str, str], dict[str, str]],
    current_heads: dict[str, str],
    current_trees: dict[str, dict[str, str]],
    adapter_smokes: dict[str, dict[str, Any]],
    *,
    observed_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    at = observed_at or _now()
    pin_rows = []
    live_rows = []
    for name in sorted(pins):
        pin = pins[name]
        repository = pin["source_repository"]
        revision = pin["source_revision"]
        components = _components(name, pin)
        pinned_tree = pinned_trees.get((repository, revision), {})
        pin_checks = [
            {
                "path": path,
                "expected_blob_sha": expected,
                "observed_blob_sha": pinned_tree.get(path),
                "status": "PASS" if pinned_tree.get(path) == expected else "MISMATCH",
            }
            for path, expected in sorted(components.items())
        ]
        pin_status = "PASS" if pin_checks and all(row["status"] == "PASS" for row in pin_checks) else "BLOCKED"
        pin_rows.append(
            {
                "integration": name,
                "integration_id": pin["integration_id"],
                "source_repository": repository,
                "source_revision": revision,
                "pin_schema_version": pin["schema_version"],
                "component_checks": pin_checks,
                "status": pin_status,
            }
        )

        current_head = current_heads.get(repository)
        current_tree = current_trees.get(repository, {})
        current_checks = [
            {
                "path": path,
                "pinned_blob_sha": expected,
                "current_blob_sha": current_tree.get(path),
                "unchanged": current_tree.get(path) == expected,
            }
            for path, expected in sorted(components.items())
        ]
        component_drift = [row["path"] for row in current_checks if not row["unchanged"]]
        smoke = adapter_smokes.get(name, {"status": "BLOCKED", "reason": "SMOKE_MISSING"})
        head_drift = current_head != revision
        live_status = "PASS" if not component_drift and smoke.get("status") == "PASS" else "BLOCKED"
        live_rows.append(
            {
                "integration": name,
                "integration_id": pin["integration_id"],
                "source_repository": repository,
                "pinned_revision": revision,
                "current_revision": current_head,
                "head_drift_detected": head_drift,
                "interface_drift_detected": bool(component_drift),
                "drift_classification": (
                    "HEAD_ADVANCED_COMPONENTS_UNCHANGED"
                    if head_drift and not component_drift
                    else "NO_DRIFT"
                    if not head_drift and not component_drift
                    else "COMPONENT_DRIFT_REQUIRES_RECONFORMANCE"
                ),
                "current_component_checks": current_checks,
                "adapter_smoke": smoke,
                "status": live_status,
            }
        )

    pin_status = "PASS" if pin_rows and all(row["status"] == "PASS" for row in pin_rows) else "BLOCKED"
    live_status = "PASS" if live_rows and all(row["status"] == "PASS" for row in live_rows) else "BLOCKED"
    pin_proof = {
        "schema_version": "1.0.0",
        "proof_type": "UPSTREAM_PIN_IDENTITY",
        "observed_at": at,
        "portfolio_head_sha": os.environ.get("GITHUB_SHA"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "status": pin_status,
        "integrations": pin_rows,
        "authority_granted": False,
        "upstream_mutations": 0,
    }
    live_proof = {
        "schema_version": "1.0.0",
        "proof_type": "UPSTREAM_LIVE_READ_ONLY_INTEGRATION",
        "observed_at": at,
        "portfolio_head_sha": os.environ.get("GITHUB_SHA"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "status": live_status,
        "integrations": live_rows,
        "authority_granted": False,
        "upstream_mutations": 0,
        "note": "Pin/blob identity and live adapter usability are separate acceptance facts.",
    }
    return pin_proof, live_proof


def build_proofs(
    *,
    get_json: Callable[[str], dict[str, Any]] = _api_get,
    validators: dict[str, Callable[[], Any]] | None = None,
    observed_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pins = load_pins()
    pinned_trees, current_heads, current_trees = collect_live_state(pins, get_json=get_json)
    smokes = run_adapter_smokes(validators)
    return evaluate_proofs(
        pins,
        pinned_trees,
        current_heads,
        current_trees,
        smokes,
        observed_at=observed_at,
    )


def _write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only upstream pin and live integration proofs")
    parser.add_argument("--pin-output", type=Path, required=True)
    parser.add_argument("--live-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        pin_proof, live_proof = build_proofs()
    except Exception as exc:
        at = _now()
        blocked = {
            "schema_version": "1.0.0",
            "observed_at": at,
            "portfolio_head_sha": os.environ.get("GITHUB_SHA"),
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "status": "BLOCKED",
            "reason": type(exc).__name__,
            "detail": str(exc)[:400],
            "authority_granted": False,
            "upstream_mutations": 0,
        }
        pin_proof = {"proof_type": "UPSTREAM_PIN_IDENTITY", **blocked}
        live_proof = {"proof_type": "UPSTREAM_LIVE_READ_ONLY_INTEGRATION", **blocked}
    _write(args.pin_output, pin_proof)
    _write(args.live_output, live_proof)
    print(json.dumps({"pin_identity": pin_proof["status"], "live_integration": live_proof["status"]}, sort_keys=True))
    if pin_proof["status"] != "PASS" or live_proof["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
