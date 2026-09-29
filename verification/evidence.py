"""Read-only evidence resolution. Checksums establish integrity, not authorship.

Production sources must be explicitly approved by an independently protected
verifier configuration. The checked-in policy denies all sources until that
administrative prerequisite is satisfied. Never execute candidate code here.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import urllib.request
import urllib.error
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from value_proof.strict_json import strict_json_loads

ROOT = Path(__file__).resolve().parents[1]

class EvidenceError(ValueError):
    pass

def require(ok: bool, message: str) -> None:
    if not ok:
        raise EvidenceError(message)

def canonical(value: Any) -> str:
    # Reuse the existing strict JSON boundary (duplicate keys / nonfinite values).
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    strict_json_loads(text)
    return text

def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()

def timestamp(value: Any) -> datetime:
    require(isinstance(value, str) and bool(value), "timestamp required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise EvidenceError("invalid timestamp") from exc
    require(result.tzinfo is not None, "timezone required")
    return result.astimezone(timezone.utc)

def finite_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0

def exact_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None

@dataclass(frozen=True)
class ResolvedEvidence:
    record: dict[str, Any]
    scope: str
    receipt_identity: str

class EvidenceResolver(Protocol):
    def resolve(self, reference: str) -> ResolvedEvidence: ...

def resolve_claim(resolver: EvidenceResolver | None, reference: str, *, kind: str,
                  subject: dict[str, Any], now: datetime | None = None) -> ResolvedEvidence:
    require(resolver is not None, "trusted evidence resolver required")
    require(isinstance(reference, str) and bool(reference), "evidence reference required")
    evidence = resolver.resolve(reference)
    require(isinstance(evidence, ResolvedEvidence), "invalid resolver result")
    require(evidence.scope in {"PROVIDER_VERIFIED", "SYNTHETIC_FIXTURE"}, "untrusted evidence scope")
    row = evidence.record
    require(isinstance(row, dict) and set(row) == {
        "schema_version", "kind", "subject", "producer_id", "verifier_id",
        "verified_at", "expires_at", "measurements"
    }, "evidence envelope schema mismatch")
    require(row["schema_version"] == "1.0.0" and row["kind"] == kind, "evidence kind mismatch")
    require(canonical(row["subject"]) == canonical(subject), "evidence subject binding mismatch")
    require(all(isinstance(row[k], str) and row[k] for k in ("producer_id", "verifier_id")), "principals required")
    require(row["producer_id"] != row["verifier_id"], "producer cannot independently verify its own evidence")
    clock = now or datetime.now(timezone.utc)
    require(timestamp(row["verified_at"]) <= clock <= timestamp(row["expires_at"]), "future or expired evidence")
    require(isinstance(row["measurements"], dict) and bool(row["measurements"]), "measurements required")
    canonical(row)
    return evidence

class GitHubArtifactResolver:
    """Resolve approved immutable artifact bytes against GitHub's own metadata.

    Configuration, this implementation and credentials belong to the trusted
    verifier process, never the candidate sandbox. An empty allowlist denies
    access before any network request. Injection hooks are for deterministic
    provider-adapter tests, not a candidate-supplied resolver configuration.
    """
    def __init__(self, policy: dict[str, Any] | None = None, *, get_json=None,
                 download=None, now: datetime | None = None):
        self.policy = policy if policy is not None else strict_json_loads(
            (ROOT / "verification" / "EVIDENCE_TRUST_POLICY.json").read_text())
        require(set(self.policy) == {"schema_version", "approved_sources", "max_archive_bytes", "max_evidence_age_seconds"}, "trust policy schema mismatch")
        require(self.policy["schema_version"] == "1.0.0", "trust policy version mismatch")
        require(isinstance(self.policy["approved_sources"], list), "source allowlist required")
        for source in self.policy["approved_sources"]:
            require(set(source) == {"repository", "workflow_id", "workflow_revision_sha", "branch", "principal_id"}, "approved source schema mismatch")
            require(exact_sha(source["workflow_revision_sha"]), "approved workflow must be revision pinned")
            require(type(source["workflow_id"]) is int and source["workflow_id"] > 0, "invalid workflow identity")
            require(type(source["principal_id"]) is int and source["principal_id"] > 0, "invalid verifier principal")
            require(all(isinstance(source[k], str) and source[k] for k in ("repository", "branch")), "source repository/branch required")
        require(type(self.policy["max_archive_bytes"]) is int and 0 < self.policy["max_archive_bytes"] <= 8_000_000, "archive limit invalid")
        require(type(self.policy["max_evidence_age_seconds"]) is int and 0 < self.policy["max_evidence_age_seconds"] <= 86400, "evidence age limit invalid")
        self.get_json = get_json or self._get_json
        self.download = download or self._download
        self.now = now or datetime.now(timezone.utc)

    def _request(self, url: str) -> bytes:
        require(url.startswith("https://api.github.com/repos/"), "only approved GitHub repository endpoints allowed")
        headers = {"User-Agent": "portfolio-brain-evidence-verifier", "Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        # Do not forward a GitHub bearer token to artifact-storage redirects.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            response = opener.open(urllib.request.Request(url, headers=headers), timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise
            location = exc.headers.get("Location", "")
            parsed = urllib.parse.urlparse(location)
            host = parsed.hostname or ""
            require(parsed.scheme == "https" and (host.endswith(".blob.core.windows.net") or host.endswith(".githubusercontent.com") or host.endswith(".actions.githubusercontent.com")), "unexpected artifact redirect")
            response = urllib.request.urlopen(urllib.request.Request(location, headers={"User-Agent": headers["User-Agent"]}), timeout=20)
        with response:
            value = response.read(self.policy["max_archive_bytes"] + 1)
        require(len(value) <= self.policy["max_archive_bytes"], "response exceeds bounded size")
        return value

    def _get_json(self, url: str) -> dict[str, Any]:
        return strict_json_loads(self._request(url).decode("utf-8"))

    def _download(self, url: str) -> bytes:
        return self._request(url)

    def resolve(self, reference: str) -> ResolvedEvidence:
        match = re.fullmatch(r"gha:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+):(\d+):(\d+):([A-Za-z0-9_./-]+\.json)", reference)
        require(match is not None, "invalid GitHub artifact reference")
        repository, run_id, artifact_id, member = match.groups()
        require(not member.startswith("/") and ".." not in member.split("/"), "unsafe evidence member path")
        sources = [s for s in self.policy["approved_sources"] if s["repository"] == repository]
        require(bool(sources), "evidence repository is not approved")
        base = "https://api.github.com/repos/" + repository
        run = self.get_json(f"{base}/actions/runs/{run_id}")
        require(run.get("id") == int(run_id) and run.get("status") == "completed" and run.get("conclusion") == "success", "source run did not succeed")
        require(run.get("repository", {}).get("full_name") == repository and run.get("head_repository", {}).get("full_name") == repository, "source run is from wrong repository/fork")
        approved = [s for s in sources if run.get("workflow_id") == s["workflow_id"] and run.get("head_sha") == s["workflow_revision_sha"] and run.get("head_branch") == s["branch"] and run.get("actor", {}).get("id") == s["principal_id"]]
        require(len(approved) == 1, "run workflow/revision/principal not uniquely approved")
        artifact = self.get_json(f"{base}/actions/artifacts/{artifact_id}")
        require(artifact.get("id") == int(artifact_id) and artifact.get("expired") is False, "artifact missing/expired")
        require(artifact.get("workflow_run", {}).get("id") == int(run_id) and artifact["workflow_run"].get("head_sha") == run["head_sha"], "artifact/run binding mismatch")
        require(timestamp(run["run_started_at"]) <= timestamp(artifact["created_at"]) <= timestamp(run["updated_at"]) <= self.now, "artifact chronology mismatch")
        # Reject artifacts left over from an earlier attempt after a workflow rerun.
        require(timestamp(artifact["created_at"]) >= timestamp(run["run_started_at"]), "artifact predates run attempt")
        raw = self.download(f"{base}/actions/artifacts/{artifact_id}/zip")
        require(len(raw) <= self.policy["max_archive_bytes"], "archive too large")
        require(artifact.get("digest") == "sha256:" + hashlib.sha256(raw).hexdigest(), "provider artifact digest mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(sum(i.file_size for i in entries) <= self.policy["max_archive_bytes"], "expanded archive too large")
            require(sum(i.filename == member for i in entries) == 1, "evidence member missing or duplicated")
            row = strict_json_loads(archive.read(member).decode("utf-8"))
        require(str(approved[0]["principal_id"]) == row.get("verifier_id"), "claimed verifier does not match provider principal")
        age = (self.now - timestamp(row.get("verified_at"))).total_seconds()
        require(0 <= age <= self.policy["max_evidence_age_seconds"], "evidence is stale or future dated")
        require(timestamp(run["run_started_at"]) <= timestamp(row["verified_at"]) <= timestamp(artifact["created_at"]), "verification timestamp is outside source execution")
        return ResolvedEvidence(row, "PROVIDER_VERIFIED", reference)
