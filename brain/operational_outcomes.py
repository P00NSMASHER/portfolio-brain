"""Bounded original-provider workflow measurements, separate from acceptance.

Only public technical metadata is retained. Workflow conclusions do not measure
uptime, useful repairs, customer activity or revenue. No canonical state writes.
"""
from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import quote

from brain.core import digest, require

PROJECTS = {
    'portfolio-brain': 'P00NSMASHER/portfolio-brain',
    'abvm': 'P00NSMASHER/abvmschoolstarworld',
    'retally': 'P00NSMASHER/github-value-hunt-ledger',
    'product-factory': 'P00NSMASHER/x402-product-factory',
}
MAX_REQUESTS = 24
MAX_PAGES = 3
ADVERSE = frozenset({'failure', 'cancelled', 'timed_out', 'action_required',
                     'startup_failure', 'stale'})
CONCLUSIONS = ADVERSE | {'success', 'neutral', 'skipped'}
STATUSES = {'queued', 'in_progress', 'completed', 'waiting', 'pending', 'requested'}
EVENTS = {'push', 'schedule', 'workflow_dispatch', 'repository_dispatch',
          'workflow_run', 'pull_request', 'pull_request_target'}
SHA = re.compile(r'[0-9a-f]{40}\Z')


def _time(value):
    require(type(value) is str and re.fullmatch(
        r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z',
        value), 'OUTCOME_UTC_REQUIRED')
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as exc:
        from brain.core import BrainError
        raise BrainError('OUTCOME_TIME_INVALID') from exc


def collect_outcomes(get, project_ids, *, started_at, ended_at):
    """GET callback receives allowlisted repository and constructed suffix only.

    A caller-supplied fixture is not authenticated provider evidence. Live use
    must use the bundled transport or independently validate the response bytes.
    """
    require(type(project_ids) is list and 1 <= len(project_ids) <= 4
            and all(type(p) is str and p in PROJECTS for p in project_ids)
            and len(set(project_ids)) == len(project_ids), 'OUTCOME_PROJECT_SCOPE')
    start, end = _time(started_at), _time(ended_at)
    require(0 < (end - start).total_seconds() <= 7 * 86400, 'OUTCOME_WINDOW_INVALID')
    requests = 0

    def read(repo, path):
        nonlocal requests
        require(requests < MAX_REQUESTS, 'OUTCOME_REQUEST_BUDGET')
        requests += 1
        response = get(repo, path)
        require(type(response) is dict, 'OUTCOME_PROVIDER_NOT_OBJECT')
        return response

    def head(repo):
        result = read(repo, '/branches/main')
        require(type(result.get('commit')) is dict, 'OUTCOME_MAIN_IDENTITY')
        sha = result['commit'].get('sha')
        require(result.get('name') == 'main' and type(sha) is str
                and SHA.fullmatch(sha), 'OUTCOME_MAIN_IDENTITY')
        return sha

    projects = []
    query = quote(started_at + '..' + ended_at, safe='')
    for project in project_ids:
        repo = PROJECTS[project]
        source = head(repo)
        rows, total = [], None
        page_digests = []
        for page in range(1, MAX_PAGES + 1):
            suffix = ('/actions/runs?branch=main&per_page=100'
                      f'&page={page}&created={query}')
            document = read(repo, suffix)
            count, values = document.get('total_count'), document.get('workflow_runs')
            require(type(count) is int and 0 <= count <= MAX_PAGES * 100,
                    'OUTCOME_INVENTORY_BOUND')
            require(total is None or total == count, 'OUTCOME_INVENTORY_CHANGED')
            total = count
            require(type(values) is list and len(values) == min(100, total-len(rows)),
                    'OUTCOME_PAGE_INCOMPLETE')
            page_digests.append({'source_ref': 'https://api.github.com/repos/' + repo + suffix,
                                 'canonical_response_sha256': digest(document)})
            rows.extend(values)
            if len(rows) == total:
                break
        require(len(rows) == total, 'OUTCOME_INVENTORY_INCOMPLETE')
        require(head(repo) == source, 'OUTCOME_SOURCE_CHANGED')
        seen, evidence, retries = set(), [], []
        success = adverse = pending = inconclusive = excluded = 0
        for row in rows:
            require(type(row) is dict and type(row.get('id')) is int
                    and row['id'] > 0 and row['id'] not in seen,
                    'OUTCOME_RUN_IDENTITY')
            seen.add(row['id'])
            require(type(row.get('head_sha')) is str and SHA.fullmatch(row['head_sha'])
                    and row.get('head_branch') == 'main'
                    and type(row.get('path')) is str
                    and re.fullmatch(r'\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml', row['path'])
                    and row.get('event') in EVENTS
                    and start <= _time(row.get('created_at')) <= end,
                    'OUTCOME_RUN_SCOPE')
            attempt = row.get('run_attempt')
            status, conclusion = row.get('status'), row.get('conclusion')
            require(type(attempt) is int and attempt >= 1 and status in STATUSES
                    and ((status == 'completed' and conclusion in CONCLUSIONS)
                         or (status != 'completed' and conclusion is None)),
                    'OUTCOME_RUN_RESULT_INVALID')
            # Pull-request CI is not production-main operational evidence.
            if row['event'] in {'pull_request', 'pull_request_target'}:
                excluded += 1
                continue
            if attempt > 1:
                retries.append(row['id'])
            elif status != 'completed':
                pending += 1
            elif conclusion == 'success':
                success += 1
            elif conclusion in ADVERSE:
                adverse += 1
            else:
                inconclusive += 1
            evidence.append({
                'run_id': row['id'], 'source_sha': row['head_sha'],
                'workflow_path': row['path'], 'event': row['event'],
                'status': status, 'conclusion': conclusion, 'run_attempt': attempt,
                'created_at': row['created_at'],
                'source_ref': f'https://github.com/{repo}/actions/runs/{row["id"]}',
            })
        denominator = success + adverse
        projects.append({
            'project_id': project, 'repository': repo, 'current_main_sha': source,
            'evidence_status': ('NO_RUNS_OBSERVED' if not evidence else
                                'ATTEMPT_CENSUS_REQUIRED' if retries else
                                'PROVIDER_WORKFLOW_METADATA_OBSERVED'),
            'run_inventory_complete': True, 'attempt_history_complete': not retries,
            'successful_terminal_runs': success, 'adverse_terminal_runs': adverse,
            'pending_runs': pending, 'inconclusive_runs': inconclusive,
            'excluded_pr_runs': excluded, 'rerun_ids_needing_attempt_census': retries,
            'terminal_success_fraction': success / denominator if denominator and not retries else None,
            'production_uptime': None, 'successful_live_repairs': None,
            'verified_revenue': None, 'source_pages': page_digests,
            'runs': sorted(evidence, key=lambda r: (r['created_at'], r['run_id'])),
        })
    signals = []
    for project in projects:
        grouped = {}
        for row in project['runs']:
            if row['status'] == 'completed' and row['conclusion'] in ADVERSE:
                grouped.setdefault(row['workflow_path'], []).append(row['source_ref'])
        for path, refs in grouped.items():
            signals.append({
                'project_id': project['project_id'], 'repository': project['repository'],
                'workflow_path': path, 'adverse_terminal_runs': len(refs),
                'original_run_refs': refs, 'root_cause_verified': False,
                'attempt_history_complete': project['attempt_history_complete'],
                'next_operation': 'DIAGNOSE_ORIGINAL_JOBS_AND_ARTIFACTS',
                'customer_value': None,
            })
    signals.sort(key=lambda s: (-s['adverse_terminal_runs'], s['project_id'], s['workflow_path']))
    return {
        'schema_version': 1, 'scope': 'WORKFLOW_OUTCOMES_NOT_UPTIME_OR_BUSINESS_VALUE',
        'started_at': started_at, 'ended_at': ended_at, 'projects': projects,
        'requests': requests, 'priority_signals': signals,
        'provider_authentication': 'CALLER_TRANSPORT_NOT_SELF_CERTIFIED',
        'production_accepted': False, 'authority_to_merge_deploy_pay_or_contact': False,
    }


def main(argv=None):
    """Explicit read-only owner operation; never changes existing schedules."""
    import argparse
    import json
    from pathlib import Path
    from brain.adapters import GitHub
    from brain.render import write_report
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', action='append', choices=sorted(PROJECTS), required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    api = GitHub()
    report = collect_outcomes(lambda repo, path: api.get('/repos/' + repo + path),
                              args.project, started_at=args.start, ended_at=args.end)
    report['provider_authentication'] = 'ORIGINAL_GITHUB_HTTPS_GET_NOT_INDEPENDENT_ACCEPTANCE'
    report['transport_requests_including_retries'] = api.requests
    write_report(report, args.output)
    print(json.dumps({'status': 'READ_ONLY_WORKFLOW_MEASUREMENTS_COLLECTED',
                      'projects': len(report['projects']), 'requests': api.requests,
                      'production_accepted': False, 'verified_revenue': None}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
