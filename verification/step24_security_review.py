#!/usr/bin/env python3
"""Fail-closed Step 24 least-privilege evidence review.

This harness prepares evidence and reports blockers. It never changes repository
settings, grants authority, publishes a check, or declares Step 24 COMPLETE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
ALLOWED_VERIFIER_PERMISSIONS = {
    "actions": "read",
    "checks": "write",
    "contents": "read",
    "metadata": "read",
    "pull_requests": "read",
}


class SecurityReviewError(ValueError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def finding(domain: str, severity: str, code: str, detail: str, evidence: str) -> dict[str, str]:
    return {
        "domain": domain,
        "severity": severity,
        "code": code,
        "detail": detail,
        "evidence": evidence,
    }


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def contract(root: Path) -> dict[str, Any]:
    value = load_json(root / "verification" / "STEP24_SECURITY_CONTRACT.json")
    if value.get("schema_version") != "1.0.0":
        raise SecurityReviewError("Step 24 contract schema drift")
    if value.get("review_id") != "portfolio-step24-least-privilege-v1":
        raise SecurityReviewError("Step 24 contract identity drift")
    domains = value.get("required_domains")
    if not isinstance(domains, list) or len(domains) != len(set(domains)):
        raise SecurityReviewError("Step 24 domains invalid")
    return value


def report(contract_doc: dict[str, Any], observed: dict[str, Any],
           findings: list[dict[str, str]], live: bool) -> dict[str, Any]:
    counts = {name: 0 for name in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]}
    for item in findings:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    blocked = counts["CRITICAL"] > 0 or counts["HIGH"] > 0 or counts["UNKNOWN"] > 0
    body = {
        "schema_version": "1.0.0",
        "review_id": contract_doc["review_id"],
        "status": "BLOCKED" if blocked else "READY_FOR_INDEPENDENT_SIGNOFF",
        "step24_complete": False,
        "live_evidence_present": live,
        "finding_counts": counts,
        "observed": observed,
        "findings": findings,
        "authority_granted": False,
        "evidence_upgraded": False,
    }
    return body | {"review_hash": digest(body)}


def repo006_binding(projects: dict[str, Any]) -> dict[str, Any] | None:
    matches = [
        binding
        for project in projects.get("projects", [])
        for binding in project.get("repository_bindings", [])
        if binding.get("repository_id") == "REPO-006"
    ]
    return matches[0] if len(matches) == 1 else None


def static_review(root: Path = ROOT) -> dict[str, Any]:
    c = contract(root)
    findings: list[dict[str, str]] = []
    observed: dict[str, Any] = {}
    paths = {
        "verifier_py": root / "verification" / "independent_verifier.py",
        "verifier_yml": root / ".github" / "workflows" / "portfolio-independent-verifier.yml",
        "repair_policy": root / "repair" / "AUTONOMOUS_REPAIR_POLICY.json",
        "factory_yml": root / ".github" / "workflows" / "software-factory-candidate.yml",
        "operating_policy": root / "operations" / "OPERATING_MODE_POLICY.json",
        "action_policy": root / "action_engine" / "ACTION_POLICY.json",
        "projects": root / "registry" / "projects.json",
    }
    missing = [str(path.relative_to(root)) for path in paths.values() if not path.exists()]
    if missing:
        findings.append(finding(
            "VERIFIER_TRUST_ANCHORS", "CRITICAL", "REQUIRED_SECURITY_FILE_MISSING",
            "Required security-review source files are missing.", ",".join(missing),
        ))
        return report(c, observed, findings, False)

    verifier_py = paths["verifier_py"].read_text(encoding="utf-8")
    verifier_yml = paths["verifier_yml"].read_text(encoding="utf-8")
    repair_policy = load_json(paths["repair_policy"])
    factory_yml = paths["factory_yml"].read_text(encoding="utf-8")
    operating = load_json(paths["operating_policy"])
    action = load_json(paths["action_policy"])
    projects = load_json(paths["projects"])

    anchors_ok = all(token in verifier_py for token in [
        "IMMUTABLE_TRUST_ANCHORS",
        '".github/workflows/portfolio-independent-verifier.yml"',
        '"verification/independent_verifier.py"',
        "VERIFIER_APP_ID = 5121826",
        "FOUNDATION_APP_ID = 15368",
    ])
    observed["verifier_trust_anchors"] = anchors_ok
    if not anchors_ok:
        findings.append(finding(
            "VERIFIER_TRUST_ANCHORS", "CRITICAL", "VERIFIER_TRUST_ANCHOR_DRIFT",
            "Independent verifier trust-anchor identities are incomplete or drifted.",
            "verification/independent_verifier.py",
        ))

    same_repo_ok = all(token in verifier_yml for token in [
        'get("full_name")==os.environ["GITHUB_REPOSITORY"]',
        'get("base",{}).get("ref")=="main"',
        'pr.get("user",{}).get("login")=="github-actions[bot]"',
        'branch.startswith("factory/auto-repair-")',
    ])
    observed["same_repo_head_restriction"] = same_repo_ok
    if not same_repo_ok:
        findings.append(finding(
            "PR_HEAD_AND_FORK_RESTRICTIONS", "CRITICAL", "PR_HEAD_RESTRICTION_DRIFT",
            "Trusted integration no longer proves same-repository/main-base/bot-branch identity.",
            ".github/workflows/portfolio-independent-verifier.yml",
        ))

    network_none = "--network none" in verifier_yml and "--cap-drop=ALL" in verifier_yml
    no_checkout_creds = "persist-credentials: false" in verifier_yml
    observed["candidate_network_isolation"] = network_none
    observed["candidate_checkout_credentials_disabled"] = no_checkout_creds
    if not network_none:
        findings.append(finding(
            "CANDIDATE_NETWORK_ISOLATION", "CRITICAL", "CANDIDATE_NETWORK_NOT_ISOLATED",
            "Candidate regressions are not explicitly network-disabled with reduced capabilities.",
            ".github/workflows/portfolio-independent-verifier.yml",
        ))
    if not no_checkout_creds:
        findings.append(finding(
            "SECRET_HANDLING", "CRITICAL", "CANDIDATE_CHECKOUT_CREDENTIALS_PERSIST",
            "Candidate checkout may retain Git credentials.",
            ".github/workflows/portfolio-independent-verifier.yml",
        ))

    candidate_marker = verifier_yml.find("Run candidate regressions in network-disabled containers")
    token_marker = verifier_yml.find("Mint short-lived independent verifier App token")
    publish_marker = verifier_yml.find("Publish exact-head independent gate")
    secret_order_ok = candidate_marker >= 0 and token_marker > candidate_marker and publish_marker > token_marker
    observed["verifier_secret_minted_after_candidate"] = secret_order_ok
    if not secret_order_ok:
        findings.append(finding(
            "SECRET_HANDLING", "CRITICAL", "VERIFIER_SECRET_ORDERING_DRIFT",
            "Verifier credentials must be minted only after candidate execution ends.",
            ".github/workflows/portfolio-independent-verifier.yml",
        ))

    repair_bounded = (
        repair_policy.get("merge_authority") is False
        and repair_policy.get("deployment_authority") is False
        and repair_policy.get("default_branch_write_authority") is False
        and repair_policy.get("branch_prefix") == "factory/auto-repair-"
    )
    observed["repair_generation_authority_bounded"] = repair_bounded
    if not repair_bounded:
        findings.append(finding(
            "AUTOMERGE_SCOPE", "CRITICAL", "REPAIR_GENERATOR_AUTHORITY_WIDENED",
            "Autonomous repair generation must remain isolated-branch only.",
            "repair/AUTONOMOUS_REPAIR_POLICY.json",
        ))

    merge_scope_ok = (
        "steps.pr.outputs.autonomous == 'true'" in verifier_yml
        and 'pulls/${PR_NUMBER}/merge' in verifier_yml
        and 'sha="$CANDIDATE_SHA"' in verifier_yml
    )
    observed["trusted_merge_scope_bounded_to_autonomous_repairs"] = merge_scope_ok
    if not merge_scope_ok:
        findings.append(finding(
            "AUTOMERGE_SCOPE", "CRITICAL", "TRUSTED_MERGE_SCOPE_DRIFT",
            "Trusted integrator merge must be exact-head and limited to authenticated repair PRs.",
            ".github/workflows/portfolio-independent-verifier.yml",
        ))

    factory_has_merge = any(token in factory_yml.lower() for token in [
        "gh pr merge", "/merge", "merge_pull",
    ])
    observed["software_factory_merge_command_present"] = factory_has_merge
    if factory_has_merge:
        findings.append(finding(
            "ADAPTER_WRITE_AUTHORITY", "CRITICAL", "SOFTWARE_FACTORY_MERGE_AUTHORITY",
            "Software-factory candidate workflow contains a merge command.",
            ".github/workflows/software-factory-candidate.yml",
        ))

    boundaries = root / "governance" / "boundaries.json"
    observed["governance_boundaries_present"] = boundaries.exists()
    if not boundaries.exists():
        findings.append(finding(
            "ADAPTER_WRITE_AUTHORITY", "HIGH", "GOVERNANCE_BOUNDARIES_MISSING",
            "Machine-readable adapter/action boundaries are absent on this revision.",
            "governance/boundaries.json",
        ))
    else:
        boundary_doc = load_json(boundaries)
        matrix = boundary_doc.get("authority_matrix", {})
        caps = boundary_doc.get("project_capabilities", [])
        required_human = ["PRODUCTION_DEPLOYMENT", "FINANCIAL_ACTION", "DESTRUCTIVE_ACTION", "CHILD_FACING_ACTION"]
        human_gates_ok = all(
            isinstance(matrix.get(name), dict)
            and matrix[name].get("decision") == "HUMAN_GATED"
            and matrix[name].get("autonomous") is False
            for name in required_human
        )
        email_rule = matrix.get("CUSTOMER_EMAIL_GMAIL", {})
        email_gate_ok = (
            isinstance(email_rule, dict)
            and email_rule.get("decision") in {"HUMAN_GATED", "PROHIBITED"}
            and email_rule.get("authority_from_observation") is False
        )
        live_trading_ok = (
            isinstance(matrix.get("LIVE_TRADING"), dict)
            and matrix["LIVE_TRADING"].get("decision") == "PROHIBITED"
            and matrix["LIVE_TRADING"].get("autonomous") is False
        )
        inheritance_ok = (
            boundary_doc.get("default_decision") == "DENY"
            and boundary_doc.get("inheritance_policy") == "NO_PROJECT_INHERITS_PORTFOLIO_BRAIN_AUTHORITY"
            and boundary_doc.get("core_autonomy_dependencies", {}).get("interactive_chatgpt_required") is False
            and boundary_doc.get("core_autonomy_dependencies", {}).get("gmail_required") is False
        )
        project_caps_ok = bool(caps) and all(
            isinstance(row, dict)
            and isinstance(row.get("capabilities"), dict)
            and row["capabilities"].get("DEPLOY") is False
            and row["capabilities"].get("EXTERNAL_ACTION") is False
            and (row.get("project_id") == "PRJ-000" or row["capabilities"].get("CANDIDATE_PR") is False)
            for row in caps
        )
        governance_ok = human_gates_ok and email_gate_ok and live_trading_ok and inheritance_ok and project_caps_ok
        observed["governance_authority_matrix_fail_closed"] = governance_ok
        observed["governance_email_human_gated"] = email_gate_ok
        observed["governance_no_inherited_authority"] = inheritance_ok
        observed["governance_project_caps_bounded"] = project_caps_ok
        if not governance_ok:
            findings.append(finding(
                "ADAPTER_WRITE_AUTHORITY", "HIGH", "GOVERNANCE_AUTHORITY_MATRIX_NOT_FAIL_CLOSED",
                "Authority matrix must deny inheritance, human-gate communications/deploy/financial/destructive/child-facing actions, prohibit live trading, and prevent downstream project deploy/external-action authority.",
                "governance/boundaries.json",
            ))

    gateways = operating.get("external_connector_gateways", {})
    allowed_actions = action.get("allowed_actions", {})
    customer_email = allowed_actions.get("CUSTOMER_EMAIL") if isinstance(allowed_actions, dict) else None
    explicit_human_gate = isinstance(customer_email, dict) and customer_email.get("requires_human_approval") is True
    gmail_act = (
        isinstance(gateways, dict)
        and "gmail" in gateways
        and isinstance(customer_email, dict)
        and not explicit_human_gate
    )
    observed["chatgpt_gmail_customer_email_authority_present"] = gmail_act
    if gmail_act:
        findings.append(finding(
            "ADAPTER_WRITE_AUTHORITY", "HIGH", "CHATGPT_GMAIL_CUSTOMER_EMAIL_AUTHORITY_PRESENT",
            "Machine policy still defines ChatGPT Gmail customer-email execution authority.",
            "operations/OPERATING_MODE_POLICY.json + action_engine/ACTION_POLICY.json",
        ))

    allowed_boundaries = {
        "SANITIZED_CODE_POLICY_AND_RECEIPTS_ONLY",
        "PUBLIC_OR_SANITIZED_EVIDENCE_ONLY",
        "PRIVATE_DATA_BY_REFERENCE_ONLY",
    }
    boundaries_seen = {
        p.get("project_id"): p.get("data_boundary")
        for p in projects.get("projects", []) if isinstance(p, dict)
    }
    persistence_ok = bool(boundaries_seen) and all(v in allowed_boundaries for v in boundaries_seen.values())
    observed["registry_persistence_sanitized_or_reference_only"] = persistence_ok
    if not persistence_ok:
        findings.append(finding(
            "SANITIZED_PUBLIC_PERSISTENCE", "HIGH", "PUBLIC_PERSISTENCE_BOUNDARY_WIDENED",
            "A registered project escaped sanitized/public/reference-only persistence classes.",
            "registry/projects.json",
        ))

    repo006 = repo006_binding(projects)
    repo006_ok = (
        isinstance(repo006, dict)
        and repo006.get("full_name") == "P00NSMASHER/permitplate-state"
        and repo006.get("integration_status") in {"BLOCKED", "READ_ONLY"}
    )
    observed["repo006_access_fail_closed"] = repo006_ok
    observed["repo006_binding"] = repo006
    if not repo006_ok:
        findings.append(finding(
            "REPO_006_ACCESS", "HIGH", "REPO006_ACCESS_NOT_FAIL_CLOSED",
            "REPO-006 must remain BLOCKED or explicitly READ_ONLY absent separate access evidence.",
            "registry/projects.json",
        ))

    return report(c, observed, findings, False)


def live_review(evidence: dict[str, Any], expected_main_sha: str) -> dict[str, Any]:
    c = contract(ROOT)
    findings: list[dict[str, str]] = []
    observed: dict[str, Any] = {}

    if SHA40.fullmatch(expected_main_sha) is None:
        raise SecurityReviewError("expected main SHA invalid")
    main_ok = evidence.get("observed_main_sha") == expected_main_sha
    observed["exact_main_identity"] = main_ok
    if not main_ok:
        findings.append(finding(
            "BRANCH_PROTECTION", "CRITICAL", "LIVE_EVIDENCE_MAIN_SHA_MISMATCH",
            "Live evidence does not match the expected main head.",
            str(evidence.get("observed_main_sha")),
        ))

    ruleset = evidence.get("ruleset")
    if not isinstance(ruleset, dict):
        findings.append(finding(
            "BRANCH_PROTECTION", "UNKNOWN", "RULESET_EVIDENCE_MISSING",
            "Full active ruleset evidence is required.", "live.ruleset",
        ))
    else:
        rows = ruleset.get("rules", [])
        types = {r.get("type") for r in rows if isinstance(r, dict)}
        status_checks: list[dict[str, Any]] = []
        strict = False
        for row in rows:
            if isinstance(row, dict) and row.get("type") == "required_status_checks":
                params = row.get("parameters", {})
                if isinstance(params, dict):
                    strict = params.get("strict_required_status_checks_policy") is True
                    status_checks.extend(params.get("required_status_checks", []))
        identities = {(x.get("context"), x.get("integration_id")) for x in status_checks if isinstance(x, dict)}
        rules_ok = (
            ruleset.get("enforcement") == "active"
            and ruleset.get("target") == "branch"
            and {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= types
            and strict
            and ("validate", 15368) in identities
            and ("portfolio-phase1-gate", 5121826) in identities
            and ruleset.get("bypass_actors") == []
            and ruleset.get("current_user_can_bypass") == "never"
        )
        observed["branch_protection_exact_checks_no_bypass"] = rules_ok
        observed["ruleset_id"] = ruleset.get("id")
        if not rules_ok:
            findings.append(finding(
                "BRANCH_PROTECTION", "CRITICAL", "MAIN_RULESET_INSUFFICIENT",
                "Main ruleset does not prove strict PR/check/no-bypass enforcement.",
                f"ruleset:{ruleset.get('id')}",
            ))

    app = evidence.get("verifier_app")
    if not isinstance(app, dict):
        findings.append(finding(
            "VERIFIER_APP_SCOPES", "UNKNOWN", "VERIFIER_APP_SCOPE_EVIDENCE_MISSING",
            "Live App 5121826 permission evidence is required.", "live.verifier_app",
        ))
    else:
        app_ok = app.get("id") == 5121826 and app.get("permissions") == ALLOWED_VERIFIER_PERMISSIONS
        observed["verifier_app_scope_exact"] = app_ok
        if not app_ok:
            findings.append(finding(
                "VERIFIER_APP_SCOPES", "CRITICAL", "VERIFIER_APP_SCOPE_WIDENED",
                "Verifier App identity or permissions exceed the reviewed set.",
                f"app:{app.get('id')}",
            ))

    artifact = evidence.get("artifact_probe")
    if not isinstance(artifact, dict):
        findings.append(finding(
            "ARTIFACT_TAMPER_RESISTANCE", "UNKNOWN", "ARTIFACT_IDENTITY_EVIDENCE_MISSING",
            "Exact run/head/artifact/digest evidence is required.", "live.artifact_probe",
        ))
    else:
        artifact_ok = (
            type(artifact.get("run_id")) is int and artifact["run_id"] > 0
            and type(artifact.get("artifact_id")) is int and artifact["artifact_id"] > 0
            and artifact.get("head_sha") == expected_main_sha
            and isinstance(artifact.get("digest"), str)
            and SHA256.fullmatch(artifact["digest"]) is not None
        )
        observed["artifact_exact_run_head_digest_traceable"] = artifact_ok
        if not artifact_ok:
            findings.append(finding(
                "ARTIFACT_TAMPER_RESISTANCE", "CRITICAL", "ARTIFACT_IDENTITY_UNTRACEABLE",
                "Artifact evidence is not bound to exact run/head/id/SHA-256 identity.",
                "live.artifact_probe",
            ))

    return report(c, observed, findings, True)


def combine(static: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    findings = list(static.get("findings", []))
    observed = {"static": static.get("observed", {})}
    if live is None:
        findings.append(finding(
            "BRANCH_PROTECTION", "UNKNOWN", "LIVE_SECURITY_EVIDENCE_NOT_SUPPLIED",
            "Step 24 requires live ruleset/App/artifact evidence against exact main.",
            "step24 live evidence",
        ))
        live_present = False
    else:
        findings.extend(live.get("findings", []))
        observed["live"] = live.get("observed", {})
        live_present = True
    return report(contract(ROOT), observed, findings, live_present)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--live-evidence", type=Path)
    parser.add_argument("--expected-main-sha")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    static = static_review(args.repo_root.resolve())
    live = None
    if args.live_evidence:
        if not args.expected_main_sha:
            raise SecurityReviewError("--expected-main-sha required with --live-evidence")
        live = live_review(load_json(args.live_evidence), args.expected_main_sha)
    result = combine(static, live)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 2 if args.require_ready and result["status"] != "READY_FOR_INDEPENDENT_SIGNOFF" else 0


if __name__ == "__main__":
    raise SystemExit(main())
