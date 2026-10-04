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
from fnmatch import fnmatchcase
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

SENSITIVE_WORKFLOW_PERMISSIONS = {
    ".github/workflows/portfolio-independent-verifier.yml": {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    },
    ".github/workflows/portfolio-autonomous-repair.yml": {
        "actions": "write",
        "contents": "write",
        "pull-requests": "write",
        "copilot-requests": "write",
    },
    ".github/workflows/software-factory-candidate.yml": {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    },
    ".github/workflows/portfolio-autonomous-scheduler.yml": {
        "actions": "write",
        "contents": "read",
        "pull-requests": "read",
    },
    ".github/workflows/portfolio-state-reducer.yml": {
        "actions": "read",
        "contents": "read",
    },
}
STATIC_REVIEW_DOMAINS = {
    "VERIFIER_TRUST_ANCHORS",
    "WORKFLOW_PERMISSIONS",
    "PR_HEAD_AND_FORK_RESTRICTIONS",
    "CANDIDATE_NETWORK_ISOLATION",
    "SECRET_HANDLING",
    "AUTOMERGE_SCOPE",
    "ADAPTER_WRITE_AUTHORITY",
    "SANITIZED_PUBLIC_PERSISTENCE",
    "REPO_006_ACCESS",
}
LIVE_REVIEW_DOMAINS = {
    "VERIFIER_APP_SCOPES",
    "ARTIFACT_TAMPER_RESISTANCE",
    "BRANCH_PROTECTION",
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
           findings: list[dict[str, str]], live: bool,
           covered_domains: set[str] | None = None) -> dict[str, Any]:
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
        "covered_domains": sorted(covered_domains or set()),
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


def _permissions_maps(text: str) -> tuple[dict[str, str] | None, list[dict[str, str] | None]]:
    """Return top-level permissions and every job-level override.

    Job-level maps are valid only when they narrow or preserve top-level scopes.
    Unspecified job-level permissions become none, so omission is a reduction.
    """
    lines = text.splitlines()
    top_starts = [index for index, line in enumerate(lines) if line == "permissions:"]
    job_starts = [index for index, line in enumerate(lines) if line == "    permissions:"]

    def parse_map(start: int, indent: int) -> dict[str, str] | None:
        prefix = " " * indent
        nested = " " * (indent + 2)
        values: dict[str, str] = {}
        for line in lines[start + 1:]:
            if not line.strip():
                continue
            if not line.startswith(prefix):
                break
            if line.startswith(nested):
                return None
            key, sep, value = line.strip().partition(":")
            if not sep or not key or not value.strip():
                return None
            values[key] = value.strip()
        return values or None

    top = parse_map(top_starts[0], 2) if len(top_starts) == 1 else None
    jobs = [parse_map(start, 6) for start in job_starts]
    return top, jobs


def _permissions_are_subset(child: dict[str, str] | None, parent: dict[str, str] | None) -> bool:
    if child is None or parent is None:
        return False
    rank = {"none": 0, "read": 1, "write": 2}
    for scope, value in child.items():
        if scope not in parent or value not in rank or parent[scope] not in rank:
            return False
        if rank[value] > rank[parent[scope]]:
            return False
    return True


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
        "autonomous_repair_yml": root / ".github" / "workflows" / "portfolio-autonomous-repair.yml",
        "scheduler_yml": root / ".github" / "workflows" / "portfolio-autonomous-scheduler.yml",
        "reducer_yml": root / ".github" / "workflows" / "portfolio-state-reducer.yml",
    }
    missing = [str(path.relative_to(root)) for path in paths.values() if not path.exists()]
    if missing:
        findings.append(finding(
            "VERIFIER_TRUST_ANCHORS", "CRITICAL", "REQUIRED_SECURITY_FILE_MISSING",
            "Required security-review source files are missing.", ",".join(missing),
        ))
        return report(c, observed, findings, False, set())

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

    workflow_permission_observations: dict[str, Any] = {}
    workflow_permissions_ok = True
    for workflow_path, expected_permissions in SENSITIVE_WORKFLOW_PERMISSIONS.items():
        workflow_text = (root / workflow_path).read_text(encoding="utf-8")
        actual_permissions, job_level_overrides = _permissions_maps(workflow_text)
        top_level_exact = actual_permissions == expected_permissions
        bounded_overrides = all(
            _permissions_are_subset(override, actual_permissions)
            for override in job_level_overrides
        )
        exact = top_level_exact and bounded_overrides
        workflow_permission_observations[workflow_path] = {
            "expected": expected_permissions,
            "observed": actual_permissions,
            "job_level_overrides": job_level_overrides,
            "job_level_overrides_bounded": bounded_overrides,
            "exact": exact,
        }
        workflow_permissions_ok = workflow_permissions_ok and exact
    observed["workflow_permissions"] = workflow_permission_observations
    observed["workflow_permissions_exact"] = workflow_permissions_ok
    if not workflow_permissions_ok:
        findings.append(finding(
            "WORKFLOW_PERMISSIONS", "CRITICAL", "WORKFLOW_PERMISSION_SCOPE_DRIFT",
            "Security-sensitive workflow token permissions differ from the reviewed least-privilege sets or add job-level overrides.",
            ",".join(sorted(SENSITIVE_WORKFLOW_PERMISSIONS)),
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

    canonical_email_gate_ok = False
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

        # Accept the checked-in canonical action-based governance schema only when
        # its explicit Gmail exception is tightly bounded and all high-risk authority
        # remains denied, prohibited, or human-gated.
        canonical_actions = boundary_doc.get("actions", {})
        required_human_actions = (
            "PRODUCTION_DEPLOYMENT",
            "FINANCIAL_ACTION",
            "DESTRUCTIVE_ACTION",
            "CHILD_FACING_ACTION",
        )
        canonical_human_gates_ok = all(
            isinstance(canonical_actions.get(name), dict)
            and canonical_actions[name].get("decision") == "HUMAN_APPROVAL_REQUIRED"
            and canonical_actions[name].get("autonomous_allowed") is False
            for name in required_human_actions
        )
        canonical_inheritance_ok = (
            boundary_doc.get("authority_model") == "DENY_BY_DEFAULT_PROJECT_SCOPED_NO_INHERITANCE"
            and boundary_doc.get("default_effect") == "DENY"
            and boundary_doc.get("core_autonomy_dependencies") == {
                "interactive_chatgpt_required": False,
                "gmail_required": False,
            }
        )
        canonical_live_trading_ok = (
            isinstance(canonical_actions.get("LIVE_TRADING"), dict)
            and canonical_actions["LIVE_TRADING"].get("decision") == "PROHIBITED"
            and canonical_actions["LIVE_TRADING"].get("autonomous_allowed") is False
        )
        pages = canonical_actions.get("PAGES_PUBLICATION", {})
        canonical_pages_ok = (
            isinstance(pages, dict)
            and pages.get("publication_only") is True
            and pages.get("production_deploy_authority") is False
        )
        bot = canonical_actions.get("PROTECTED_BOT_REPAIR_INTEGRATION", {})
        canonical_bot_ok = (
            isinstance(bot, dict)
            and bot.get("project_ids") == ["PRJ-000"]
            and bot.get("repository_ids") == ["REPO-008"]
            and set(bot.get("requires", [])) >= {
                "FOUNDATION_EXACT_HEAD_SUCCESS",
                "APP_5121826_EXACT_HEAD_SUCCESS",
                "PROTECTED_BRANCH_RULES",
            }
            and bot.get("bypass_authority") is False
        )
        canonical_project_caps_ok = bool(caps) and all(
            isinstance(row, dict)
            and isinstance(row.get("READ_OBSERVE"), dict)
            and row["READ_OBSERVE"].get("allowed") is True
            and row.get("DEPLOY") == {"allowed": False}
            and row.get("EXTERNAL_ACTION") == {"allowed": False}
            and (
                (
                    row.get("project_id") == "PRJ-000"
                    and row.get("CANDIDATE_PR", {}).get("allowed") is True
                    and row.get("CANDIDATE_PR", {}).get("repository_ids") == ["REPO-008"]
                    and row.get("CANDIDATE_PR", {}).get("branch_prefixes") == ["factory/", "auto-repair/"]
                )
                or (
                    row.get("project_id") != "PRJ-000"
                    and row.get("CANDIDATE_PR") == {
                        "allowed": False,
                        "repository_ids": [],
                        "branch_prefixes": [],
                    }
                )
            )
            for row in caps
        )
        canonical_email = canonical_actions.get("CUSTOMER_EMAIL_GMAIL", {})
        customer_email = action.get("allowed_actions", {}).get("CUSTOMER_EMAIL")
        gateway = operating.get("external_connector_gateways", {}).get("gmail")
        required_prohibited = {
            "PAYMENT_OR_PURCHASE",
            "BILLING_CHANGE",
            "MOVE_MONEY",
            "LEGAL_OR_REGULATORY_COMMUNICATION",
            "CLAIM_OR_DISPUTE_SUBMISSION",
            "DESTRUCTIVE_DATA_DELETION",
            "PRIVATE_INFORMATION_DISCLOSURE",
            "LIVE_MARKET_TRADING",
            "BROKERAGE_ORDER",
            "AUTONOMOUS_INVESTMENT_POSITION",
            "CONSEQUENTIAL_CHILD_FACING_CHANGE",
        }
        canonical_email_gate_ok = (
            isinstance(canonical_email, dict)
            and canonical_email.get("decision") == "EXPLICIT_MACHINE_POLICY_GATE"
            and canonical_email.get("autonomous_allowed") is True
            and canonical_email.get("core_runtime_dependency") is False
            and canonical_email.get("policy_ref") == "action_engine/ACTION_POLICY.json"
            and canonical_email.get("provider") == "CHATGPT_GMAIL_CONNECTOR"
            and canonical_email.get("merge_or_deploy_authority") is False
            and action.get("enabled") is True
            and action.get("authority_class") == "ACT"
            and set(action.get("allowed_actions", {})) == {"CUSTOMER_EMAIL"}
            and isinstance(customer_email, dict)
            and set(customer_email.get("allowed_consequences", [])) <= {"LOW", "MEDIUM"}
            and bool(customer_email.get("allowed_consequences"))
            and type(customer_email.get("max_per_utc_day")) is int
            and 0 < customer_email["max_per_utc_day"] <= 25
            and customer_email.get("max_per_recipient_per_utc_day") == 1
            and action.get("state_persistence", {}).get("sanitized_only") is True
            and action.get("kill_switches", {}).get("file") == "action_engine/KILL_SWITCH.json"
            and required_prohibited <= set(action.get("prohibited_action_types", []))
            and action.get("execution_provider") == "CHATGPT_GMAIL_CONNECTOR"
            and action.get("gmail_account_ref") == "PRIMARY_GMAIL_CONNECTOR"
            and isinstance(gateway, dict)
            and gateway.get("provider") == "CHATGPT_GMAIL_CONNECTOR"
            and gateway.get("policy_file") == "action_engine/ACTION_POLICY.json"
            and gateway.get("kill_switch_file") == "action_engine/KILL_SWITCH.json"
            and gateway.get("private_queue") == "GMAIL_DRAFTS"
        )
        canonical_governance_ok = (
            canonical_human_gates_ok
            and canonical_inheritance_ok
            and canonical_live_trading_ok
            and canonical_pages_ok
            and canonical_bot_ok
            and canonical_project_caps_ok
            and canonical_email_gate_ok
        )
        if canonical_governance_ok:
            governance_ok = True
            email_gate_ok = True
            inheritance_ok = True
            project_caps_ok = True
        observed["governance_canonical_action_schema"] = canonical_governance_ok
        observed["governance_authority_matrix_fail_closed"] = governance_ok
        observed["governance_email_policy_bounded"] = email_gate_ok
        observed["governance_no_inherited_authority"] = inheritance_ok
        observed["governance_project_caps_bounded"] = project_caps_ok
        if not governance_ok:
            findings.append(finding(
                "ADAPTER_WRITE_AUTHORITY", "HIGH", "GOVERNANCE_AUTHORITY_MATRIX_NOT_FAIL_CLOSED",
                "Governance must be deny-by-default, human-gate high-risk actions, prohibit live trading, bound the explicit Gmail policy exception, and prevent downstream deploy/external-action authority.",
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
    observed["chatgpt_gmail_customer_email_gateway_present"] = gmail_act
    observed["chatgpt_gmail_customer_email_policy_bounded"] = canonical_email_gate_ok
    if gmail_act and not canonical_email_gate_ok:
        findings.append(finding(
            "ADAPTER_WRITE_AUTHORITY", "HIGH", "CHATGPT_GMAIL_CUSTOMER_EMAIL_AUTHORITY_PRESENT",
            "ChatGPT Gmail customer-email execution exists without the reviewed bounded action policy, sanitized persistence, kill switch, and prohibited-action set.",
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

    return report(c, observed, findings, False, STATIC_REVIEW_DOMAINS)


def live_review(evidence: dict[str, Any], expected_main_sha: str) -> dict[str, Any]:
    c = contract(ROOT)
    findings: list[dict[str, str]] = []
    observed: dict[str, Any] = {}

    if SHA40.fullmatch(expected_main_sha) is None:
        raise SecurityReviewError("expected main SHA invalid")
    main_ok = evidence.get("observed_main_sha") == expected_main_sha
    observed["expected_main_sha"] = expected_main_sha
    observed["observed_main_sha"] = evidence.get("observed_main_sha")
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
        conditions = ruleset.get("conditions")
        ref_name = conditions.get("ref_name") if isinstance(conditions, dict) else None
        includes = ref_name.get("include") if isinstance(ref_name, dict) else None
        excludes = ref_name.get("exclude") if isinstance(ref_name, dict) else None
        main_ref_covered = (
            isinstance(includes, list)
            and isinstance(excludes, list)
            and "refs/heads/main" in includes
            and all(
                isinstance(pattern, str)
                and pattern not in {"~ALL", "~DEFAULT_BRANCH"}
                and not fnmatchcase("refs/heads/main", pattern)
                for pattern in excludes
            )
        )
        rules_ok = (
            ruleset.get("enforcement") == "active"
            and ruleset.get("target") == "branch"
            and main_ref_covered
            and {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= types
            and strict
            and ("validate", 15368) in identities
            and ("portfolio-phase1-gate", 5121826) in identities
            and ruleset.get("bypass_actors") == []
            and ruleset.get("current_user_can_bypass") == "never"
        )
        observed["ruleset_covers_main"] = main_ref_covered
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
        source_head_sha = app.get("source_head_sha")
        source_merge_sha = app.get("source_merge_sha")
        source_check_run_id = app.get("source_check_run_id")
        source_pr_number = app.get("source_pr_number")
        source_binding_ok = (
            isinstance(source_head_sha, str)
            and SHA40.fullmatch(source_head_sha) is not None
            and source_merge_sha == expected_main_sha
            and type(source_check_run_id) is int
            and source_check_run_id > 0
            and type(source_pr_number) is int
            and source_pr_number > 0
            and app.get("source_check_name") == "portfolio-phase1-gate"
            and app.get("source_check_conclusion") == "success"
        )
        app_ok = (
            app.get("id") == 5121826
            and app.get("slug") == "portfolio-brain-522"
            and app.get("permissions") == ALLOWED_VERIFIER_PERMISSIONS
            and app.get("events") == []
            and source_binding_ok
        )
        observed["verifier_app_scope_exact"] = app_ok
        observed["verifier_app_source_binding"] = source_binding_ok
        observed["verifier_app_slug"] = app.get("slug")
        observed["verifier_app_events"] = app.get("events")
        observed["verifier_app_source_head_sha"] = source_head_sha
        observed["verifier_app_source_merge_sha"] = source_merge_sha
        observed["verifier_app_source_check_run_id"] = source_check_run_id
        observed["verifier_app_source_pr_number"] = source_pr_number
        if not app_ok:
            findings.append(finding(
                "VERIFIER_APP_SCOPES", "CRITICAL", "VERIFIER_APP_SCOPE_WIDENED",
                "Verifier App identity/scope or protected-merge source binding does not match the reviewed set.",
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
            and isinstance(artifact.get("provider_digest"), str)
            and SHA256.fullmatch(artifact["provider_digest"]) is not None
            and isinstance(artifact.get("downloaded_zip_digest"), str)
            and SHA256.fullmatch(artifact["downloaded_zip_digest"]) is not None
            and artifact["provider_digest"] == artifact["downloaded_zip_digest"]
            and artifact.get("expired") is False
        )
        observed["artifact_exact_run_head_digest_traceable"] = artifact_ok
        if not artifact_ok:
            findings.append(finding(
                "ARTIFACT_TAMPER_RESISTANCE", "CRITICAL", "ARTIFACT_IDENTITY_UNTRACEABLE",
                "Artifact evidence must bind exact run/head/id, remain unexpired, and match provider-reported SHA-256 to downloaded ZIP bytes.",
                "live.artifact_probe",
            ))

    return report(c, observed, findings, True, LIVE_REVIEW_DOMAINS)


def combine(static: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    c = contract(ROOT)
    findings = list(static.get("findings", []))
    observed = {"static": static.get("observed", {})}
    covered_domains = set(static.get("covered_domains", []))
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
        covered_domains.update(live.get("covered_domains", []))
        live_present = True
    missing_domains = sorted(set(c["required_domains"]) - covered_domains)
    for domain in missing_domains:
        findings.append(finding(
            domain, "UNKNOWN", "REQUIRED_DOMAIN_EVIDENCE_MISSING",
            "Required Step 24 security domain has no explicit reviewer coverage.",
            f"coverage:{domain}",
        ))
    observed["required_domain_coverage"] = {
        "required": c["required_domains"],
        "covered": sorted(covered_domains),
        "missing": missing_domains,
    }
    return report(c, observed, findings, live_present, covered_domains)


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
