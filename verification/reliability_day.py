"""Read-only 24-hour observation; no independent release authority."""
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
from soak_v3.remote_probe import GitHubReadOnly
from verification.source_acceptance_verifier import collect_original_runs, req, utc, _zip_json

CORE = '/actions/workflows/brain-cycle.yml/runs?branch=main&per_page=100'


def evaluate(summary):
    req(summary['maximum_gap'] <= 5400, 'automatic cycle gap exceeded')
    return {'status': 'PASS' if summary['span'] >= 86400 else 'COLLECTING',
            'completed_span_seconds': summary['span'], 'required_span_seconds': 86400,
            'maximum_gap_seconds': summary['maximum_gap'], 'independent_release_authority': False}


def inventory(api, path):
    rows = []
    total = None
    for page in range(1, 11):
        doc = api.json(path + '&page=' + str(page))
        req(type(doc.get('total_count')) is int and type(doc.get('workflow_runs')) is list,
            'invalid run inventory')
        if total is None:
            total = doc['total_count']
        req(total == doc['total_count'], 'run inventory moved')
        rows.extend(doc['workflow_runs'])
        req(len({row['id'] for row in rows}) == len(rows), 'duplicate inventory run')
        if len(rows) == total:
            return rows
        req(len(rows) < total and len(doc['workflow_runs']) == 100, 'incomplete run inventory')
    raise RuntimeError('RUN_INVENTORY_CAPACITY_EXCEEDED')


def window(rows, source):
    selected = sorted((r for r in rows if r.get('head_sha') == source), key=lambda r: r['created_at'])
    req(selected, 'source runs absent')
    completed = []
    first = None
    for row in selected:
        created = utc(row['created_at']) if first is not None else None
        # The receipt is a fixed first-24.5-hour snapshot. A later run cannot
        # retroactively change that already bounded evidence window.
        if first is not None and (created - first).total_seconds() > 88200:
            break
        if row.get('status') != 'completed':
            break
        req(row.get('conclusion') == 'success' and row.get('run_attempt') == 1,
            'original core failed or retried')
        completed.append(row)
        if row.get('event') in {'schedule', 'workflow_dispatch'}:
            if first is None:
                first = utc(row['created_at'])
                created = first
            # Include a boundary cycle at exactly 24.5h; the collector uses
            # job completion times to establish the required 24-hour span.
            if (created - first).total_seconds() >= 88200:
                break
    return completed


class Snapshot:
    def __init__(self, api, rows):
        self.api, self.rows = api, rows
    def json(self, path):
        if path == CORE:
            return {'total_count': len(self.rows), 'workflow_runs': self.rows}
        return self.api.json(path)
    def get(self, *args, **kwargs):
        return self.api.get(*args, **kwargs)


def verify_repairs(api, rows, source, core_ids, cutoff=None):
    seen = set()
    for row in rows:
        if cutoff is not None and utc(row['created_at']) > cutoff:
            continue
        if row.get('head_sha') != source or row.get('conclusion') == 'skipped':
            continue
        if row.get('status') != 'completed':
            continue
        req(row.get('conclusion') == 'success' and row.get('run_attempt') == 1,
            'original scheduled repair failed or retried')
        doc = api.json(f"/actions/runs/{row['id']}/artifacts?per_page=100")
        artifacts = doc.get('artifacts', [])
        req(doc.get('total_count') == 1 and len(artifacts) == 1, 'repair artifact census invalid')
        item = artifacts[0]
        req(item.get('expired') is False and item.get('workflow_run', {}).get('id') == row['id']
            and item.get('workflow_run', {}).get('head_sha') == source, 'repair artifact identity invalid')
        raw = api.get(f"/actions/artifacts/{item['id']}/zip", limit=20_000_000)
        req(item.get('digest') == 'sha256:' + hashlib.sha256(raw).hexdigest(), 'repair digest invalid')
        receipt = _zip_json(raw, 'v8-origin.json')
        req(receipt.get('source_sha') == source and receipt.get('status') == 'ORIGINAL_AUTOMATIC_CORE_AUTHENTICATED',
            'repair origin invalid')
        core = int(receipt['run_id'])
        if core in core_ids:
            req(core not in seen, 'duplicate repair origin')
            seen.add(core)
    return seen == core_ids


def main():
    source = os.environ['SOURCE_SHA']
    api = GitHubReadOnly(os.environ['GITHUB_TOKEN'], max_calls=656)
    req(api.json('/branches/main')['commit']['sha'] == source, 'source moved')
    rows = window(inventory(api, CORE + "&head_sha=" + source), source)
    result = {'status': 'COLLECTING', 'source_sha': source, 'independent_release_authority': False}
    if sum(row.get('event') in {'schedule', 'workflow_dispatch'} for row in rows) >= 2:
        summary = collect_original_runs(Snapshot(api, rows), source)
        result.update(evaluate(summary), qualifying_cores=len(summary['automatic']),
                      first_run_id=summary['automatic'][0]['id'], terminal_run_id=summary['terminal']['id'])
        repairs = inventory(api, '/actions/workflows/v8-scoped-repair.yml/runs?branch=main&per_page=100&head_sha=' + source)
        complete = verify_repairs(api, repairs, source, {r['id'] for r in summary['automatic']},
                                  cutoff=summary['terminal']['completed'] + timedelta(minutes=30))
        if not complete:
            result.update(status='COLLECTING', reason='REPAIR_FOLLOW_THROUGH_PENDING')
    req(api.json('/branches/main')['commit']['sha'] == source, 'source moved')
    Path('reliability-day.json').write_text(json.dumps(result, sort_keys=True)+'\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
