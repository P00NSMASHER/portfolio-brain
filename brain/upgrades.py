"""Bounded autonomous knowledge upgrades through the existing protected PR gate.

No arbitrary generated code, main pushes, independent-gate bypass, or downstream
writes. External code stays unexecuted. New evidence must be real, fresh, hashed,
and contain inspected implementation plus structural tests before a proposal.
"""
import base64
import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from brain.core import require, digest, utcnow, BrainError, timestamp
from brain.adapters import NoRedirect, related_test_paths

REPOSITORY='P00NSMASHER/portfolio-brain'
PATH='brain/REUSE_KNOWLEDGE.json'
VALIDATION='actions/workflows/foundation-ci.yml/dispatches'
BRANCH=re.compile(r'factory/auto-repair-v2-knowledge-[0-9a-f]{16}')

def balanced_knowledge_sources(candidates, limit=12):
    """Round-robin prequalified sources by project target, with stable key order.

    All eligibility checks still happen in build_knowledge. This only prevents
    one alphabetically early project from crowding out other eligible projects.
    No scoring probability, license grant, execution or authority is inferred.
    """
    require(type(limit) is int and 1 <= limit <= 12, 'knowledge source limit invalid')
    buckets = {}
    for candidate in sorted(candidates, key=lambda c: (c['target'], c['key'])):
        buckets.setdefault(candidate['target'], []).append(candidate)
    selected = []
    for offset in range(max((len(group) for group in buckets.values()), default=0)):
        for target in sorted(buckets):
            if offset < len(buckets[target]):
                selected.append(buckets[target][offset])
                if len(selected) == limit:
                    return selected
    return selected

def build_knowledge(report):
    require(report['status']=='PASS', 'upgrade requires passing authoritative report')
    candidates=[]
    for c in report['reuse_candidates']:
        # Persisted candidates may predate retrieval fixes. Recheck association
        # before granting upgrade eligibility, without rewriting historical facts.
        tests=related_test_paths(c['path'],[{'path':p,'type':'blob'} for p in c['test_paths']])
        if c['data_kind']=='ACTUAL' and c['freshness']=='CURRENT' and tests and len(c['matched_terms'])>=2:
            candidates.append({**c,'test_paths':tests})
    require(len(candidates)>=3, 'INSUFFICIENT_UPGRADE_EVIDENCE: three real implementation-and-test sources required')
    sources=[]
    for c in balanced_knowledge_sources(candidates):
        sources.append({key:c[key] for key in ('key','repository','head_sha','path','blob_sha','code_sha256','test_paths','license','source_ref','target','matched_terms')})
    # No private names, code, payloads, or subjective revenue claim in public upgrades.
    return {'schema_version':2,'scope':'STRUCTURAL_REUSE_KNOWLEDGE_NOT_EXECUTED_OR_REVENUE_VERIFIED','sources':sources,'fingerprint':digest(sources)}

class UpgradeAPI:
    def __init__(self, token=None, transport=None):
        self.token=token or os.environ.get('GITHUB_TOKEN','')
        require(self.token or transport, 'UPGRADE_TOKEN_UNAVAILABLE')
        self.transport=transport
        self.requests=0
        self.opener=urllib.request.build_opener(NoRedirect())
    def request(self,path,method='GET',payload=None):
        self.requests+=1
        require(self.requests<=10, 'UPGRADE_REQUEST_BUDGET')
        require(path.startswith('/repos/'+REPOSITORY+'/') and '..' not in path.split('/'), 'self upgrade scope violation')
        # Precisely bounded GitHub mutations; no arbitrary repository/URL or force update.
        if method!='GET':
            suffix=path.split(REPOSITORY+'/')[1]
            require((method=='POST' and suffix in {'git/refs','pulls',VALIDATION}) or (method=='PUT' and suffix==f'contents/{PATH}'), 'upgrade mutation forbidden')
            require(type(payload) is dict, 'upgrade payload invalid')
            if suffix=='git/refs':
                require(set(payload)=={'ref','sha'} and payload['ref'].startswith('refs/heads/') and BRANCH.fullmatch(payload['ref'][11:]) and re.fullmatch('[0-9a-f]{40}',payload['sha']), 'upgrade ref forbidden')
            if suffix==f'contents/{PATH}':
                require(set(payload)=={'message','branch','sha','content'} and BRANCH.fullmatch(payload['branch']) and re.fullmatch('[0-9a-f]{40}',payload['sha']), 'upgrade content target forbidden')
            if suffix=='pulls':
                require(set(payload)=={'head','base','title','body'} and BRANCH.fullmatch(payload['head']) and payload['base']=='main' and 'AUTO_REPAIR_FINGERPRINT:' in payload['body'], 'upgrade pull target forbidden')
            if suffix==VALIDATION:
                require(set(payload)=={'ref'} and BRANCH.fullmatch(payload['ref']), 'upgrade validation ref forbidden')
        if self.transport:return self.transport(path,method,payload)
        body=None if payload is None else json.dumps(payload).encode()
        request=urllib.request.Request('https://api.github.com'+path,data=body,method=method,headers={'Authorization':'Bearer '+self.token,'User-Agent':'PortfolioBrain-v2-protected-knowledge-upgrade','Accept':'application/vnd.github+json','Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=10) as response:
                raw=response.read(1_000_001)
        except urllib.error.HTTPError as exc:
            raise BrainError(f'UPGRADE_API_{exc.code}: {method} {path.split(REPOSITORY+"/")[1]}; proposal remains unaccepted') from None
        require(len(raw)<=1_000_000,'upgrade response too large')
        return json.loads(raw) if raw else {}

def evolve(store,source_sha, *, api=None):
    require(store.visibility=='PUBLIC','private state cannot be published as a self upgrade')
    report=store.read_report(source_sha)
    try: knowledge=build_knowledge(report)
    except BrainError as exc:
        return {'status':'NO_CANDIDATE','reason':str(exc),'source_sha':source_sha,'authority_widened':False}
    current=json.loads((Path(__file__).parent/'REUSE_KNOWLEDGE.json').read_text())
    if current.get('fingerprint')==knowledge['fingerprint']:
        return {'status':'UNCHANGED','source_sha':source_sha,'authority_widened':False}
    # One proposal per week, including failed attempts. No speculative repair loop.
    fingerprint=knowledge['fingerprint']
    latest=store.db.execute("SELECT * FROM attempts WHERE operation='evolve' ORDER BY id DESC LIMIT 1").fetchone()
    recovering=False
    if latest and (timestamp(utcnow())-timestamp(latest['created_at'])).total_seconds()<604800:
        proposal=store.db.execute("SELECT * FROM attempts WHERE operation='evolve' AND json_extract(details,'$.fingerprint')=? ORDER BY id DESC LIMIT 1",(fingerprint,)).fetchone()
        recovering=bool(proposal and proposal['source_sha']==source_sha and proposal['status']=='FAIL' and json.loads(proposal['details']).get('phase')=='PROPOSAL_STARTED' and (timestamp(utcnow())-timestamp(proposal['created_at'])).total_seconds()>=3600)
        if not recovering:
            return {'status':'COOLDOWN','source_sha':source_sha,'authority_widened':False}
    branch='factory/auto-repair-v2-knowledge-'+fingerprint[:16]
    store.attempt('evolve','FAIL','RECOVERY_STARTED' if recovering else 'PROPOSAL_STARTED',source_sha=source_sha,details={'fingerprint':fingerprint,'branch':branch,'phase':'RECOVERY_STARTED' if recovering else 'PROPOSAL_STARTED'})
    api=api or UpgradeAPI()
    main=api.request(f'/repos/{REPOSITORY}/branches/main')
    require(main['commit']['sha']==source_sha,'MAIN_DRIFT: upgrade source changed')
    pulls=api.request(f'/repos/{REPOSITORY}/pulls?state=open&head=P00NSMASHER:{branch}')
    require(len(pulls)<=1,'upgrade PR identity ambiguous')
    old=api.request(f'/repos/{REPOSITORY}/contents/{PATH}?ref={source_sha}')
    try:
        existing=api.request(f'/repos/{REPOSITORY}/branches/{branch}')
    except BrainError as exc:
        require(str(exc).startswith('UPGRADE_API_404'),'upgrade branch lookup failed')
        require(not pulls,'upgrade PR lost its branch')
        api.request(f'/repos/{REPOSITORY}/git/refs','POST',{'ref':'refs/heads/'+branch,'sha':source_sha})
        existing={'commit':{'sha':source_sha}}
    encoded=base64.b64encode((json.dumps(knowledge,indent=2,sort_keys=True)+'\n').encode()).decode()
    head=existing['commit']['sha']
    if head==source_sha:
        require(not pulls,'upgrade PR exists before candidate content')
        result=api.request(f'/repos/{REPOSITORY}/contents/{PATH}','PUT',{'message':'Update evidence-bound reusable code knowledge','branch':branch,'sha':old['sha'],'content':encoded})
        head=result['commit']['sha']
    else:
        comparison=api.request(f'/repos/{REPOSITORY}/compare/{source_sha}...{head}')
        require(comparison['merge_base_commit']['sha']==source_sha and [f['filename'] for f in comparison['files']]==[PATH],'upgrade recovery branch drift')
        saved=api.request(f'/repos/{REPOSITORY}/contents/{PATH}?ref={head}')
        require(saved.get('encoding')=='base64' and json.loads(base64.b64decode(saved['content']))==knowledge,'upgrade recovery content mismatch')
    require(re.fullmatch('[0-9a-f]{40}',head),'upgrade commit identity missing')
    body=f'''Refresh the Brain's reusable-code knowledge from independently hash-inspected public implementations and observed test paths. This does not execute source, claim production usefulness, grant rights, or claim revenue.

AUTO_REPAIR_FINGERPRINT: {fingerprint}

Source main: `{source_sha}`. Candidate head: `{head}`. Existing exact-head Foundation and App 5121826 remain mandatory. The trusted verifier alone may merge through repository protections; this worker never invokes merge or pushes main.'''
    if pulls:
        pr=pulls[0]
        require(pr['head']['sha']==head and pr['head']['ref']==branch and pr['head']['repo']['full_name']==REPOSITORY and pr['base']['ref']=='main' and pr['user']['login']=='github-actions[bot]','upgrade existing PR identity mismatch')
    else:
        pr=api.request(f'/repos/{REPOSITORY}/pulls','POST',{'head':branch,'base':'main','title':'Brain v2: refresh evidence-bound reuse knowledge','body':body})
    # Token-created PR events may require approval. Explicitly dispatch the existing
    # Foundation entry point once; its exact-head independent verifier stays mandatory.
    api.request(f'/repos/{REPOSITORY}/{VALIDATION}','POST',{'ref':branch})
    store.attempt('evolve','PASS',source_sha=source_sha,details={'pr_number':pr['number'],'head_sha':head,'fingerprint':fingerprint,'phase':'VALIDATION_DELIVERED'})
    return {'status':'CANDIDATE_PR_CREATED','url':pr['html_url'],'head_sha':head,'source_sha':source_sha,'validation_dispatch':'DELIVERED','independent_review':'PENDING','authority_widened':False}
