"""Prepare an integration verdict from fresh provider metadata, without merging.

This must run in an independently controlled verifier, not candidate code. The
checked-in configuration intentionally has no trusted gate App or reviewer:
issue #65 must establish those identities and repository enforcement first.
"""
from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from verification.evidence import EvidenceError, GitHubArtifactResolver, digest, exact_sha, require
from verification.protection import inspect_main_protection
from value_proof.strict_json import strict_json_loads

POLICY_PATH = Path(__file__).with_name('RELEASE_GATE_POLICY.json')


def verify_release(repository: str, pr_number: int, expected_head: str, *,
                   gate_app_id: int | None = None, policy: dict[str, Any] | None = None,
                   get_json=None) -> dict[str, Any]:
    """Read-only verdict; candidate JSON is never accepted as provider metadata."""
    p = deepcopy(policy) if policy is not None else strict_json_loads(POLICY_PATH.read_text())
    require(set(p) == {'schema_version','trusted_gate_app_id','gate_check_name','approved_reviewer_ids','required_checks'}, 'release policy schema mismatch')
    require(p['schema_version'] == '2.0.0', 'release policy version mismatch')
    require(type(p['trusted_gate_app_id']) is int and p['trusted_gate_app_id'] > 0, 'independent gate App is not configured')
    require(type(gate_app_id) is int and gate_app_id == p['trusted_gate_app_id'], 'gate issuer is not approved')
    require(isinstance(p['approved_reviewer_ids'], list) and p['approved_reviewer_ids'] and all(type(i) is int and i > 0 for i in p['approved_reviewer_ids']), 'independent reviewer is not configured')
    require(isinstance(p['required_checks'], list) and p['required_checks'], 'required checks missing')
    require(isinstance(p['gate_check_name'], str) and p['gate_check_name'], 'gate check name missing')
    for spec in p['required_checks']:
        require(isinstance(spec, dict) and set(spec) == {'name','app_id','workflow_id','workflow_path','job_name','required_steps'}, 'check policy schema mismatch')
        require(type(spec['app_id']) is int and spec['app_id'] > 0 and type(spec['workflow_id']) is int and spec['workflow_id'] > 0, 'invalid check identity')
        require(all(isinstance(spec[k], str) and spec[k] for k in ('name','workflow_path','job_name')), 'check names required')
        steps = spec['required_steps']
        require(isinstance(steps,list) and steps and all(isinstance(n,str) and n for n in steps) and len(set(steps)) == len(steps), 'invalid required step list')
    require(len({c['name'] for c in p['required_checks']}) == len(p['required_checks']), 'duplicate check policy')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) is not None, 'invalid repository')
    require(type(pr_number) is int and pr_number > 0 and exact_sha(expected_head), 'PR identity invalid')
    api = get_json or GitHubArtifactResolver()._get_json
    base = 'https://api.github.com/repos/' + repository
    pr = api(f'{base}/pulls/{pr_number}')
    require(pr.get('state') == 'open' and pr.get('draft') is False, 'PR not open and ready')
    require(pr.get('head', {}).get('repo', {}).get('full_name') == repository, 'fork requires separate trust policy')
    require(pr.get('base', {}).get('repo', {}).get('full_name') == repository, 'PR target repository mismatch')
    require(pr['head'].get('sha') == expected_head, 'PR head changed')
    main = api(f'{base}/branches/main')
    base_sha = main.get('commit', {}).get('sha')
    require(exact_sha(base_sha) and pr.get('base', {}).get('sha') == base_sha and pr['base'].get('ref') == 'main', 'candidate not tested against current main')
    # pr.base.sha is only the current target; it does not prove ancestry.
    comparison = api(f'{base}/compare/{base_sha}...{expected_head}')
    require(comparison.get('base_commit', {}).get('sha') == base_sha
            and comparison.get('merge_base_commit', {}).get('sha') == base_sha
            and type(comparison.get('behind_by')) is int and comparison['behind_by'] == 0
            and comparison.get('status') in {'ahead', 'identical'}, 'candidate does not contain current main')
    # Required workflow definitions are part of the trusted base. Candidate code
    # may change application/tests, but it cannot rewrite the gate-producing
    # workflow and then use that rewritten workflow as its own evidence.
    for spec in p['required_checks']:
        base_workflow = api(f"{base}/contents/{spec['workflow_path']}?ref={base_sha}")
        head_workflow = api(f"{base}/contents/{spec['workflow_path']}?ref={expected_head}")
        require(base_workflow.get('type') == 'file' and head_workflow.get('type') == 'file', 'required workflow file missing')
        require(isinstance(base_workflow.get('sha'), str) and base_workflow['sha'] == head_workflow.get('sha'), 'required workflow changed in candidate')
    protection = inspect_main_protection(repository,
        [{'name': c['name'], 'app_id': c['app_id']} for c in p['required_checks']],
        gate_app_id=gate_app_id, gate_check_name=p['gate_check_name'], get_json=api)
    require(protection['main_sha'] == base_sha and protection['status'] == 'CONFIGURATION_OBSERVED', 'required live protection is missing')
    # The independent gate cannot double as the candidate-controlled CI issuer.
    require(all(c.get('app_id') != gate_app_id for c in p['required_checks']), 'gate and candidate CI must have separate principals')
    data = api(f'{base}/commits/{expected_head}/check-runs?filter=latest&per_page=100')
    checks = data.get('check_runs', [])
    require(data.get('total_count') == len(checks) and len(checks) < 100, 'check coverage incomplete')
    evidence = []
    for spec in p['required_checks']:
        require(set(spec) == {'name','app_id','workflow_id','workflow_path','job_name','required_steps'}, 'check policy schema mismatch')
        require(type(spec['app_id']) is int and type(spec['workflow_id']) is int and spec['required_steps'], 'trusted check identity/steps missing')
        candidates = [c for c in checks if c.get('name') == spec['name']]
        require(len(candidates) == 1, 'required check missing or ambiguous')
        check = candidates[0]
        require(check.get('head_sha') == expected_head and check.get('app', {}).get('id') == spec['app_id'], 'untrusted/stale check')
        require(check.get('status') == 'completed' and check.get('conclusion') == 'success', 'required check skipped, neutral, cancelled or failed')
        match = re.fullmatch(r'https://github\.com/' + re.escape(repository) + r'/actions/runs/(\d+)(?:/job/(\d+))?',check.get('details_url',''))
        require(match is not None, 'required check lacks provider run link')
        run_id = int(match.group(1))
        run = api(f'{base}/actions/runs/{run_id}')
        require(run.get('id') == run_id and run.get('head_sha') == expected_head and run.get('workflow_id') == spec['workflow_id'] and run.get('path') == spec['workflow_path'], 'run/workflow/revision mismatch')
        require(run.get('status') == 'completed' and run.get('conclusion') == 'success', 'required run did not succeed')
        require(type(run.get('run_attempt')) is int and run['run_attempt'] > 0, 'run attempt missing')
        require(run.get('repository', {}).get('full_name') == repository and run.get('head_repository', {}).get('full_name') == repository, 'run repository/fork mismatch')
        jobs_data = api(f'{base}/actions/runs/{run_id}/jobs?filter=latest&per_page=100')
        jobs = jobs_data.get('jobs', [])
        require(jobs_data.get('total_count') == len(jobs) and len(jobs) < 100, 'job coverage incomplete')
        matches = [j for j in jobs if j.get('name') == spec['job_name']]
        require(len(matches) == 1 and matches[0].get('head_sha') == expected_head and matches[0].get('conclusion') == 'success', 'required job missing/stale/failed')
        job = matches[0]
        require(job.get('run_id') == run_id and job.get('run_attempt') == run['run_attempt']
                and job.get('status') == 'completed', 'job belongs to wrong run/attempt')
        require(job.get('check_run_url') == f"{base}/check-runs/{check['id']}", 'job is not the required check')
        require(match.group(2) is None or int(match.group(2)) == job['id'], 'check details link identifies another job')
        for step_name in spec['required_steps']:
            steps = [s for s in job.get('steps', []) if s.get('name') == step_name]
            require(len(steps) == 1 and steps[0].get('status') == 'completed' and steps[0].get('conclusion') == 'success', 'required step did not actually succeed')
        evidence.append({'check_id':check['id'], 'run_id':run_id, 'job_id':job['id'], 'run_attempt':run['run_attempt']})
    reviews_url = f'{base}/pulls/{pr_number}/reviews?per_page=100'
    reviews = api(reviews_url)
    def approved_ids(rows):
        require(isinstance(rows,list) and len(rows) < 100, 'review coverage incomplete')
        latest = {}
        for review in sorted(rows, key=lambda r:r['id']):
            if review.get('state') in {'APPROVED','CHANGES_REQUESTED','DISMISSED'}:
                latest[review.get('user',{}).get('id')] = review
        require(not any(r.get('state') == 'CHANGES_REQUESTED' for r in latest.values()), 'unresolved change request')
        author = pr.get('user', {}).get('id')
        approved = [r['id'] for uid,r in latest.items() if uid in p['approved_reviewer_ids'] and uid != author and r.get('state') == 'APPROVED' and r.get('commit_id') == expected_head]
        require(bool(approved), 'current-head independent approval missing')
        return sorted(approved)
    review_ids = approved_ids(reviews)
    # Re-read mutable prerequisites. GitHub must still enforce the real merge;
    # a read-only observation is not an atomic authorization or bypass token.
    require(approved_ids(api(reviews_url)) == review_ids, 'review changed during verification')
    fresh_data = api(f'{base}/commits/{expected_head}/check-runs?filter=latest&per_page=100')
    fresh_checks = fresh_data.get('check_runs', [])
    require(fresh_data.get('total_count') == len(fresh_checks) and len(fresh_checks) < 100, 'final check coverage incomplete')
    required_names = {c['name'] for c in p['required_checks']}
    normalize = lambda items: sorted([c for c in items if c.get('name') in required_names], key=lambda c:c['id'])
    require(digest(normalize(fresh_checks)) == digest(normalize(checks)), 'required checks changed during verification')
    for item in evidence:
        run = api(f"{base}/actions/runs/{item['run_id']}")
        require(run.get('run_attempt') == item['run_attempt'] and run.get('status') == 'completed' and run.get('conclusion') == 'success' and run.get('head_sha') == expected_head, 'run changed during verification')
    latest_protection = inspect_main_protection(repository,
        [{'name': c['name'], 'app_id': c['app_id']} for c in p['required_checks']],
        gate_app_id=gate_app_id, gate_check_name=p['gate_check_name'], get_json=api)
    require(digest(latest_protection) == digest(protection), 'protection changed during verification')
    final_pr = api(f'{base}/pulls/{pr_number}')
    require(final_pr.get('state') == 'open' and final_pr.get('draft') is False, 'PR closed or returned to draft')
    require(final_pr.get('head', {}).get('sha') == expected_head, 'head changed during verification')
    require(final_pr.get('base', {}).get('sha') == base_sha and final_pr['base'].get('ref') == 'main'
            and final_pr['base'].get('repo', {}).get('full_name') == repository, 'PR target changed during verification')
    require(api(f'{base}/branches/main')['commit']['sha'] == base_sha, 'base changed during verification')
    body={'schema_version':'2.0.0','status':'EVIDENCE_VALIDATED_NOT_MERGED','repository':repository,'pr_number':pr_number,'head_sha':expected_head,'base_sha':base_sha,'gate_app_id':gate_app_id,'policy_hash':digest(p),'check_evidence':evidence,'review_ids':review_ids, 'protection_observation':protection, 'enforcement_tested':False,'merge_performed':False,'authority_granted':False}
    return {**body,'receipt_hash':digest(body)}
