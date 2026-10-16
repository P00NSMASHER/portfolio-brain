"""One engineering entry point: existing recipes, kernel planning and owner handoffs."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
from brain.core import digest,require
from brain.repair_patch_executor import generate
from brain.v8.contracts import SHA,matches,parse_utc
from brain.v8.inventory import project_maps
from brain.v8.planning import select_work


def prepare_repair(request,original_bytes):
    patch=generate(request,original_bytes)
    return dict(patch=patch,verification_contract='isolated negative/positive regression, exact-head CI, independent checks, source-pinned production verification',
                next_action='EXISTING_AUTHORIZED_PROJECT_OWNER',runtime_actions_executed=0,
                production_accepted=False)


def exercise_repair(request,original_bytes):
    """Run only the shipped deterministic regression, never provider YAML/code."""
    artifact=prepare_repair(request,original_bytes)
    patch=artifact['patch']
    with tempfile.TemporaryDirectory(prefix='brain-v8-recipe-') as folder:
        root=Path(folder)
        target=root/patch['source_path']
        test=root/patch['test_path']
        target.parent.mkdir(parents=True)
        test.parent.mkdir(parents=True)
        target.write_bytes(original_bytes)
        test.write_text(patch['test_content'],encoding='utf-8')
        def run():
            return subprocess.run([sys.executable,'-I',str(test)],cwd=root,
                capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin'}).returncode
        before=run()
        target.write_text(patch['changed_content'],encoding='utf-8')
        after=run()
    require(before!=0 and after==0,'V8_RECIPE_NEGATIVE_POSITIVE_CONTROL_FAILED')
    return dict(status='ISOLATED_RECIPE_RED_GREEN',source_sha=patch['source_head_sha'],
                patch_sha256=patch['changed_sha256'],test_sha256=patch['test_sha256'],
                original_returncode=before,corrected_returncode=after,
                production_accepted=False,third_party_code_executed=False)


def build_cycle(report, *, source_sha,cycle,now):
    require(matches(SHA,source_sha) and type(report) is dict
            and report.get('source_sha')==source_sha and type(report.get('projects')) is list,
            'V8_ENGINEERING_SOURCE_INVALID')
    parse_utc(now)
    maps=project_maps(report['projects'])
    work=[]
    gaps=[]
    for row in maps:
        if row['source_sha'] is None:
            gaps.append(dict(project_id=row['project_id'],owner=row['owner'],reason='PROJECT_SOURCE_UNOBSERVED',
                             next_action='OBSERVE_CURRENT_SOURCE_BEFORE_EDIT'))
            continue
        state=row['source_check_state']
        if state=='ADVERSE_CHECKS_OBSERVED': tier,action=1,'DIAGNOSE_REPRODUCE_AND_REPAIR'
        elif state!='NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL': tier,action=2,'VERIFY_CURRENT_SOURCE_AND_RUNTIME'
        else: tier,action=3,'RESEARCH_AND_TEST_USEFUL_UPGRADE'
        fingerprint=digest(dict(project=row['project_id'],check_state=state,operation=action))
        item=dict(schema_version=1,project_id=row['project_id'],repository=row['repository'],
            source_sha=row['source_sha'],fingerprint=fingerprint,owner=row['owner'],
            resource=digest(dict(repository=row['repository'])),state='OBSERVED',priority_tier=tier,
            evidence_ids=[digest(dict(project=row['project_id'],source=row['source_sha'],check_state=state))],
            dependencies=[],created_at=now,updated_at=now,attempts=0,blocker=None)
        item['work_id']='work:'+digest({k:item[k] for k in ('project_id','repository','source_sha','fingerprint')})
        work.append(item)
    plan=select_work(work,cycle=cycle,limit=5)
    by_id={r['project_id']:r for r in maps}
    jobs=[]
    for item in plan['selected']:
        contract=by_id[item['project_id']]
        jobs.append(dict(work_id=item['work_id'],project_id=item['project_id'],repository=item['repository'],
            expected_source_sha=item['source_sha'],owner=item['owner'],
            next_action={1:'DIAGNOSE_REPRODUCE_AND_REPAIR',2:'VERIFY_CURRENT_SOURCE_AND_RUNTIME',3:'RESEARCH_AND_TEST_USEFUL_UPGRADE'}[item['priority_tier']],
            verification_contract=contract['verification_contract'],reobserve_before_mutation=True,
            owner_runtime_access_verified=False,merge_or_deployment_authority=False))
    return dict(schema_version=1,source_sha=source_sha,cycle=cycle,
        status='OWNER_BRIDGE_READY_WITH_GAPS' if gaps else 'OWNER_BRIDGE_READY',
        project_maps=maps,work_items=work,owner_jobs=jobs,coverage_gaps=gaps,
        coverage=dict(registered=len(maps),observed=len(work),missing=len(gaps)),
        source_freshness='REOBSERVE_BEFORE_OWNER_ACTION',provider_calls=0,runtime_actions_executed=0,
        production_accepted=False,automatic_execution_authority=False,
        source_report_sha256=digest(report))
