"""Bounded source-bound local mission DAGs projected from the existing journal.

No provider calls, second persistence, leases, or acceptance authority. A plan is
a point-in-time advisory snapshot; authorized executors must recheck before acting.
"""
from copy import deepcopy
from brain.core import digest, require
from brain.intelligence import REPO
from brain.v8.contracts import LOCAL_STATES, SHA, matches, parse_utc, validate_work
from brain.v8.journal import KernelJournal, MUTABLE
from brain.v9 import SCOPE

MAX_WORK = 256
MAX_PARALLEL = 5
FIELDS = {'schema_version', 'mission_id', 'scope', 'source_heads', 'work', 'max_parallel'}


def _identity(row):
    return {key: deepcopy(value) for key, value in row.items() if key not in MUTABLE}


def _heads(heads):
    require(type(heads) is dict and 0 < len(heads) <= MAX_WORK
            and all(matches(REPO, repo) and matches(SHA, sha)
                    for repo, sha in heads.items()), 'V9_SOURCE_HEADS_INVALID')
    return dict(sorted(heads.items()))


def compile_mission(work_items, *, source_heads, max_parallel=1):
    """Freeze work identity and reject incomplete or cyclic DAGs."""
    require(type(work_items) is list and 0 < len(work_items) <= MAX_WORK,
            'V9_MISSION_BOUND')
    require(type(max_parallel) is int and 1 <= max_parallel <= MAX_PARALLEL,
            'V9_PARALLEL_BOUND')
    heads = _heads(source_heads)
    rows = [validate_work(row) for row in work_items]
    by_id = {row['work_id']: row for row in rows}
    require(len(by_id) == len(rows), 'V9_DUPLICATE_WORK')
    require(set(heads) == {row['repository'] for row in rows}, 'V9_SOURCE_MEMBERSHIP')
    require(all(heads[row['repository']] == row['source_sha'] for row in rows),
            'V9_SOURCE_DRIFT')
    done, visiting = set(), set()

    def visit(key):
        require(key in by_id, 'V9_DEPENDENCY_MISSING')
        require(key not in visiting, 'V9_DEPENDENCY_CYCLE')
        if key in done:
            return
        visiting.add(key)
        for dependency in by_id[key]['dependencies']:
            visit(dependency)
        visiting.remove(key)
        done.add(key)

    for key in sorted(by_id):
        visit(key)
    body = dict(schema_version=1, scope=SCOPE, source_heads=heads,
                work=[_identity(by_id[key]) for key in sorted(by_id)],
                max_parallel=max_parallel)
    return dict(body, mission_id='mission:' + digest(body))


def _validate_mission(mission):
    require(type(mission) is dict and set(mission) == FIELDS, 'V9_MISSION_FIELDS')
    require(type(mission['schema_version']) is int and mission['schema_version'] == 1
            and mission['scope'] == SCOPE, 'V9_MISSION_VERSION_OR_SCOPE')
    body = {key: value for key, value in mission.items() if key != 'mission_id'}
    require(mission['mission_id'] == 'mission:' + digest(body), 'V9_MISSION_IDENTITY')
    require(type(mission['work']) is list and 0 < len(mission['work']) <= MAX_WORK,
            'V9_MISSION_BOUND')
    rows = []
    for item in mission['work']:
        require(type(item) is dict and not (set(item) & MUTABLE), 'V9_MISSION_WORK_FIELDS')
        rows.append(dict(item, state='OBSERVED', evidence_ids=[],
                         updated_at=item.get('created_at'), attempts=0, blocker=None))
    expected = compile_mission(rows, source_heads=mission['source_heads'],
                               max_parallel=mission['max_parallel'])
    require(expected == mission, 'V9_MISSION_NONCANONICAL')


def project_mission(mission, journal, *, source_heads, now):
    """Select next local stages from validated replay. TESTED is not acceptance.

    Current heads are supplied observations, not authenticated access evidence.
    Held claims block even after expiry, until explicitly reconciled and released.
    """
    _validate_mission(mission)
    current = parse_utc(now)
    require(_heads(source_heads) == mission['source_heads'], 'V9_SOURCE_DRIFT')
    require(type(journal) is KernelJournal, 'V9_KERNEL_JOURNAL_REQUIRED')
    records = journal.replay()
    state, pending, claims, completed = {}, {}, {}, {}
    for record in records:
        KernelJournal._apply_record(record['kind'], record['operation'],
                                    state, pending, claims, completed)
    require(all(parse_utc(row['updated_at']) <= current for row in state.values())
            and all(parse_utc(claim['now']) <= current for claim in claims.values()),
            'V9_PROJECTION_TIME_REVERSED')
    unresolved = {state[key]['resource'] for key in pending}
    membership = {row['work_id']: row for row in mission['work']}
    for key, identity in membership.items():
        require(key not in state or _identity(state[key]) == identity,
                'V9_WORK_MEMBERSHIP_CHANGED')

    reasons = {}
    def reason(key):
        if key in reasons:
            return reasons[key]
        row = state.get(key)
        result = None
        if row is None:
            result = 'WORK_NOT_OBSERVED'
        elif row['resource'] in unresolved:
            result = 'EXTERNAL_RECONCILIATION_REQUIRED'
        elif row['resource'] in claims:
            result = 'RESOURCE_CLAIM_HELD'
        elif row['state'] not in LOCAL_STATES or row['blocker'] is not None:
            result = 'NONLOCAL_OR_BLOCKED_STATE'
        elif any(reason(dep) is not None or state.get(dep, {}).get('state') != 'TESTED'
                 for dep in membership[key]['dependencies']):
            result = 'LOCAL_DEPENDENCY_UNFINISHED'
        reasons[key] = result
        return result

    selected, blocked, deferred, local_completed = [], [], [], []
    resources = set()
    ordered = sorted(membership, key=lambda key: (membership[key]['priority_tier'], key))
    for key in ordered:
        why = reason(key)
        if why:
            blocked.append(dict(work_id=key, reason=why))
        elif state[key]['state'] == 'TESTED':
            local_completed.append(key)
        elif membership[key]['resource'] in resources:
            deferred.append(dict(work_id=key, reason='RESOURCE_COLLISION'))
        elif len(selected) >= mission['max_parallel']:
            deferred.append(dict(work_id=key, reason='PARALLEL_BOUND'))
        else:
            resources.add(membership[key]['resource'])
            selected.append(dict(work_id=key, source_sha=state[key]['source_sha'],
                                 next_local_state=LOCAL_STATES[LOCAL_STATES.index(state[key]['state']) + 1]))
    return dict(mission_id=mission['mission_id'], scope=SCOPE, observed_at=now,
                journal_tip=records[-1]['chain_hash'] if records else '0' * 64,
                selected=selected, blocked=blocked, deferred=deferred,
                local_completed=local_completed, independently_accepted=False,
                automatic_execution_authority=False, release_authority=False)
