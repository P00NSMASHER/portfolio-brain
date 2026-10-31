"""Read-only 12-hour observation; no independent release authority."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from soak_v3.remote_probe import GitHubReadOnly
from verification.source_acceptance_verifier import collect_original_runs, req, utc, _zip_json
from verification.owner_observation_window import activation, post_activation

CORE = '/actions/workflows/brain-cycle.yml/runs?branch=main&per_page=100'
REQUIRED_SPAN_SECONDS = 12 * 60 * 60
WINDOW_LIMIT_SECONDS = REQUIRED_SPAN_SECONDS + 30 * 60


def evaluate(summary):
    req(summary['maximum_gap'] <= 5400, 'automatic cycle gap exceeded')
    return {'status': 'PASS' if summary['span'] >= REQUIRED_SPAN_SECONDS else 'COLLECTING',
            'completed_span_seconds': summary['span'], 'required_span_seconds': REQUIRED_SPAN_SECONDS,
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


def window(rows, source, activation_start=None):
    selected = sorted((r for r in rows if r.get('head_sha') == source), key=lambda r: r['created_at'])
    req(selected, 'source runs absent')
    completed = []
    first = None
    for row in selected:
        created = utc(row['created_at']) if first is not None else None
        # The receipt is a fixed first-12.5-hour snapshot. A later run cannot
        # retroactively change that already bounded evidence window.
        # When a new owner-activated run is requested, keep source ancestry
        # but bound the actual review after first ORIGINAL successful observer.
        # Up to 15h permits the first post-activation core, a full 12h
        # completed-core span, a missed-cycle tolerance, and terminal repair.
        if activation_start is not None:
            req(activation_start.tzinfo is not None, 'activation timestamp must be aware')
            if utc(row['created_at']) > activation_start + timedelta(hours=15):
                break
        elif first is not None and (created - first).total_seconds() > WINDOW_LIMIT_SECONDS:
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
            # Include a boundary cycle at exactly 12.5h; the collector uses
            # job completion times to establish the required 12-hour span.
            if activation_start is None and (created - first).total_seconds() >= WINDOW_LIMIT_SECONDS:
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


def terminal_follow_through_ready(terminal, now=None):
    """An observer PASS must not precede the full 30-minute terminal interval."""
    instant = datetime.now(timezone.utc) if now is None else now
    req(isinstance(instant, datetime) and instant.tzinfo is not None,
        'invalid terminal follow-through clock')
    return instant >= terminal['completed'] + timedelta(minutes=30)


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
        # Preserve failed/retried original repairs even when they finish late.
        # Late successful work cannot retroactively certify the 30m window.
        if cutoff is not None and utc(row.get('updated_at')) > cutoff:
            continue
        doc = api.json(f"/actions/runs/{row['id']}/artifacts?per_page=100")
        artifacts = doc.get('artifacts', [])
        req(doc.get('total_count') == 1 and len(artifacts) == 1, 'repair artifact census invalid')
        item = artifacts[0]
        if cutoff is not None and utc(item.get('created_at')) > cutoff:
            continue
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
    # The first active observer must authenticate its own GitHub run before
    # recording an activation epoch. Earlier source history remains verified
    # for ancestry but never contributes 12-hour owner-window credit.
    marker = activation(api, source, current_run_id=int(os.environ['GITHUB_RUN_ID']))
    rows = window(inventory(api, CORE + "&head_sha=" + source), source,
                  activation_start=marker['created'])
    result = {'status': 'COLLECTING', 'source_sha': source,
              'required_span_seconds': REQUIRED_SPAN_SECONDS,
              'independent_release_authority': False,
              'activation_observer_run_id': marker['run_id'],
              'activation_observer_created_utc': marker['created'].isoformat().replace('+00:00', 'Z'),
              'completed_span_seconds': 0, 'qualifying_cores': 0}
    if sum(row.get('event') in {'schedule', 'workflow_dispatch'} for row in rows) >= 2:
        summary = collect_original_runs(Snapshot(api, rows), source)
        scoped = post_activation(summary, marker)
        result.update(status=scoped['status'],
                      completed_span_seconds=scoped['completed_span_seconds'],
                      maximum_gap_seconds=scoped['maximum_gap_seconds'],
                      qualifying_cores=len(scoped['automatic']))
        if scoped['automatic']:
            result.update(first_run_id=scoped['automatic'][0]['id'],
                          terminal_run_id=scoped['automatic'][-1]['id'])
        if scoped['automatic']:
            repairs = inventory(api, '/actions/workflows/v8-scoped-repair.yml/runs?branch=main&per_page=100&head_sha=' + source)
            terminal = scoped['automatic'][-1]
            complete = verify_repairs(
                api, repairs, source, {r['id'] for r in scoped['automatic']},
                cutoff=terminal['completed'] + timedelta(minutes=30),
            )
            if not complete:
                result.update(status='COLLECTING', reason='REPAIR_FOLLOW_THROUGH_PENDING')
            elif scoped['status'] == 'PASS' and not terminal_follow_through_ready(terminal):
                result.update(status='COLLECTING',
                              reason='TERMINAL_30_MINUTE_FOLLOW_THROUGH_PENDING')
    req(api.json('/branches/main')['commit']['sha'] == source, 'source moved')
    Path('reliability-day.json').write_text(json.dumps(result, sort_keys=True)+'\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
