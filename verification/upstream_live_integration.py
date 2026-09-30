#!/usr/bin/env python3
"""Read-only Step 20 proof for pinned upstream integrations.

Pin/blob identity and live interface usability are deliberately reported as
separate proofs. The probe never mutates the upstream repository and uses no
write-scoped credential.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGETS_PATH = ROOT / "verification" / "UPSTREAM_LIVE_TARGETS.json"
SUPPORTED_SCHEMA_VERSION = "1.0.0"


class UpstreamIntegrationError(ValueError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise UpstreamIntegrationError(message)


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(data, dict), f"{path} must contain an object")
    return data


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class GitHubReadOnlyClient:
    """Minimal public GitHub REST reader with no mutation methods."""

    def __init__(self) -> None:
        self.network_reads = 0
        self._branch_cache: dict[tuple[str, str], str] = {}
        self._file_cache: dict[tuple[str, str, str], dict[str, str]] = {}

    def _json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "portfolio-brain-step20-readonly-probe",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.network_reads += 1
        _require(isinstance(payload, dict), "GitHub response must be an object")
        return payload

    def branch_head(self, repository: str, branch: str) -> str:
        key = (repository, branch)
        if key not in self._branch_cache:
            owner_repo = urllib.parse.quote(repository, safe="/")
            branch_q = urllib.parse.quote(branch, safe="")
            payload = self._json(f"https://api.github.com/repos/{owner_repo}/branches/{branch_q}")
            sha = payload.get("commit", {}).get("sha")
            _require(isinstance(sha, str) and len(sha) == 40, "upstream branch head SHA unavailable")
            self._branch_cache[key] = sha
        return self._branch_cache[key]

    def file(self, repository: str, path: str, ref: str) -> dict[str, str]:
        key = (repository, path, ref)
        if key not in self._file_cache:
            owner_repo = urllib.parse.quote(repository, safe="/")
            path_q = urllib.parse.quote(path, safe="/")
            ref_q = urllib.parse.quote(ref, safe="")
            payload = self._json(
                f"https://api.github.com/repos/{owner_repo}/contents/{path_q}?ref={ref_q}"
            )
            sha = payload.get("sha")
            encoded = payload.get("content")
            _require(isinstance(sha, str) and len(sha) == 40, f"{path}: blob SHA unavailable")
            _require(isinstance(encoded, str), f"{path}: source content unavailable")
            text = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
            self._file_cache[key] = {"sha": sha, "text": text}
        return dict(self._file_cache[key])


def _pin_files(pin: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if "source_path" in pin:
        rows.append(
            {
                "key": "source",
                "path": str(pin["source_path"]),
                "blob_sha": str(pin["source_blob_sha"]),
            }
        )
        if pin.get("source_test_path") and pin.get("source_test_blob_sha"):
            rows.append(
                {
                    "key": "source_test",
                    "path": str(pin["source_test_path"]),
                    "blob_sha": str(pin["source_test_blob_sha"]),
                }
            )
    components = pin.get("components")
    if components is not None:
        _require(isinstance(components, dict) and components, "pin components must be a non-empty object")
        for key in sorted(components):
            row = components[key]
            _require(isinstance(row, dict), f"pin component {key} must be an object")
            rows.append(
                {
                    "key": key,
                    "path": str(row["path"]),
                    "blob_sha": str(row["blob_sha"]),
                }
            )
    _require(rows, "pin exposes no source files")
    for row in rows:
        _require(len(row["blob_sha"]) == 40, f"{row['key']}: invalid pinned blob SHA")
    return rows


def _primary_file(pin_files: list[dict[str, str]], selector: dict[str, Any]) -> dict[str, str]:
    kind = selector.get("kind")
    wanted = "source" if kind == "source" else selector.get("key")
    _require(isinstance(wanted, str) and wanted, "primary selector is invalid")
    for row in pin_files:
        if row["key"] == wanted:
            return row
    raise UpstreamIntegrationError(f"primary pinned component {wanted} not found")


def _interface_inventory(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    classes: dict[str, set[str]] = {}
    functions: set[str] = set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            methods = {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            classes[node.name] = methods
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return {
        "classes": classes,
        "functions": functions,
        "names": names,
    }


def interface_check(source: str, expected: dict[str, Any]) -> dict[str, Any]:
    try:
        inventory = _interface_inventory(source)
    except SyntaxError as exc:
        return {"status": "BLOCKED", "syntax_error": str(exc), "missing": ["VALID_PYTHON_SOURCE"]}

    missing: list[str] = []
    for name in expected.get("classes", []):
        if name not in inventory["classes"]:
            missing.append(f"class:{name}")
    for name in expected.get("functions", []):
        if name not in inventory["functions"]:
            missing.append(f"function:{name}")
    for name in expected.get("names", []):
        if name not in inventory["names"]:
            missing.append(f"name:{name}")
    for class_name, methods in expected.get("methods", {}).items():
        present = inventory["classes"].get(class_name, set())
        for method in methods:
            if method not in present:
                missing.append(f"method:{class_name}.{method}")
    return {
        "status": "PASS" if not missing else "BLOCKED",
        "missing": sorted(missing),
    }


def _probe_target(
    client: Any,
    root: Path,
    target: dict[str, Any],
    upstream_branch: str,
) -> dict[str, Any]:
    pin_path = root / str(target["pin_path"])
    pin = _load_json(pin_path)
    _require(pin.get("schema_version") == SUPPORTED_SCHEMA_VERSION, "unsupported pin schema_version")
    repository = pin.get("source_repository")
    pinned_revision = pin.get("source_revision")
    _require(isinstance(repository, str) and repository, "pin source_repository missing")
    _require(isinstance(pinned_revision, str) and len(pinned_revision) == 40, "pin source_revision invalid")

    pin_files = _pin_files(pin)
    primary = _primary_file(pin_files, target["primary"])
    head_revision = client.branch_head(repository, upstream_branch)

    file_receipts: list[dict[str, Any]] = []
    pinned_primary_source: str | None = None
    head_primary_source: str | None = None
    for row in pin_files:
        pinned = client.file(repository, row["path"], pinned_revision)
        head = client.file(repository, row["path"], head_revision)
        identity_match = pinned["sha"] == row["blob_sha"]
        head_matches_pin = head["sha"] == row["blob_sha"]
        file_receipts.append(
            {
                "component_key": row["key"],
                "path": row["path"],
                "pinned_blob_sha": row["blob_sha"],
                "resolved_pinned_blob_sha": pinned["sha"],
                "pinned_identity_match": identity_match,
                "head_blob_sha": head["sha"],
                "head_matches_pinned_blob": head_matches_pin,
            }
        )
        if row["key"] == primary["key"]:
            pinned_primary_source = pinned["text"]
            head_primary_source = head["text"]

    _require(pinned_primary_source is not None and head_primary_source is not None, "primary source was not fetched")
    pinned_interface = interface_check(pinned_primary_source, target["interface"])
    head_interface = interface_check(head_primary_source, target["interface"])
    pin_identity_ok = all(row["pinned_identity_match"] for row in file_receipts)
    target_blob_drift = any(not row["head_matches_pinned_blob"] for row in file_receipts)
    interface_drift = pinned_interface["status"] != "PASS" or head_interface["status"] != "PASS"

    repository_head_advanced = head_revision != pinned_revision
    if target_blob_drift:
        drift_class = "TARGET_BLOB_DRIFT"
    elif repository_head_advanced:
        drift_class = "REPOSITORY_HEAD_ADVANCED_TARGETS_STABLE"
    else:
        drift_class = "NONE"

    status = "PASS"
    reasons: list[str] = []
    if not pin_identity_ok:
        status = "BLOCKED"
        reasons.append("PIN_IDENTITY_MISMATCH")
    if target_blob_drift:
        status = "BLOCKED"
        reasons.append("TARGET_BLOB_DRIFT")
    if interface_drift:
        status = "BLOCKED"
        reasons.append("INTERFACE_SCHEMA_DRIFT")

    return {
        "target_id": target["target_id"],
        "status": status,
        "blocked_reasons": reasons,
        "pin_identity_proof": {
            "status": "PASS" if pin_identity_ok else "BLOCKED",
            "repository": repository,
            "revision": pinned_revision,
            "files": file_receipts,
        },
        "live_readonly_integration_proof": {
            "status": "PASS" if not target_blob_drift and head_interface["status"] == "PASS" else "BLOCKED",
            "upstream_branch": upstream_branch,
            "upstream_head_revision": head_revision,
            "repository_head_advanced": repository_head_advanced,
            "drift_class": drift_class,
            "target_blob_drift_detected": target_blob_drift,
            "pinned_interface": pinned_interface,
            "head_interface": head_interface,
            "writes_attempted": 0,
        },
    }


def run_probe(
    client: Any | None = None,
    *,
    root: Path = ROOT,
    targets_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    client = client or GitHubReadOnlyClient()
    config = _load_json(targets_path or (root / "verification" / "UPSTREAM_LIVE_TARGETS.json"))
    _require(config.get("schema_version") == SUPPORTED_SCHEMA_VERSION, "unsupported target-config schema_version")
    _require(config.get("authority_class") == "OBSERVE", "upstream proof authority must remain OBSERVE")
    upstream_branch = config.get("upstream_branch")
    _require(isinstance(upstream_branch, str) and upstream_branch, "upstream branch missing")
    targets = config.get("targets")
    _require(isinstance(targets, list) and targets, "upstream targets missing")

    rows: list[dict[str, Any]] = []
    for target in targets:
        try:
            rows.append(_probe_target(client, root, target, upstream_branch))
        except Exception as exc:
            rows.append(
                {
                    "target_id": target.get("target_id", "unknown"),
                    "status": "BLOCKED",
                    "blocked_reasons": ["PROBE_ERROR"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "pin_identity_proof": {"status": "BLOCKED"},
                    "live_readonly_integration_proof": {
                        "status": "BLOCKED",
                        "writes_attempted": 0,
                    },
                }
            )

    status = "PASS" if all(row["status"] == "PASS" for row in rows) else "BLOCKED"
    body = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "proof_id": config["proof_id"],
        "status": status,
        "generated_at": generated_at or _now(),
        "repository_sha": os.getenv("GITHUB_SHA"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "authority_class": "OBSERVE",
        "write_authority": False,
        "targets": rows,
        "network_reads": getattr(client, "network_reads", None),
        "separate_proofs": {
            "pin_blob_identity": True,
            "live_readonly_integration": True,
        },
    }
    return body | {"receipt_hash": _canonical_hash(body)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="verification/out/upstream_live_integration_receipt.json",
    )
    args = parser.parse_args()
    receipt = run_probe()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
