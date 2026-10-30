"""Report the runtime's declared authority without treating tools as grants.

This is an audit receipt, not an authorization mechanism. Provider connections
available to a human or ChatGPT session are not inherited by GitHub Actions.
"""
from pathlib import Path
import hashlib
import re

from brain.core import require

REPOSITORY = "P00NSMASHER/portfolio-brain"
WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/brain-cycle.yml"
# A scope-name scan cannot establish which credentials the workflow uses.
# Workflow source change reviewed: state push now uses exact readback and both\n# source acceptance jobs are hard-held pending explicit user re-arm.
REVIEWED_WORKFLOW_SHA256 = "91dd5f7ab8108f1ade660d7038f8a5da6783e3ebe014e51c762aaf626fe61269"


def runtime_authority(workflow_text=None):
    """Summarize the reviewed Brain runner's explicit permission boundary.

    Fail closed if the workflow broadens or removes its reviewed token scopes.
    Cross-project writes stay unavailable until a separately installed and
    independently verified runtime integration exists.
    """
    if workflow_text is None:
        workflow_text = WORKFLOW.read_text(encoding="utf-8")
    require(type(workflow_text) is str, "V8_AUTHORITY_WORKFLOW_INVALID")
    workflow_digest = hashlib.sha256(workflow_text.encode("utf-8")).hexdigest()
    require(workflow_digest == REVIEWED_WORKFLOW_SHA256,
            "V8_AUTHORITY_WORKFLOW_REVIEW_REQUIRED")
    require("permissions:\n  contents: read\n" in workflow_text,
            "V8_AUTHORITY_REPOSITORY_DEFAULT_SCOPE_CHANGED")
    match = re.search(
        r"(?m)^  monitor:\n(?P<body>(?:^    .*\n|^\n)*)", workflow_text
    )
    require(match is not None, "V8_AUTHORITY_MONITOR_JOB_MISSING")
    body = match.group("body")
    for scope in ("contents: write", "pull-requests: write", "actions: write"):
        require(re.search(r"(?m)^      " + re.escape(scope) + r"\s*$", body),
                "V8_AUTHORITY_MONITOR_SCOPE_CHANGED")
    require("permissions: write-all" not in workflow_text,
            "V8_AUTHORITY_BROAD_PERMISSION_FORBIDDEN")
    return {
        "schema_version": 1,
        "runtime_repository": REPOSITORY,
        "runtime_surface": "GITHUB_ACTIONS_BRAIN_CYCLE",
        "workflow_sha256": workflow_digest,
        "authority_evidence_kind": "REVIEWED_SOURCE_CONFIGURATION_NOT_LIVE_PERMISSION_PROBE",
        "effective_permissions_verified": False,
        "workflow_declares": {
            "repository_default": {"contents": "read"},
            "monitor_job": {
                "contents": "write",
                "pull_requests": "write",
                "actions": "write",
            },
        },
        "credential_scope": "BRAIN_REPOSITORY_WORKFLOW_TOKEN_ONLY",
        "cross_project_source_observation": "PUBLIC_SOURCE_OBSERVATION_ONLY",
        "cross_project_code_write": "NOT_CONFIGURED",
        "cross_project_deploy": "NOT_CONFIGURED",
        "chatgpt_connectors_in_runner": "NOT_INHERITED",
        "scheduled_task_mutation": "NOT_CONFIGURED",
        "independent_release_gate_required": True,
        "permission_expansion_verified": False,
        "provider_write_actions_verified": False,
    }
