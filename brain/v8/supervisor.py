"""Read-only supervision recommendations for the existing independent watchdog."""
from brain.core import require
from brain.v8.contracts import SHA,matches,parse_utc
from brain.operational_outcomes import ADVERSE,CONCLUSIONS,STATUSES


def supervise(inventory, *, source_sha, now):
    current=parse_utc(now)
    require(matches(SHA,source_sha) and type(inventory) is dict
            and set(inventory)=={'total_count','workflow_runs'}
            and type(inventory['total_count']) is int and inventory['total_count']>=0
            and type(inventory['workflow_runs']) is list and len(inventory['workflow_runs'])<=100,
            'V8_SUPERVISOR_INVENTORY_INVALID')
    result=dict(status='INCOMPLETE_INVENTORY',next_action='FETCH_ORIGINAL_COMPLETE_CENSUS',
                source_sha=source_sha,production_accepted=False,automatic_action_executed=False)
    if inventory['total_count']!=len(inventory['workflow_runs']): return result
    relevant=[]
    unverified_scope=False
    seen=set()
    for row in inventory['workflow_runs']:
        require(type(row) is dict and type(row.get('id')) is int and row['id']>0
                and row['id'] not in seen and matches(SHA,row.get('head_sha'))
                and type(row.get('status')) is str and row['status'] in STATUSES and type(row.get('run_attempt')) is int
                and row['run_attempt']>=1,'V8_SUPERVISOR_RUN_INVALID')
        seen.add(row['id'])
        created,end=map(parse_utc,(row['created_at'],row['updated_at']))
        require(created<=end<=current,'V8_SUPERVISOR_TIME_INVALID')
        require((row['status']=='completed' and type(row.get('conclusion')) is str and row['conclusion'] in CONCLUSIONS)
                or (row['status']!='completed' and row.get('conclusion') is None),
                'V8_SUPERVISOR_CONCLUSION_INVALID')
        if row.get('name')=='brain-cycle-v2' and row['head_sha']==source_sha:
            if (row.get('path')!='.github/workflows/brain-cycle.yml'
                    or row.get('head_branch')!='main'
                    or type(row.get('repository')) is not dict
                    or row['repository'].get('full_name')!='P00NSMASHER/portfolio-brain'):
                unverified_scope=True
                continue
            relevant.append((row,end))
    if any(row['run_attempt']>1 for row,end in relevant):
        result.update(status='ATTEMPT_CENSUS_REQUIRED',next_action='FETCH_EVERY_ORIGINAL_ATTEMPT')
    elif any(row['conclusion'] in ADVERSE for row,end in relevant):
        result.update(status='ADVERSE_ORIGINAL_RUN',next_action='DIAGNOSE_ORIGINAL_FAILURE')
    elif any(row['status']!='completed' and (current-end).total_seconds()<=5400 for row,end in relevant):
        result.update(status='CORE_IN_PROGRESS',next_action='WAIT_FOR_ORIGINAL_RUN')
    elif any(row['conclusion']=='success' and row.get('event')=='schedule'
             and (current-end).total_seconds()<=5400 for row,end in relevant):
        result.update(status='RECENT_CORE_OBSERVED',next_action='VERIFY_ORIGINAL_PROVENANCE_AND_STATE')
    elif any(row.get('event')=='workflow_dispatch' and (current-end).total_seconds()<=5400 for row,end in relevant):
        result.update(status='AUTOMATIC_ORIGIN_UNVERIFIED',next_action='VERIFY_ORIGINAL_AUTOMATIC_ORIGIN')
    elif unverified_scope:
        result.update(status='CORE_SCOPE_UNVERIFIED',next_action='VERIFY_ORIGINAL_WORKFLOW_MAIN_AND_REPOSITORY')
    else:
        result.update(status='CORE_STALLED_OR_UNOBSERVED',next_action='USE_EXISTING_WATCHDOG')
    return result
