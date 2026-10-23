"""Pure, source-bound routing to existing 15-task specialist lanes.

No task creation, provider API call, code execution or release authority.
Unknown identities fail closed, and each owner receives at most one concurrent
proposed assignment in a cycle.
"""
from brain.v9.batch_queue import BatchFault, PROJECTS, hashval, valid_path

KINDS=frozenset({'PRODUCTION_INCIDENT','SECURITY','DATA_ACCURACY',
                  'USER_EXPERIENCE','FEATURE','RESEARCH','CHECK_EVIDENCE_TRIAGE'})
VERIFIERS={
 'brain-reliability':'brain-qa','brain-engineering':'brain-qa',
 'portfolio-security':'brain-qa','abvm-sources':'portfolio-security',
 'abvm-guides':'portfolio-security','abvm-learning':'portfolio-security',
 'abvm-reliability':'portfolio-security','retally-product':'retally-qa',
 'retally-evidence':'retally-qa','retally-website':'retally-qa',
 'retally-qa':'portfolio-security','research-provenance':'portfolio-security'
}

def route_defect(*,project_id,repository,source_sha,path,kind):
    if (type(project_id) is not str or project_id not in PROJECTS or
            repository!=PROJECTS[project_id] or not hashval(source_sha,40)):
        raise BatchFault('ROUTING_IDENTITY_INVALID')
    if type(kind) is not str or kind not in KINDS or not valid_path(path):
        raise BatchFault('ROUTING_INPUT_INVALID')
    p=path.casefold()
    if kind=='SECURITY' or p.startswith('verification/'):
        owner='portfolio-security'
    elif project_id=='portfolio-brain':
        owner=('brain-reliability' if kind in ('PRODUCTION_INCIDENT','CHECK_EVIDENCE_TRIAGE') or
               p.startswith(('brain/core.py','brain/state_','brain/watchdog','brain/intelligence.py'))
               else 'brain-engineering')
    elif project_id=='abvm':
        if any(x in p for x in ('teacher','homework','school-calendar','school-data','curriculum-source')):
            owner='abvm-sources'
        elif any(x in p for x in ('mastery','learner','recommendation','scoring')):
            owner='abvm-learning'
        elif any(x in p for x in ('worksheet','study-guide','study-universe','practice-question')):
            owner='abvm-guides'
        else:
            owner='abvm-reliability'
    elif project_id=='research-labs':
        owner='research-provenance'
    elif any(x in p for x in ('lab/','benchmark','adjudication','evidence/')):
        owner='retally-evidence'
    elif p.startswith(('website/','web/','pages/','components/','public/')):
        owner='retally-website'
    elif p.startswith(('tests/security/','qa/')):
        owner='retally-qa'
    else:
        owner='retally-product'
    return dict(project_id=project_id,repository=repository,source_sha=source_sha,
                path=path,defect_kind=kind,owner=owner,verifier=VERIFIERS[owner],
                source_reobservation_required=True,
                automatic_execution_authority=False,provider_writes=0)

def select_distinct_owners(entries,*,limit=5,cycle=0):
    if (type(entries) is not list or len(entries)>256 or
            type(limit) is not int or not 1<=limit<=5 or
            type(cycle) is not int or cycle<0):
        raise BatchFault('ROUTING_BOUND')
    for e in entries:
        if (type(e) is not dict or not {'owner','repository','path','source_sha','priority'}<=set(e)
                or type(e['owner']) is not str or e['owner'] not in VERIFIERS
                or type(e['repository']) is not str or not valid_path(e['path'])
                or not hashval(e['source_sha'],40) or
                type(e['priority']) is not int or not 0<=e['priority']<=4):
            raise BatchFault('ROUTING_ENTRY_INVALID')
    ordered=sorted(entries,key=lambda e:(e['priority'],e['repository'].casefold(),e['path'],e['source_sha']))
    selected=[];deferred=[];owners=set();resources=set()
    for priority in range(5):
        tier=[e for e in ordered if e['priority']==priority]
        if tier:
            offset=cycle%len(tier);tier=tier[offset:]+tier[:offset]
        for e in tier:
            resource=(e['repository'].casefold(),e['path'].casefold())
            if (len(selected)>=limit or e['owner'] in owners
                    or resource in resources):
                deferred.append(e)
                continue
            selected.append(e);owners.add(e['owner']);resources.add(resource)
    return dict(selected=selected,deferred=deferred,
                automatic_execution_authority=False)
