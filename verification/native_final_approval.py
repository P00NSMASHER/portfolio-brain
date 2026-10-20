"""Read-only exact-approval verifier; NOT installed in the protected final gate.

The caller must supply a trusted, bounded, authenticated repository GET reader
and a durably retained enrollment ticket, never candidate code or a mutable label
as the ticket source. A ticket hash is only a binding: an ORIGINAL check issued by
the independent GitHub App must corroborate it. This module neither issues that
check nor publishes the final check, enrolls, disables, merges, or grants release.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import time

REPOSITORY = 'P00NSMASHER/portfolio-brain'
REPOSITORY_ID = 1387747549
APP_ID = 5121826
APPROVAL_NAME = 'portfolio-native-admission'
LABEL = 'brain:guarded-automerge'
MAX_TICKET_SECONDS = 600
MAX_OBSERVATION_SECONDS = 30
TICKET_KEYS = frozenset((
    'repository', 'repository_id', 'pr_number', 'pr_node_id', 'head_ref',
    'head_sha', 'base_ref', 'base_sha', 'controller_source_sha', 'policy_sha',
    'approval_check_id', 'issued_at', 'expires_at',
))


@dataclass(frozen=True)
class Result:
    status: str
    reason: str
    reads: int
    head_sha: str = ''
    provider_writes: int = 0
    merge_authorized: bool = False
    protected_check_issued: bool = False


class _Denied(ValueError):
    pass


def _need(condition, reason):
    if not condition:
        raise _Denied(reason)


def _sha(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{40}', value) is not None


def _positive(value):
    return type(value) is int and 0 < value < 10**15


def _utc(value):
    _need(type(value) is str and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value) is not None,
        'TIMESTAMP_INVALID')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        raise _Denied('TIMESTAMP_INVALID') from None


def approval_fingerprint(ticket):
    """Canonical binding only. Computing this does NOT create an approval."""
    _need(type(ticket) is dict and set(ticket) == TICKET_KEYS, 'TICKET_SCHEMA')
    body = {k: v for k, v in ticket.items() if k != 'approval_check_id'}
    raw = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return 'native-admission-v1:' + hashlib.sha256(raw).hexdigest()


def _window(ticket, now):
    _need(type(now) is datetime and now.tzinfo is not None and now.utcoffset() is not None,
          'CLOCK_INVALID')
    issued, expires = _utc(ticket['issued_at']), _utc(ticket['expires_at'])
    _need(0 < (expires - issued).total_seconds() <= MAX_TICKET_SECONDS
          and issued <= now < expires, 'TICKET_EXPIRED_FUTURE_OR_OVERLONG')


def _ticket(ticket, source, policy, now):
    _need(type(ticket) is dict and set(ticket) == TICKET_KEYS, 'TICKET_SCHEMA')
    _need(ticket['repository'] == REPOSITORY
          and type(ticket['repository_id']) is int
          and ticket['repository_id'] == REPOSITORY_ID, 'TICKET_REPOSITORY')
    _need(_positive(ticket['pr_number']) and _positive(ticket['approval_check_id'])
          and type(ticket['pr_node_id']) is str
          and re.fullmatch(r'PR_[A-Za-z0-9_-]{8,190}', ticket['pr_node_id']) is not None,
          'TICKET_PR_IDENTITY')
    _need(type(ticket['head_ref']) is str and ticket['head_ref'] != 'main'
          and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_/-]{0,127}', ticket['head_ref']) is not None
          and all(ticket['head_ref'].split('/')), 'TICKET_HEAD_REF')
    _need(_sha(source) and _sha(policy) and _sha(ticket['head_sha'])
          and ticket['head_sha'] != source and ticket['base_ref'] == 'main'
          and ticket['base_sha'] == source and ticket['controller_source_sha'] == source
          and ticket['policy_sha'] == policy, 'TICKET_SOURCE_OR_POLICY')
    _window(ticket, now)


def _main(record, ticket):
    _need(type(record) is dict and record.get('name') == 'main'
          and record.get('protected') is True and type(record.get('commit')) is dict
          and record['commit'].get('sha') == ticket['base_sha'], 'MAIN_OR_PROTECTION_DRIFT')


def _pr(record, ticket):
    _need(type(record) is dict and type(record.get('number')) is int
          and record['number'] == ticket['pr_number']
          and record.get('node_id') == ticket['pr_node_id'], 'PR_IDENTITY')
    _need(record.get('state') == 'open' and record.get('draft') is False
          and record.get('merged') is False and record.get('mergeable') is True
          and record.get('mergeable_state') in ('blocked', 'clean'), 'PR_STATE')
    for side in ('head', 'base'):
        value = record.get(side)
        _need(type(value) is dict and value.get('sha') == ticket[side + '_sha']
              and value.get('ref') == ticket[side + '_ref'], 'PR_HEAD_OR_BASE_DRIFT')
        repo = value.get('repo')
        _need(type(repo) is dict and type(repo.get('id')) is int
              and repo['id'] == REPOSITORY_ID and repo.get('full_name') == REPOSITORY,
              'PR_REPOSITORY')
    labels = record.get('labels')
    _need(type(labels) is list and len(labels) < 100
          and all(type(x) is dict and type(x.get('name')) is str for x in labels)
          and sum(x['name'] == LABEL for x in labels) == 1, 'OPT_IN_ABSENT_OR_AMBIGUOUS')
    auto = record.get('auto_merge')
    _need(type(auto) is dict and auto.get('merge_method') == 'squash', 'ENROLLMENT_UNPROVEN')


def _approval(record, ticket, now):
    _need(type(record) is dict and type(record.get('id')) is int
          and record['id'] == ticket['approval_check_id']
          and record.get('name') == APPROVAL_NAME
          and record.get('head_sha') == ticket['head_sha']
          and record.get('url') == f'https://api.github.com/repos/{REPOSITORY}/check-runs/{record["id"]}',
          'APPROVAL_IDENTITY')
    app = record.get('app')
    _need(type(app) is dict and type(app.get('id')) is int and app['id'] == APP_ID,
          'APPROVAL_ISSUER')
    _need(record.get('status') == 'completed' and record.get('conclusion') == 'success'
          and record.get('external_id') == approval_fingerprint(ticket), 'APPROVAL_BINDING_OR_STATUS')
    _need(_utc(ticket['issued_at']) <= _utc(record.get('started_at'))
          <= _utc(record.get('completed_at')) <= now, 'APPROVAL_CHRONOLOGY')
    return (record['id'], record['external_id'], record['started_at'], record['completed_at'])


def _census(record, ticket, now):
    _need(type(record) is dict and type(record.get('total_count')) is int
          and 1 <= record['total_count'] < 100 and type(record.get('check_runs')) is list
          and len(record['check_runs']) == record['total_count'], 'CHECK_CENSUS_INCOMPLETE')
    rows = record['check_runs']
    _need(all(type(x) is dict and _positive(x.get('id'))
              and x.get('head_sha') == ticket['head_sha'] for x in rows), 'CHECK_IDENTITY')
    _need(len({x['id'] for x in rows}) == len(rows), 'CHECK_ID_DUPLICATED')
    foundation = [x for x in rows if x.get('name') == 'validate']
    _need(len(foundation) == 1, 'FOUNDATION_AMBIGUOUS_OR_ABSENT')
    f = foundation[0]
    _need(type(f.get('app')) is dict and type(f['app'].get('id')) is int
          and f['app']['id'] == 15368 and f.get('status') == 'completed'
          and f.get('conclusion') == 'success', 'FOUNDATION_NOT_SUCCESS')
    approval = [x for x in rows if x.get('name') == APPROVAL_NAME]
    _need(len(approval) == 1, 'APPROVAL_CENSUS_AMBIGUOUS_OR_ABSENT')
    return _approval(approval[0], ticket, now)


def verify_final_approval(read, ticket, *, expected_source_sha, expected_policy_sha, now):
    """Corroborate the exact independent approval using at most seven GETs.

    All returned decisions are read-only evidence, not enforcement or release.
    The deployed final-check issuer must call this fail-closed for EVERY enrolled
    PR lineage, retain tickets independently of labels, and prohibit a generic
    green-check fallback. Those deployment changes are deliberately absent here.
    """
    count = 0
    started = time.monotonic()

    def current_time():
        elapsed = time.monotonic() - started
        _need(0 <= elapsed <= MAX_OBSERVATION_SECONDS, 'OBSERVATION_DEADLINE')
        return now + timedelta(seconds=elapsed)

    def get(path):
        nonlocal count
        _window(ticket, current_time())
        _need(count < 7, 'READ_BOUND')
        count += 1
        value = read(path)
        _window(ticket, current_time())
        return value

    try:
        _need(type(ticket) is dict, 'TICKET_SCHEMA')
        # Detach FIRST; validation must inspect the same snapshot used by reads.
        ticket = dict(ticket)
        _ticket(ticket, expected_source_sha, expected_policy_sha, now)
        _main(get('/branches/main'), ticket)
        _pr(get(f'/pulls/{ticket["pr_number"]}'), ticket)
        approval_path = f'/check-runs/{ticket["approval_check_id"]}'
        initial = _approval(get(approval_path), ticket, current_time())
        census = _census(get(f'/commits/{ticket["head_sha"]}/check-runs?per_page=100'),
                         ticket, current_time())
        _need(census == initial, 'APPROVAL_CENSUS_CHANGED')
        _main(get('/branches/main'), ticket)
        _pr(get(f'/pulls/{ticket["pr_number"]}'), ticket)
        final = _approval(get(approval_path), ticket, current_time())
        _need(final == initial, 'APPROVAL_CHANGED')
        return Result('APPROVAL_MATCHED_NOT_ENFORCEMENT',
                      'FINAL_GATE_INTEGRATION_AND_PLATFORM_RACE_PROOF_STILL_REQUIRED',
                      count, ticket['head_sha'])
    except _Denied as error:
        return Result('HOLD', str(error), count)
    except Exception:
        # Never echo provider response text, tokens, or unexpected object values.
        return Result('HOLD', 'PROVIDER_OR_INPUT_UNVERIFIED', count)
