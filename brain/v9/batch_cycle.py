"""Wire durable v9 work and bounded original publication reads into the core cycle.

Uses the existing state image and project GET budget. Produces existing-owner
handoffs, never a merge, deployment, credential, schedule or automatic release.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from brain.v9.batch_queue import BatchQueue, BatchFault, PROJECTS, digest, hashval, instant
from brain.v9.batch_routing import route_defect, select_distinct_owners
from brain.v9.publication_reader import PublicationReader, REQUIRED_BUDGET

# Approved bounded reader codes only. Never preserve raw provider response text,
# exceptions, URLs, token values, stack traces or unrecognized BatchFault payloads.
PUBLICATION_FAILURE_CODES = frozenset({
    'PROVIDER_READBACK_REQUIRED',
    'PUBLICATION_ASSET_INVALID',
    'PUBLICATION_BRANCH_INVALID',
    'PUBLICATION_BROWSER_JOB_NOT_VERIFIED',
    'PUBLICATION_CANDIDATE_QA_NOT_VERIFIED',
    'PUBLICATION_CENSUS_INCOMPLETE',
    'PUBLICATION_DUPLICATE_JSON_KEY',
    'PUBLICATION_HTTP_NOT_OK',
    'PUBLICATION_JSON_INVALID',
    'PUBLICATION_LIVE_BYTES_MISMATCH',
    'PUBLICATION_LIVE_STEP_NOT_VERIFIED',
    'PUBLICATION_NONFINITE',
    'PUBLICATION_ORIGINAL_RUN_MISSING',
    'PUBLICATION_ORIGINAL_RUN_NOT_SUCCESS',
    'PUBLICATION_PROVIDER_UNAVAILABLE',
    'PUBLICATION_PR_NOT_EXACT_MERGE',
    'PUBLICATION_REPAIR_NOT_IN_DEPLOYED_HISTORY',
    'PUBLICATION_RESPONSE_TOO_LARGE',
    'PUBLICATION_ROUTE_REFUSED',
    'PUBLICATION_SOURCE_BYTES_MISMATCH',
    'PUBLICATION_SOURCE_MOVED_DURING_READBACK',
    'PUBLICATION_SPEC_FIELDS',
    'PUBLICATION_SPEC_SCOPE',
    'PUBLICATION_URL_REFUSED',
    'READBACK_BUDGET_EXHAUSTED',
    'RECONCILIATION_REQUIRED',
    'RECONCILIATION_SOURCE_CHANGED',
})
def stable_publication_failure(exc):
    code = str(exc) if isinstance(exc, BatchFault) else None
    return code if code in PUBLICATION_FAILURE_CODES else 'PUBLICATION_FAILURE_UNCLASSIFIED'

RETIRED = {'product-factory', 'pips-classroom', 'trading-platform'}
CHECK_STATES = {'SOURCE_UNOBSERVED', 'CHECK_EVIDENCE_UNVERIFIED', 'NO_CHECK_RUNS_OBSERVED',
                'ADVERSE_CHECKS_OBSERVED', 'INCOMPLETE_OR_INCONCLUSIVE_CHECKS_OBSERVED',
                'NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL'}

def need(condition, code):
    if not condition:
        raise BatchFault(code)

def run_cycle(report, queue, *, source_sha, cycle, now, proof_spec=None, reader=None):
    need(hashval(source_sha, 40) and type(cycle) is int and 0 <= cycle < 2**63,
         'CYCLE_SOURCE_INVALID')
    when = instant(now)
    need(type(report) is dict and report.get('source_sha') == source_sha
         and type(report.get('schema_version')) is int and report['schema_version'] == 1
         and type(report.get('canonical_pending_events')) is int
         and report['canonical_pending_events'] == 0, 'CYCLE_SOURCE_INVALID')
    operation = report.get('operation')
    need(type(operation) is dict and operation.get('name') == 'projects'
         and type(operation.get('requests')) is int and 0 <= operation['requests'] <= 24,
         'CYCLE_GET_BUDGET_INVALID')
    used = operation['requests']
    reserved = operation.get('publication_reserved_gets', 0)
    ceiling = operation.get('project_request_ceiling', 24 - reserved)
    # Reject a false reservation before touching the durable queue. The 24
    # GET cap still includes real project GETs and original publication GETs.
    need(type(reserved) is int and reserved in (0, REQUIRED_BUDGET)
         and type(ceiling) is int and ceiling == 24 - reserved
         and used <= ceiling, 'CYCLE_GET_BUDGET_INVALID')
    rows = report.get('projects')
    need(type(rows) is list and len(rows) <= 16, 'CYCLE_PROJECTS_INVALID')
    inputs, missing, skipped, seen = [], [], [], set()
    for row in rows:
        need(type(row) is dict and type(row.get('id')) is str and row['id'] not in seen,
             'CYCLE_PROJECTS_INVALID')
        project = row['id']
        seen.add(project)
        if project in RETIRED:
            skipped.append(project)
            continue
        need(project in PROJECTS and row.get('repository') == PROJECTS[project],
             'CYCLE_PROJECT_IDENTITY_INVALID')
        state = row.get('source_check_state')
        need(type(state) is str and state in CHECK_STATES, 'CYCLE_CHECK_STATE_INVALID')
        sha = row.get('repository_revision')
        if sha is None:
            missing.append(project)
            continue
        need(hashval(sha, 40), 'CYCLE_PROJECT_SOURCE_INVALID')
        adverse = state == 'ADVERSE_CHECKS_OBSERVED'
        clean = state == 'NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL'
        # Check-run history for a commit also includes checks from unrelated
        # feature-branch runs on that SHA.  This source-only envelope cannot
        # prove that an adverse check was from a protected-main runtime cycle.
        kind = 'CHECK_EVIDENCE_TRIAGE' if adverse else 'RESEARCH'
        # This is a repository diagnosis scope, not a claimed source file or
        # authority to mutate arbitrary files. The owner must identify a real
        # defect/path and claim its current source before any actual edit.
        path = 'repository-observation'
        route = route_defect(project_id=project, repository=row['repository'],
                             source_sha=sha, path=path, kind=kind)
        route['source_check_state'] = state
        priority = 1 if adverse else (3 if clean else 2)
        item = dict(project_id=project, repository=row['repository'], source_sha=sha,
                    fingerprint=digest(dict(project=project, check_state=state,
                                            purpose='SOURCE_BOUND_DIAGNOSIS')),
                    owner=route['owner'], path=path, priority=priority)
        inputs.append((item, route))
    # All report fields are checked before adding any durable observations.
    current_ids = []
    routes = {}
    for item, route in inputs:
        ident = queue.observe(item, now=now)
        current_ids.append(ident)
        routes[ident] = route
    before_gets = 0
    provider = dict(status='NO_CONFIGURED_PUBLICATION_PROOF', provider_gets=0,
                    production_accepted=False)
    if proof_spec is not None:
        remaining = 24 - used
        if remaining < REQUIRED_BUDGET:
            provider['status'] = 'BUDGET_UNAVAILABLE_NOT_VERIFIED'
        else:
            actual = reader if reader is not None else PublicationReader(
                token=os.environ.get('GITHUB_TOKEN', ''), max_gets=remaining)
            need(type(actual) is PublicationReader and actual.max_gets <= remaining,
                 'CYCLE_READER_BUDGET_INVALID')
            before_gets = actual.used_gets
            try:
                provider = queue.record_publication(proof_spec, actual, now=now)
            except (BatchFault, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                # Keep the original fail-closed verdict, and expose only one
                # fixed machine code so an absent downstream quality run can
                # be distinguished from a changed source or bad live bytes.
                provider = dict(status='ORIGINAL_PUBLICATION_NOT_VERIFIED',
                                failure_code=stable_publication_failure(exc),
                                production_accepted=False)
            provider['provider_gets'] = actual.used_gets - before_gets
    total = used + provider.get('provider_gets', 0)
    need(total <= 24, 'CYCLE_GET_BUDGET_EXCEEDED')
    state = queue.snapshot()['work']
    candidates, held = [], []
    # Include older-source leases and uncertain writes. A current report must
    # not issue a new assignment that competes with an earlier active owner.
    busy_owners, busy_repositories = set(), set()
    for existing in state.values():
        claim = existing['claim']
        if existing['pending'] is not None or (claim is not None and when < instant(claim['expires_at'])):
            busy_owners.add(existing['owner'])
            busy_repositories.add(existing['repository'].casefold())
    for ident in current_ids:
        work = state[ident]
        lease = work['claim']
        busy = lease is not None and when < instant(lease['expires_at'])
        if (work['pending'] is not None or busy or work['stage'] == 'LIVE_VERIFIED'
                or work['owner'] in busy_owners or work['repository'].casefold() in busy_repositories):
            held.append(ident)
            continue
        route = routes[ident]
        candidates.append(dict(work_id=ident, project_id=work['project_id'],
            repository=work['repository'], source_sha=work['source_sha'],
            path=work['path'], priority=work['priority'], owner=work['owner'],
            verifier=route['verifier'], stage=work['stage'],
            source_check_state=route['source_check_state'],
            incident_classification=(
                'ADVERSE_CHECK_HISTORY_PRODUCTION_UNVERIFIED'
                if route['defect_kind'] == 'CHECK_EVIDENCE_TRIAGE'
                else 'NO_PRODUCTION_INCIDENT_CLAIM'),
            source_reobservation_required=True, durable_claim_required_before_mutation=True,
            automatic_execution_authority=False))
    selected = select_distinct_owners(candidates, limit=5, cycle=cycle)
    return dict(schema_version=1, status='DURABLE_OWNER_QUEUE_UPDATED_NOT_RELEASED',
                source_sha=source_sha, owner_jobs=selected['selected'],
                deferred_work_ids=[row['work_id'] for row in selected['deferred']],
                held_work_ids=held, unobserved_projects=missing,
                outside_owner_scope=skipped, queue_checkpoint=queue.checkpoint(),
                metrics=queue.metrics(now=now), provider_readback=provider,
                provider_gets=provider.get('provider_gets', 0), total_project_gets=total,
                provider_writes=0, production_accepted=False,
                six_hour_acceptance_passed=False, automatic_execution_authority=False)

def load_json(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 2*1024*1024,
         'CYCLE_INPUT_INVALID')
    def pairs(values):
        result = {}
        for key, value in values:
            need(key not in result, 'CYCLE_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(BatchFault('CYCLE_NONFINITE')))

def write_receipt(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    need(not any(p.is_symlink() for p in (path, *path.parents)), 'CYCLE_OUTPUT_UNSAFE')
    fd, temporary = tempfile.mkstemp(prefix='.v9-receipt-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(result, output, sort_keys=True, indent=2, allow_nan=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    core = commands.add_parser('cycle')
    core.add_argument('--input', type=Path, required=True)
    core.add_argument('--expected-sha', required=True)
    core.add_argument('--cycle', type=int, required=True)
    core.add_argument('--proof-manifest', type=Path)
    proof = commands.add_parser('proof')
    proof.add_argument('--spec', type=Path, required=True)
    for command in (core, proof):
        command.add_argument('--db', type=Path, required=True)
        command.add_argument('--now', required=True)
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    queue = None
    try:
        queue = BatchQueue(args.db)
        if args.command == 'cycle':
            result = run_cycle(load_json(args.input), queue, source_sha=args.expected_sha,
                cycle=args.cycle, now=args.now,
                proof_spec=load_json(args.proof_manifest) if args.proof_manifest else None)
        else:
            spec = load_json(args.spec)
            reader = PublicationReader(token=os.environ.get('GITHUB_TOKEN', ''), max_gets=10)
            proof_result = queue.record_publication(spec, reader, now=args.now)
            checkpoint = queue.checkpoint()
            restored = queue.restore_drill()
            queue.close()
            queue = BatchQueue(args.db)
            need(queue.checkpoint() == checkpoint, 'PUBLICATION_RESTART_REPLAY_MISMATCH')
            result = dict(status='ORIGINAL_REPAIR_PUBLICATION_AND_DURABLE_REPLAY_VERIFIED',
                publication=proof_result, restart_checkpoint=checkpoint, restore=restored,
                metrics=queue.metrics(now=args.now), production_accepted=False,
                six_hour_acceptance_passed=False)
        write_receipt(args.output, result)
        print(json.dumps({'status': result['status'], 'production_accepted': False}, sort_keys=True))
        return 0
    except (BatchFault, OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error):
        result = dict(status='BLOCKED_V9_INTEGRATION_NOT_VERIFIED',
                      production_accepted=False, six_hour_acceptance_passed=False)
        write_receipt(args.output, result)
        print(json.dumps(result, sort_keys=True))
        return 2
    finally:
        if queue is not None:
            queue.close()

if __name__ == '__main__':
    raise SystemExit(main())
