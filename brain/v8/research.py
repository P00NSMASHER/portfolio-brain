"""Bounded need-driven experiment routing; never executes discovered code."""
import re
from brain.core import digest,require
from brain.intelligence import related_test_paths
from brain.v8.contracts import HASH,matches

SOURCE=re.compile(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/blob/([0-9a-f]{40})/([^?#%\\\s]+)\Z')


def research_actions(projects,candidates,history):
    require(type(projects) is list and len(projects)<=16
            and type(candidates) is list and len(candidates)<=128
            and type(history) is list and len(history)<=256,'V8_RESEARCH_BOUND')
    suppressed=set()
    for row in history:
        require(type(row) is dict and set(row)=={'finding_id','outcome'}
                and matches(HASH,row['finding_id']) and type(row['outcome']) is str
                and row['outcome'] in {'FAILED','NOT_USEFUL','INTEGRATED','UNKNOWN'},
                'V8_RESEARCH_HISTORY_INVALID')
        if row['outcome']!='UNKNOWN': suppressed.add(row['finding_id'])
    result=[]
    seen=set()
    for p in projects:
        require(type(p) is dict and type(p.get('id')) is str
                and type(p.get('research_target')) is str,'V8_RESEARCH_PROJECT_INVALID')
        for c in candidates:
            if type(c) is not dict or c.get('target')!=p['research_target'] or c.get('freshness')!='CURRENT': continue
            ref=c.get('source_ref')
            m=SOURCE.fullmatch(ref) if type(ref) is str else None
            if not m or c.get('key')!=m[1]+':'+m[3] or any(x in {'.','..'} for x in m[3].split('/')): continue
            terms,paths=c.get('matched_terms'),c.get('test_paths')
            if not (type(terms) is list and len(terms)<=32 and all(type(t) is str and 0<len(t)<=80 for t in terms)
                    and len({t.lower() for t in terms})>=2 and type(paths) is list and len(paths)<=32
                    and all(type(path) is str and len(path)<=300 for path in paths)): continue
            if not related_test_paths(m[3],[{'path':path,'type':'blob'} for path in paths]): continue
            ident=digest(dict(project=p['id'],source_ref=ref))
            if ident in seen or ident in suppressed: continue
            seen.add(ident)
            result.append(dict(finding_id=ident,project_id=p['id'],source_ref=ref,
                next_action='VERIFY_SOURCE_BYTES_LICENSE_AND_PROJECT_EXPERIMENT',
                license_verified=False,source_identity_authenticated=False,
                independently_useful=False,third_party_execution_authorized=False))
    return dict(experiments=result[:5],deferred_count=max(0,len(result)-5),
                unavailable_is_not_no_opportunity=not bool(candidates),provider_calls=0)
