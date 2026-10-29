"""Durable execution of the shipped local recipe regression, never target code.

Temporary files and Python -I are not an OS security sandbox. Only the fixed
regression emitted by the allowlisted generator is executed. All stage names
refer to that fixture: no repository patch, provider write or release occurs.
Local hashes detect accidental corruption, not a hostile same-user writer.
"""
from datetime import timedelta
import os
from brain.core import digest, require
from brain.repair_patch_executor import generate
from brain.v8.contracts import LOCAL_STATES, advance, parse_utc
from brain.v8.engineering import exercise_repair
from brain.v8.journal import KernelJournal
from brain.v8.private_state import PrivateFiles
from brain.v9.missions import project_mission

ADAPTER = 'V9_FIXED_LOCAL_RECIPE_V1'
SCOPE = 'LOCAL_GENERATED_REGRESSION_ONLY'


def _operation(row, ident, expected, outcome):
    return dict(schema_version=1, operation_id=ident, work=row,
                expected_state=expected, occurred_at=row['updated_at'], outcome=outcome)


def _snapshot(journal):
    records = journal.replay()
    state, pending, claims, completed = {}, {}, {}, {}
    for record in records:
        KernelJournal._apply_record(record['kind'], record['operation'],
                                    state, pending, claims, completed)
    return records, state, pending, claims


def _expected_result(patch):
    return dict(status='ISOLATED_RECIPE_RED_GREEN', source_sha=patch['source_head_sha'],
                patch_sha256=patch['changed_sha256'], test_sha256=patch['test_sha256'],
                original_returncode=1, corrected_returncode=0,
                production_accepted=False, third_party_code_executed=False)


def _validate_result(body, *, row, request, patch, operation_id, now):
    expected = dict(adapter=ADAPTER, scope=SCOPE, work_id=row['work_id'],
                    request_sha256=digest(request), operation_id=operation_id,
                    artifact=patch, result=_expected_result(patch))
    require(type(body) is dict and set(body) == set(expected) | {'observed_at'},
            'V9_RECIPE_RESULT_FIELDS')
    require(digest({key: body[key] for key in expected}) == digest(expected),
            'V9_RECIPE_RESULT_IDENTITY')
    # Equality alone would admit bool values in place of integer return codes.
    require(type(body['result']['original_returncode']) is int
            and type(body['result']['corrected_returncode']) is int,
            'V9_RECIPE_RESULT_COUNTERS')
    require(parse_utc(row['created_at']) <= parse_utc(body['observed_at']) <= parse_utc(now),
            'V9_RECIPE_RESULT_TIME')
    return body


def execute_recipe(mission, journal, request, original, *, source_heads, now):
    """Execute once, or resume a validated durable result without re-execution.

    Missing results after intent remain blocked for external investigation.
    Orphan claims left before intent also require external reconciliation;
    lease expiry never authorizes a retry. DIAGNOSED records the generator's
    static finding, REPRODUCED the failing fixed regression, PATCHED the temporary
    changed fixture, and TESTED the passing fixed regression. None represents
    an actual repository edit or an independent acceptance decision. Heads
are caller-supplied observations; this adapter grants no repository authority.
The cooperative directory lock serializes v9 callers using this journal. Other
writers must follow the same locking/claim protocol; it is not a hostile-process
security boundary. Outcome files use a dedicated private subdirectory so v8
learning records cannot be confused with recipe artifacts.
"""
    require(type(journal) is KernelJournal and not journal.readonly,
            'V9_RECIPE_WRITABLE_JOURNAL_REQUIRED')
    require(type(request) is dict and type(request.get('schema_version')) is int
            and type(request.get('repository')) is str and type(original) is bytes,
            'V9_RECIPE_REQUEST_INVALID')
    patch = generate(request, original)
    clock = parse_utc(now)
    root = PrivateFiles(journal.path.parent)
    with root.lock():
        plan = project_mission(mission, journal, source_heads=source_heads, now=now)
        matches = [row for row in mission['work']
                   if row['fingerprint'] == digest(request)
                   and row['repository'] == request['repository']
                   and row['source_sha'] == request['source_head_sha']]
        require(len(matches) == 1, 'V9_RECIPE_WORK_BINDING')
        identity = matches[0]
        key = identity['work_id']
        resource = digest(dict(repository=request['repository'].casefold()))
        require(identity['resource'] == resource, 'V9_RECIPE_RESOURCE_BINDING')
        ident = digest(dict(adapter=ADAPTER, work_id=key))
        records, state, pending, claims = _snapshot(journal)
        require(key in state, 'V9_RECIPE_WORK_NOT_OBSERVED')
        row = state[key]
        require(row['state'] in LOCAL_STATES and row['blocker'] is None,
                'V9_RECIPE_WORK_STATE')
        # Stable journal-specific namespace, separate from v8 learning outcomes.
        folder = journal.path.parent / ('.v9-local-recipe-' + digest(str(journal.path))[:16])
        folder.mkdir(mode=0o700, exist_ok=True)
        files = PrivateFiles(folder)
        directory = os.open(journal.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        body = files.read('outcome', ident)
        intents = [record for record in records if record['kind'] == 'WORK'
                   and record['operation']['operation_id'] == ident
                   and record['operation']['outcome'] == 'EXTERNAL_INTENT']
        require(len(intents) <= 1, 'V9_RECIPE_DUPLICATE_INTENT')
        if intents:
            intent = intents[0]['operation']
            require(intent['work']['work_id'] == key and intent['work']['state'] == 'OBSERVED'
                    and intent['expected_state'] == 'OBSERVED', 'V9_RECIPE_INTENT_IDENTITY')
        if body is not None:
            _validate_result(body, row=row, request=request, patch=patch,
                             operation_id=ident, now=now)
            require(bool(intents), 'V9_RECIPE_RESULT_WITHOUT_INTENT')
        elif intents:
            require(False, 'V9_RECIPE_UNCERTAIN_RESULT_NO_REEXECUTION')

        if not intents:
            require(body is None and row['state'] == 'OBSERVED'
                    and key in {item['work_id'] for item in plan['selected']},
                    'V9_RECIPE_NOT_SELECTED')
            expires = (clock + timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
            journal.claim(resource=resource, owner=row['owner'], operation_id=ident,
                          source_sha=row['source_sha'], now=now, expires_at=expires)
            row = dict(row, updated_at=now)
            journal.append(_operation(row, ident, 'OBSERVED', 'EXTERNAL_INTENT'))
            result = exercise_repair(request, original)
            require(digest(result) == digest(_expected_result(patch))
                    and type(result['original_returncode']) is int
                    and type(result['corrected_returncode']) is int,
                    'V9_RECIPE_REGRESSION_FAILED')
            body = dict(adapter=ADAPTER, scope=SCOPE, work_id=key,
                        request_sha256=digest(request), operation_id=ident,
                        artifact=patch, result=result, observed_at=now)
            files.write('outcome', ident, body)

        # Recovery ignores only this adapter's own verified claim and intent.
        # A foreign claim/write on the same normalized repository remains fatal.
        records, state, pending, claims = _snapshot(journal)
        row = state[key]
        repo = row['repository'].casefold()
        require(all(other == key and action == ident or
                    (state[other]['repository'].casefold() != repo
                     and state[other]['resource'] != resource)
                    for other, action in pending.items()), 'V9_RECIPE_FOREIGN_PENDING')
        for claimed_resource, claim in claims.items():
            related = claimed_resource == resource or any(
                item['resource'] == claimed_resource and item['repository'].casefold() == repo
                for item in state.values())
            if related:
                require(claimed_resource == resource and claim['operation_id'] == ident
                        and claim['owner'] == row['owner'] and claim['source_sha'] == row['source_sha'],
                        'V9_RECIPE_FOREIGN_CLAIM')
        checked_dependencies = set()
        def complete_dependency(dependency):
            if dependency in checked_dependencies:
                return
            item = state.get(dependency)
            require(item is not None and item['state'] == 'TESTED' and item['blocker'] is None,
                    'V9_RECIPE_DEPENDENCY_UNFINISHED')
            dep_repo = item['repository'].casefold()
            require(not any(action != ident and
                            (state[other]['repository'].casefold() == dep_repo
                             or state[other]['resource'] == item['resource'])
                            for other, action in pending.items()),
                    'V9_RECIPE_DEPENDENCY_UNCERTAIN')
            require(not any(claim['operation_id'] != ident and
                            (claimed_resource == item['resource'] or any(
                                candidate['resource'] == claimed_resource
                                and candidate['repository'].casefold() == dep_repo
                                for candidate in state.values()))
                            for claimed_resource, claim in claims.items()),
                    'V9_RECIPE_DEPENDENCY_CLAIMED')
            for parent in item['dependencies']:
                complete_dependency(parent)
            checked_dependencies.add(dependency)
        for dependency in row['dependencies']:
            complete_dependency(dependency)
        evidence = digest(body)
        operations = {record['operation']['operation_id']: record['operation']
                      for record in records if record['kind'] == 'WORK'}
        confirm_id = digest(dict(adapter=ADAPTER, work_id=key, phase='CONFIRM'))
        if key not in pending:
            confirmation = operations.get(confirm_id)
            require(confirmation is not None and confirmation['work']['work_id'] == key
                    and confirmation['outcome'] == 'EXTERNAL_CONFIRMED',
                    'V9_RECIPE_CONFIRMATION_MISSING')
        for stage in LOCAL_STATES[1:LOCAL_STATES.index(row['state']) + 1]:
            stage_op = operations.get(digest(dict(adapter=ADAPTER, work_id=key, phase=stage)))
            require(stage_op is not None and stage_op['work']['work_id'] == key
                    and stage_op['work']['state'] == stage
                    and stage_op['work']['evidence_ids'] == [evidence]
                    and stage_op['outcome'] == 'LOCAL_COMMITTED', 'V9_RECIPE_STAGE_PROVENANCE')
        require(row['state'] == 'TESTED' or resource in claims, 'V9_RECIPE_CLAIM_MISSING')
        if key in pending:
            row = dict(row, updated_at=now)
            journal.append(_operation(row, confirm_id,
                                      row['state'], 'EXTERNAL_CONFIRMED'))
        while row['state'] != 'TESTED':
            previous = row['state']
            target = LOCAL_STATES[LOCAL_STATES.index(previous) + 1]
            row = advance(row, target, evidence_ids=[evidence], now=now)
            journal.append(_operation(row, digest(dict(adapter=ADAPTER, work_id=key, phase=target)),
                                      previous, 'LOCAL_COMMITTED'))
        if resource in claims:
            journal.release_claim(resource=resource, owner=row['owner'], operation_id=ident, now=now)
        return dict(status='LOCAL_RECIPE_TESTED', scope=SCOPE, work_id=key,
                    operation_id=ident, artifact_sha256=evidence,
                    artifact_path=str(files.path('outcome', ident)),
                    reused_result=bool(intents), production_accepted=False,
                    independently_accepted=False, provider_calls=0,
                    target_code_executed=False, merge_authority=False, release_authority=False)
