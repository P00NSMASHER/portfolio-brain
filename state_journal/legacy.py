"""Restore every legacy durable state through its production validator."""
from __future__ import annotations
import json
import os
from pathlib import Path
from state_journal.contracts import DOMAINS, JournalError, digest, validate_domain, require
from state_journal.transport import GitHubReader
from runtime import artifact_state as runtime_artifact
from agents import artifact_state as heartbeat_artifact
from hunting import artifact_state as hunter_artifact
from hunting import proposal_artifact_state as proposal_artifact
from hunting import proposal_review_artifact_state as review_artifact
from scheduler import artifact_state as scheduler_artifact
from cost_governor import artifact_state as cost_artifact
from model_router import feedback_artifact_state as feedback_artifact
from learning import artifact_state as learning_artifact
from notifications import artifact_state as notification_artifact
from dashboard import history_artifact_state as history_artifact

RESTORERS = {
    "heartbeat": heartbeat_artifact.restore,
    "hunter": hunter_artifact.restore,
    "proposals": proposal_artifact.restore,
    "reviews": review_artifact.restore,
    "scheduler": scheduler_artifact.restore,
    "cost": cost_artifact.restore,
    "model_feedback": feedback_artifact.restore,
    "learning": learning_artifact.restore,
    "notifications": notification_artifact.restore,
    "history": history_artifact.restore,
}

def _restore_runtime(output: Path, metadata: Path) -> str:
    return runtime_artifact.restore(
        output=output,
        metadata_output=metadata,
        provider_health_output=None,
        provider_health_metadata_output=None,
    )


def restore_domain(root: Path, domain: str, work: Path) -> tuple[dict, str]:
    require(domain in DOMAINS, "Unknown checkpoint domain")
    work.mkdir(parents=True, exist_ok=True)
    output = work / f"{domain}.json"
    metadata = work / f"{domain}.metadata.json"
    seed = DOMAINS[domain][3]
    original_run = os.environ.get("GITHUB_RUN_ID")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("PORTFOLIO_GITHUB_TOKEN")
    reader = GitHubReader(token, max_requests=5) if token else None
    status = "NO_PRIOR_ARTIFACT"
    try:
        for _attempt in range(5):
            output.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            if domain == "runtime":
                status = _restore_runtime(output, metadata)
            else:
                status = RESTORERS[domain](output, metadata)
            if not output.exists() or not metadata.exists() or reader is None:
                break
            meta = json.loads(metadata.read_text())
            source_run_ids = meta.get("source_run_ids")
            if isinstance(source_run_ids, list) and source_run_ids:
                require(
                    all(type(run_id) is int and run_id > 0 for run_id in source_run_ids),
                    f"{domain} merged metadata run ids invalid",
                )
            else:
                source_run_id = meta.get("source_run_id")
                if type(source_run_id) is not int or source_run_id <= 0:
                    break
                source_run_ids = [source_run_id]
            nonterminal = None
            for source_run_id in source_run_ids:
                source_run = reader.get(f"/actions/runs/{source_run_id}")
                if not (
                    source_run.get("status") == "completed"
                    and source_run.get("conclusion") in {"success", "failure", "cancelled", "timed_out"}
                ):
                    nonterminal = source_run_id
                    break
            if nonterminal is None:
                break
            # Legacy artifacts can become downloadable before their producer is
            # terminal. Such bytes are not yet eligible journal evidence, so
            # parity must compare against terminal evidence rather than racing
            # any in-progress member of a losslessly merged fork.
            os.environ["GITHUB_RUN_ID"] = str(nonterminal)
        else:
            require(False, f"{domain} legacy restore remained bound to non-terminal producers")
    finally:
        if original_run is None:
            os.environ.pop("GITHUB_RUN_ID", None)
        else:
            os.environ["GITHUB_RUN_ID"] = original_run
    if not output.exists():
        require(status == "NO_PRIOR_ARTIFACT" and seed is not None, f"{domain} missing durable state")
        output.write_bytes((root / seed).read_bytes())
        state = json.loads(output.read_text())
        validate_domain(domain, state)
        ref = f"repo-seed:{os.environ.get('CHECKPOINT_SOURCE_SHA', 'UNKNOWN')}:{Path(seed).as_posix()}:{digest(state)}"
        return state, ref
    state = json.loads(output.read_text())
    validate_domain(domain, state)
    meta = json.loads(metadata.read_text())
    require(meta.get("source_state_hash") == digest(state), f"{domain} metadata hash mismatch")
    if meta.get("restore_status", "").startswith("RESTORED_MERGED_COMMUTING_HEARTBEAT_FORK_"):
        require(domain == "heartbeat", "Only heartbeat restore may carry merged fork metadata")
        artifact_ids = meta.get("source_artifact_ids")
        run_ids = meta.get("source_run_ids")
        head_shas = meta.get("source_head_shas")
        artifact_digests = meta.get("source_artifact_digests")
        require(
            isinstance(artifact_ids, list) and artifact_ids
            and all(type(value) is int and value > 0 for value in artifact_ids),
            "heartbeat merged metadata artifact ids invalid",
        )
        require(
            isinstance(run_ids, list) and len(run_ids) == len(artifact_ids)
            and all(type(value) is int and value > 0 for value in run_ids),
            "heartbeat merged metadata run ids invalid",
        )
        require(
            isinstance(head_shas, list) and len(head_shas) == len(artifact_ids)
            and all(isinstance(value, str) and len(value) == 40 for value in head_shas),
            "heartbeat merged metadata source SHAs invalid",
        )
        require(
            isinstance(artifact_digests, list) and len(artifact_digests) == len(artifact_ids)
            and all(isinstance(value, str) and value.startswith("sha256:") for value in artifact_digests),
            "heartbeat merged metadata digests invalid",
        )
        ref = (
            "github-actions:merged-heartbeat-artifacts=" + ",".join(map(str, artifact_ids))
            + ";runs=" + ",".join(map(str, run_ids))
            + ";shas=" + ",".join(head_shas)
            + ";digests=" + ",".join(str(value) for value in artifact_digests)
            + f";sequence={meta['source_sequence']};hash={meta['source_state_hash']};"
            + f"created={meta['artifact_created_at']}"
        )
        return state, ref

    require(meta.get("artifact_id") is not None, f"{domain} metadata missing artifact")
    ref = (
        f"github-actions:artifact={meta['artifact_id']};run={meta['source_run_id']};"
        f"sha={meta['source_head_sha']};sequence={meta['source_sequence']};"
        f"hash={meta['source_state_hash']};created={meta['artifact_created_at']}"
    )
    return state, ref


def restore_all(root: Path, work: Path) -> tuple[dict, dict]:
    states, refs = {}, {}
    for domain in sorted(DOMAINS):
        try:
            state, ref = restore_domain(root, domain, work / domain)
        except Exception as exc:
            raise JournalError(
                f"LEGACY_RESTORE_FAILED:{domain}:{type(exc).__name__}:{exc}"
            ) from exc
        states[domain] = state
        refs[domain] = ref
    return states, refs
