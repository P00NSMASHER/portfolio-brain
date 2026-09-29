"""Read-only ruleset preflight; configuration is not an enforcement test.

Only effective repository-level rulesets are supported in this Phase 1 path.
Classic protection and inherited org rules require a separately reviewed adapter.
Missing coverage/permissions block; an omitted bypass list is UNKNOWN, not empty.
No credentials, protection updates, check publication, or merge are performed.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from value_proof.strict_json import strict_json_loads
from verification.evidence import canonical, digest, exact_sha, require

DEFAULT_GATE_CHECK = "portfolio-phase1-gate"


def public_get_json(url: str) -> Any:
    """Public read only. Never inspect the environment for credentials."""
    require(re.fullmatch(r"https://api\.github\.com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[^\s]+", url) is not None, "unsupported metadata URL")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            return None
    request = urllib.request.Request(url, headers={
        "User-Agent": "portfolio-brain-protection-preflight",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        body = response.read(2_000_001)
    require(len(body) <= 2_000_000, "metadata response exceeds bound")
    return strict_json_loads(body.decode("utf-8"))


def _effective_rules(base: str, api: Callable[[str], Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 11):
        batch = api(f"{base}/rules/branches/main?per_page=100&page={page}")
        require(isinstance(batch, list) and len(batch) <= 100, "effective rules response invalid")
        require(all(isinstance(row, dict) for row in batch), "effective rule must be an object")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise ValueError("effective rules pagination bound exceeded")


def inspect_main_protection(repository: str, required_checks: list[dict[str, Any]], *,
                            gate_app_id: int | None,
                            gate_check_name: str = DEFAULT_GATE_CHECK,
                            get_json=None) -> dict[str, Any]:
    """Return a bounded observation; this does not prove a rejected write.

    get_json and policy arguments are trusted-orchestrator inputs, not PR inputs.
    bypass_actors may be hidden from read-only callers by GitHub. Visibility is
    reported separately and never silently upgraded to a verified empty list.
    """
    require(isinstance(repository, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None, "invalid repository")
    require(isinstance(gate_check_name, str) and bool(gate_check_name.strip()), "gate check name required")
    require(isinstance(required_checks, list) and required_checks, "CI check specification required")
    for spec in required_checks:
        require(isinstance(spec, dict) and set(spec) == {"name", "app_id"}, "protection check specification invalid")
        require(isinstance(spec["name"], str) and spec["name"] and type(spec["app_id"]) is int and spec["app_id"] > 0, "trusted CI identity required")
    require(len({s['name'] for s in required_checks}) == len(required_checks), "duplicate required check name")
    require(gate_check_name not in {s['name'] for s in required_checks}, "gate cannot masquerade as candidate CI")
    require(gate_app_id is None or (type(gate_app_id) is int and gate_app_id > 0), "invalid gate issuer")
    api = get_json or public_get_json
    base = f"https://api.github.com/repos/{repository}"
    branch = api(f"{base}/branches/main")
    head = branch.get("commit", {}).get("sha")
    require(exact_sha(head), "main revision unavailable")
    rules = _effective_rules(base, api)
    require(len({canonical(r) for r in rules}) == len(rules), "duplicate effective rule rows")
    details: dict[int, dict[str, Any]] = {}
    for rule in rules:
        rid = rule.get("ruleset_id")
        require(type(rid) is int and rid > 0, "effective ruleset identity missing")
        require(rule.get("ruleset_source_type") == "Repository" and rule.get("ruleset_source") == repository, "unsupported inherited ruleset source; manual verification required")
        if rid not in details:
            detail = api(f"{base}/rulesets/{rid}")
            require(detail.get("id") == rid and detail.get("source") == repository and detail.get("source_type") == "Repository", "ruleset identity mismatch")
            require(detail.get("target") == "branch" and detail.get("enforcement") == "active", "ruleset not actively enforced")
            require(isinstance(detail.get("rules"), list), "ruleset body incomplete")
            # Details can hide bypass actors. Never infer an empty list from that.
            if "bypass_actors" in detail:
                require(isinstance(detail['bypass_actors'], list), "invalid bypass data")
            details[rid] = detail
        projected = {k: v for k, v in rule.items() if k not in {"ruleset_id", "ruleset_source", "ruleset_source_type"}}
        require(any(canonical(projected) == canonical(r) for r in details[rid]['rules']), "effective rule and ruleset details disagree")
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in rules:
        by_type.setdefault(row.get("type", ""), []).append(row.get("parameters", {}))
    criteria = {
        "branch_reported_protected": branch.get("protected") is True,
        "active_rules_present": bool(rules),
        "block_deletion": bool(by_type.get("deletion")),
        "block_force_push": bool(by_type.get("non_fast_forward")),
        "pull_request_required": any(
            type(p.get("required_approving_review_count")) is int
            and p["required_approving_review_count"] == 0
            and p.get("required_review_thread_resolution") is True
            for p in by_type.get("pull_request", [])
        ),
        "gate_issuer_configured": gate_app_id is not None,
    }
    for spec in [*required_checks, {"name": gate_check_name, "app_id": gate_app_id}]:
        criteria[f"check:{spec['name']}"] = spec['app_id'] is not None and any(
            p.get('strict_required_status_checks_policy') is True
            and any(c.get('context') == spec['name']
                    and type(c.get('integration_id')) is int
                    and c['integration_id'] == spec['app_id']
                    for c in p.get('required_status_checks', []) if isinstance(c, dict))
            for p in by_type.get('required_status_checks', [])
        )
    # An observed explicit bypass is a blocker. Omitted data remains unknown.
    visible_bypass = any(bool(d.get('bypass_actors')) for d in details.values())
    bypass_known = bool(details) and all('bypass_actors' in d for d in details.values())
    criteria['no_visible_bypass'] = not visible_bypass
    final = api(f"{base}/branches/main")
    require(final.get('commit', {}).get('sha') == head and final.get('protected') == branch.get('protected'), "main changed during protection observation")
    require(canonical(_effective_rules(base, api)) == canonical(rules), "active rules changed during observation")
    for rid, detail in details.items():
        current = api(f"{base}/rulesets/{rid}")
        require(canonical(current) == canonical(detail), "ruleset changed during observation")
    body = {
        'schema_version': '1.0.0', 'repository': repository, 'branch': 'main',
        'main_sha': head, 'criteria': criteria,
        'status': 'CONFIGURATION_OBSERVED' if all(criteria.values()) else 'BLOCKED',
        'missing': [k for k, v in criteria.items() if not v],
        'bypass_visibility': 'VISIBLE_NONEMPTY' if visible_bypass else ('VISIBLE_EMPTY' if bypass_known else 'UNKNOWN'),
        'ruleset_ids': sorted(details), 'rules_hash': digest(rules),
        'ruleset_details_hash': digest(details),
        'enforcement_tested': False, 'production_accepted': False,
        'mutation_capability': 'NONE',
    }
    return {**body, 'observation_hash': digest(body)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default='P00NSMASHER/portfolio-brain')
    parser.add_argument('--gate-app-id', type=int)
    parser.add_argument('--gate-check-name', default=DEFAULT_GATE_CHECK)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = inspect_main_protection(args.repository, [{'name': 'validate', 'app_id': 15368}],
                                         gate_app_id=args.gate_app_id, gate_check_name=args.gate_check_name)
        report['observed_at'] = datetime.now(timezone.utc).isoformat()
        code = 0 if report['status'] == 'CONFIGURATION_OBSERVED' else 2
    except Exception as exc:
        # Do not expose exception URLs, provider bodies, credentials, or filenames.
        report = {'status': 'BLOCKED', 'reason': 'PROTECTION_READ_OR_VALIDATION_FAILED',
                  'error_type': type(exc).__name__, 'production_accepted': False,
                  'mutation_capability': 'NONE'}
        code = 2
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
