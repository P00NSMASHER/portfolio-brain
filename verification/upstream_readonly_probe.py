#!/usr/bin/env python3
"""Read-only live proof for pinned Portfolio Brain upstream integrations.

The identity receipt proves the configured revision/blob exists upstream.
The integration receipt separately proves the exact source can be fetched and
its required Python interface parsed. Upstream code is never imported/executed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "verification" / "UPSTREAM_READONLY_INTEGRATION_CONTRACT.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class UpstreamProbeError(ValueError):
    pass


class UpstreamNetworkError(RuntimeError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise UpstreamProbeError(message)


def _now(value: str | None = None) -> str:
    if value is not None:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(parsed.tzinfo is not None, "probe timestamp requires timezone")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _git_blob_sha(raw: bytes) -> str:
    prefix = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(prefix + raw).hexdigest()  # Git object identity is SHA-1.


def _receipt(body: dict[str, Any]) -> dict[str, Any]:
    return body | {"receipt_hash": _hash(body)}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path} must contain an object")
    return value


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = _load_json(path)
    _require(set(contract) == {
        "schema_version", "contract_id", "source_repository", "network_policy", "integrations"
    }, "upstream integration contract fields changed")
    _require(contract["schema_version"] == "1.0.0", "upstream integration contract schema drifted")
    _require(contract["contract_id"] == "portfolio-upstream-readonly-integration-v1", "contract identity drifted")
    _require(contract["source_repository"] == "P00NSMASHER/github-value-hunt-ledger", "source repository widened")
    network = contract["network_policy"]
    _require(network == {
        "mode": "READ_ONLY_PUBLIC_GITHUB",
        "allowed_hosts": ["api.github.com", "raw.githubusercontent.com"],
        "max_requests_per_run": 8,
        "execute_upstream_code": False,
    }, "read-only upstream network policy drifted")
    integrations = contract["integrations"]
    _require(isinstance(integrations, list) and len(integrations) == 4, "expected four pinned upstream integrations")
    ids = [row.get("integration_id") for row in integrations]
    _require(len(ids) == len(set(ids)), "duplicate upstream integration id")
    for row in integrations:
        _require(set(row) == {
            "integration_id", "pin_path", "pin_component", "required_classes",
            "required_functions", "required_class_methods"
        }, f"integration contract fields drifted: {row.get('integration_id')}")
        _require(isinstance(row["pin_path"], str) and row["pin_path"], "pin path required")
        _require(isinstance(row["required_classes"], list), "required_classes must be a list")
        _require(isinstance(row["required_functions"], list), "required_functions must be a list")
        _require(isinstance(row["required_class_methods"], dict), "required_class_methods must be an object")
    return contract


def _safe_repo_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    _require(ROOT == path or ROOT in path.parents, "pin path escapes repository")
    return path


def _pin_source(spec: dict[str, Any], source_repository: str) -> dict[str, str]:
    pin = _load_json(_safe_repo_path(spec["pin_path"]))
    _require(pin.get("schema_version") == "1.0.0", f"{spec['integration_id']} pin schema/version drifted")
    _require(pin.get("source_repository") == source_repository, f"{spec['integration_id']} source repository drifted")
    revision = pin.get("source_revision")
    _require(isinstance(revision, str) and SHA40.fullmatch(revision) is not None,
             f"{spec['integration_id']} source revision invalid")
    component = spec["pin_component"]
    if component is None:
        path = pin.get("source_path")
        blob_sha = pin.get("source_blob_sha")
    else:
        components = pin.get("components")
        _require(isinstance(components, dict) and component in components,
                 f"{spec['integration_id']} pinned component missing")
        entry = components[component]
        _require(isinstance(entry, dict), f"{spec['integration_id']} component invalid")
        path = entry.get("path")
        blob_sha = entry.get("blob_sha")
    _require(isinstance(path, str) and path and not path.startswith("/") and ".." not in Path(path).parts,
             f"{spec['integration_id']} source path invalid")
    _require(isinstance(blob_sha, str) and SHA40.fullmatch(blob_sha) is not None,
             f"{spec['integration_id']} source blob invalid")
    return {
        "repository": source_repository,
        "revision": revision,
        "path": path,
        "blob_sha": blob_sha,
        "pin_path": spec["pin_path"],
        "pin_schema_version": pin["schema_version"],
    }


class GitHubReadonlyClient:
    def __init__(self, *, max_requests: int = 8, timeout: float = 15.0):
        self.max_requests = max_requests
        self.timeout = timeout
        self.requests = 0
        self.token = os.environ.get("GITHUB_TOKEN", "").strip()

    def _read(self, url: str, *, api: bool) -> bytes:
        host = urllib.parse.urlparse(url).hostname
        if host not in {"api.github.com", "raw.githubusercontent.com"}:
            raise UpstreamNetworkError("upstream host not allowlisted")
        self.requests += 1
        if self.requests > self.max_requests:
            raise UpstreamNetworkError("upstream request budget exceeded")
        headers = {
            "Accept": "application/vnd.github+json" if api else "text/plain",
            "User-Agent": "portfolio-brain-upstream-readonly-probe/1",
        }
        if api and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                final_host = urllib.parse.urlparse(response.geturl()).hostname
                if final_host != host:
                    raise UpstreamNetworkError("upstream redirect changed host")
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpstreamNetworkError(type(exc).__name__) from exc

    def metadata(self, repository: str, revision: str, path: str) -> dict[str, Any]:
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_ref = urllib.parse.quote(revision, safe="")
        url = f"https://api.github.com/repos/{repository}/contents/{encoded_path}?ref={encoded_ref}"
        try:
            value = json.loads(self._read(url, api=True).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpstreamNetworkError("invalid GitHub metadata response") from exc
        if not isinstance(value, dict):
            raise UpstreamNetworkError("unexpected GitHub metadata response")
        return value

    def raw(self, repository: str, revision: str, path: str) -> bytes:
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_ref = urllib.parse.quote(revision, safe="")
        url = f"https://raw.githubusercontent.com/{repository}/{encoded_ref}/{encoded_path}"
        return self._read(url, api=False)


def _interface_observation(raw: bytes, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise UpstreamProbeError(f"{spec['integration_id']} source is not parseable Python") from exc

    functions = {
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    classes: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes[node.name] = {
                child.name for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

    required_classes = set(spec["required_classes"])
    required_functions = set(spec["required_functions"])
    missing_classes = sorted(required_classes - set(classes))
    missing_functions = sorted(required_functions - functions)
    missing_methods: dict[str, list[str]] = {}
    for class_name, expected in spec["required_class_methods"].items():
        observed = classes.get(class_name, set())
        missing = sorted(set(expected) - observed)
        if missing:
            missing_methods[class_name] = missing

    public_view = {
        "functions": sorted(x for x in functions if not x.startswith("_")),
        "classes": sorted(classes),
        "required_class_methods": {
            class_name: sorted(classes.get(class_name, set()))
            for class_name in sorted(spec["required_class_methods"])
        },
    }
    return {
        "parse_verified": True,
        "missing_classes": missing_classes,
        "missing_functions": missing_functions,
        "missing_methods": missing_methods,
        "interface_compatible": not (missing_classes or missing_functions or missing_methods),
        "observed_interface_hash": _hash(public_view),
    }


def _rollup(rows: list[dict[str, Any]], good: str) -> str:
    statuses = {row["status"] for row in rows}
    if statuses == {good}:
        return good
    if "BLOCKED" in statuses:
        return "BLOCKED"
    return "UNKNOWN"


def run_probe(
    *,
    output_dir: Path,
    at: str | None = None,
    metadata_fetcher: Callable[[str, str, str], dict[str, Any]] | None = None,
    raw_fetcher: Callable[[str, str, str], bytes] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = load_contract()
    checked_at = _now(at)
    client = GitHubReadonlyClient(max_requests=contract["network_policy"]["max_requests_per_run"])
    metadata_fetcher = metadata_fetcher or client.metadata
    raw_fetcher = raw_fetcher or client.raw

    identity_rows: list[dict[str, Any]] = []
    live_rows: list[dict[str, Any]] = []

    for spec in contract["integrations"]:
        integration_id = spec["integration_id"]
        try:
            source = _pin_source(spec, contract["source_repository"])
        except (OSError, json.JSONDecodeError, UpstreamProbeError) as exc:
            row = {
                "integration_id": integration_id,
                "status": "BLOCKED",
                "reason": f"PIN_CONTRACT_DRIFT:{type(exc).__name__}",
            }
            identity_rows.append(row)
            live_rows.append(row | {"proof": "LIVE_READ_ONLY_INTERFACE"})
            continue

        base = {
            "integration_id": integration_id,
            "repository": source["repository"],
            "revision": source["revision"],
            "path": source["path"],
            "pinned_blob_sha": source["blob_sha"],
            "pin_path": source["pin_path"],
            "pin_schema_version": source["pin_schema_version"],
        }

        try:
            metadata = metadata_fetcher(source["repository"], source["revision"], source["path"])
        except Exception as exc:
            if not isinstance(exc, UpstreamNetworkError):
                exc = UpstreamNetworkError(type(exc).__name__)
            identity_rows.append(base | {
                "status": "UNKNOWN",
                "reason": f"IDENTITY_FETCH_FAILED:{type(exc).__name__}",
                "observed_blob_sha": None,
            })
            live_rows.append(base | {
                "status": "UNKNOWN",
                "reason": "IDENTITY_NOT_VERIFIED",
                "raw_git_blob_sha": None,
                "interface_compatible": None,
            })
            continue

        observed_sha = metadata.get("sha")
        metadata_ok = metadata.get("type") == "file" and metadata.get("path") == source["path"]
        identity_ok = metadata_ok and observed_sha == source["blob_sha"]
        identity_rows.append(base | {
            "status": "VERIFIED" if identity_ok else "BLOCKED",
            "reason": "EXACT_PIN_IDENTITY" if identity_ok else "PIN_OR_METADATA_DRIFT",
            "observed_blob_sha": observed_sha if isinstance(observed_sha, str) else None,
        })
        if not identity_ok:
            live_rows.append(base | {
                "status": "BLOCKED",
                "reason": "PIN_IDENTITY_REQUIRED_BEFORE_LIVE_PROBE",
                "raw_git_blob_sha": None,
                "interface_compatible": None,
            })
            continue

        try:
            raw = raw_fetcher(source["repository"], source["revision"], source["path"])
            raw_sha = _git_blob_sha(raw)
            if raw_sha != source["blob_sha"]:
                raise UpstreamProbeError("raw source Git blob does not match pinned identity")
            observed = _interface_observation(raw, spec)
            compatible = observed["interface_compatible"]
            live_rows.append(base | {
                "status": "LIVE" if compatible else "BLOCKED",
                "reason": "READ_ONLY_SOURCE_INTERFACE_VERIFIED" if compatible else "UPSTREAM_INTERFACE_DRIFT",
                "raw_git_blob_sha": raw_sha,
                **observed,
            })
        except UpstreamNetworkError as exc:
            live_rows.append(base | {
                "status": "UNKNOWN",
                "reason": f"LIVE_FETCH_FAILED:{type(exc).__name__}",
                "raw_git_blob_sha": None,
                "interface_compatible": None,
            })
        except UpstreamProbeError as exc:
            live_rows.append(base | {
                "status": "BLOCKED",
                "reason": f"LIVE_INTERFACE_BLOCKED:{str(exc)}",
                "raw_git_blob_sha": None,
                "interface_compatible": False,
            })

    identity_body = {
        "schema_version": "1.0.0",
        "receipt_id": "portfolio-upstream-pin-identity-v1",
        "proof_kind": "PIN_BLOB_IDENTITY",
        "checked_at": checked_at,
        "status": _rollup(identity_rows, "VERIFIED"),
        "authority_class": "OBSERVE",
        "authority_granted": False,
        "evidence_upgraded": False,
        "components": identity_rows,
    }
    live_body = {
        "schema_version": "1.0.0",
        "receipt_id": "portfolio-upstream-live-integration-v1",
        "proof_kind": "LIVE_READ_ONLY_SOURCE_INTERFACE",
        "checked_at": checked_at,
        "status": _rollup(live_rows, "LIVE"),
        "network_mode": contract["network_policy"]["mode"],
        "upstream_code_executed": False,
        "authority_class": "OBSERVE",
        "authority_granted": False,
        "evidence_upgraded": False,
        "components": live_rows,
    }
    identity_receipt = _receipt(identity_body)
    live_receipt = _receipt(live_body)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "upstream_pin_identity_receipt.json").write_text(
        json.dumps(identity_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "upstream_live_integration_receipt.json").write_text(
        json.dumps(live_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return identity_receipt, live_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify pinned upstream identity and read-only live interface separately")
    parser.add_argument("--output-dir", default="verification/out")
    parser.add_argument("--at", default=None)
    args = parser.parse_args()
    identity, live = run_probe(output_dir=Path(args.output_dir), at=args.at)
    print(json.dumps({
        "pin_identity_status": identity["status"],
        "live_integration_status": live["status"],
        "pin_receipt_hash": identity["receipt_hash"],
        "live_receipt_hash": live["receipt_hash"],
    }, sort_keys=True))
    if identity["status"] != "VERIFIED" or live["status"] != "LIVE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
