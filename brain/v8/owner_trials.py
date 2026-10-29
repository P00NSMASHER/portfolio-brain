"""Bounded original-source repair trials for the assigned project owner.

This entry point binds the shipped deterministic repair generator to an
observed, collision-free v8 handoff. It executes only the shipped fixed
regression in temporary local storage. No target code, provider mutation,
scheduler, merged PR, credential or production release is involved.
"""
from brain.core import digest, require
from brain.v8.engineering import build_cycle, exercise_repair


def trial_owner_repair(report, request, original, *, source_sha, cycle, now,
                       project_id):
    """Prove red/green for one real owner slot or fail before execution."""
    require(type(request) is dict and type(project_id) is str
            and type(original) is bytes, 'V8_REPAIR_TRIAL_INPUT_INVALID')
    plan = build_cycle(report, source_sha=source_sha, cycle=cycle, now=now)
    jobs = [job for job in plan['owner_jobs']
            if job['project_id'] == project_id
            and job['repository'] == request.get('repository')
            and job['expected_source_sha'] == request.get('source_head_sha')]
    require(len(jobs) == 1, 'V8_REPAIR_TRIAL_SOURCE_NOT_SELECTED')
    job = jobs[0]
    require(job['next_action'] == 'DIAGNOSE_REPRODUCE_AND_REPAIR'
            and job['reobserve_before_mutation'] is True
            and job['owner_runtime_access_verified'] is False
            and job['merge_or_deployment_authority'] is False,
            'V8_REPAIR_TRIAL_NOT_ADVERSE_OR_AUTHORIZED')
    evidence = exercise_repair(request, original)
    require(evidence['status'] == 'ISOLATED_RECIPE_RED_GREEN'
            and evidence['source_sha'] == job['expected_source_sha']
            and evidence['original_returncode'] != 0
            and evidence['corrected_returncode'] == 0
            and evidence['production_accepted'] is False
            and evidence['third_party_code_executed'] is False,
            'V8_REPAIR_TRIAL_EVIDENCE_INVALID')
    return dict(
        schema_version=1, status='SOURCE_BOUND_OWNER_TRIAL_RED_GREEN',
        scope='SHIPPED_LOCAL_FIXTURE_ONLY',
        project_id=project_id, repository=job['repository'],
        source_sha=job['expected_source_sha'], owner=job['owner'],
        work_id=job['work_id'], next_action=job['next_action'],
        original_returncode=evidence['original_returncode'],
        corrected_returncode=evidence['corrected_returncode'],
        patch_sha256=evidence['patch_sha256'],
        regression_sha256=evidence['test_sha256'],
        evidence_fingerprint=digest(dict(
            work_id=job['work_id'], request=request,
            patch_sha256=evidence['patch_sha256'],
            regression_sha256=evidence['test_sha256'])),
        independent_verification_contract=job['verification_contract'],
        provider_calls=0, target_code_executed=False,
        target_repository_modified=False, patch_published=False,
        production_accepted=False, independent_gate_passed=False,
        merge_or_deployment_authority=False)
