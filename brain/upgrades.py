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
from pathlib import Path
from brain.core import require, digest, utcnow, BrainError, timestamp
from brain.adapters import NoRedirect

REPOSITORY='P00NSMASHER/portfolio-brain'
PATH='brain/REUSE_KNOWLEDGE.json'

def build_knowledge(report):
    require(report['status']=='PASS', 'upgrade requires passing authoritative report')
    candidates=[c for c in report['reuse_candidates'] if c['data_kind']=='ACTUAL' and c['freshness']=='CURRENT' and c['test_paths'] and len(c['matched_terms'])>=2]
    require(len(candidates)>=3, 'INSUFFICIENT_UPGRADE_EVIDENCE: three real implementation-and-test sources required')
    sources=[]
    for c in sorted(candidates,key=lambda x:x['key'])[:12]:
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
        require(self.requests<=8, 'UPGRADE_REQUEST_BUDGET')
        require(path.startswith('/repos/'+REPOSITORY+'/') and '..' not in path.split('/'), 'self upgrade scope violation')
        # Precisely bounded GitHub mutations; no arbitrary repository/URL or force update.
        if method!='GET':
            suffix=path.split(REPOSITORY+'/')[1]
            require((method=='POST' and suffix in {'git/refs','pulls'}) or (method=='PUT' and suffix==f'contents/{PATH}'), 'upgrade mutation forbidden')
        if self.transport:return self.transport(path,method,payload)
        body=None if payload is None else json.dumps(payload).encode()
        request=urllib.request.Request('https://api.github.com'+path,data=body,method=method,headers={'Authorization':'Bearer '+self.token,'User-Agent':'PortfolioBrain-v2-protected-knowledge-upgrade','Accept':'application/vnd.github+json','Content-Type':'application/json'})
        with self.opener.open(request,timeout=10) as response:
            raw=response.read(1_000_001)
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
    latest=store.db.execute("SELECT created_at FROM attempts WHERE operation='evolve' ORDER BY id DESC LIMIT 1").fetchone()
    if latest and (timestamp(utcnow())-timestamp(latest[0])).total_seconds()<604800:
        return {'status':'COOLDOWN','source_sha':source_sha,'authority_widened':False}
    store.attempt('evolve','FAIL','PROPOSAL_STARTED',source_sha=source_sha)
    api=api or UpgradeAPI()
    main=api.request(f'/repos/{REPOSITORY}/branches/main')
    require(main['commit']['sha']==source_sha,'MAIN_DRIFT: upgrade source changed')
    fingerprint=knowledge['fingerprint']
    branch='factory/auto-repair-v2-knowledge-'+fingerprint[:16]
    pulls=api.request(f'/repos/{REPOSITORY}/pulls?state=open&head=P00NSMASHER:{branch}')
    if pulls:
        return {'status':'EXISTING_PR','url':pulls[0]['html_url'],'source_sha':source_sha,'authority_widened':False}
    old=api.request(f'/repos/{REPOSITORY}/contents/{PATH}?ref={source_sha}')
    api.request(f'/repos/{REPOSITORY}/git/refs','POST',{'ref':'refs/heads/'+branch,'sha':source_sha})
    encoded=base64.b64encode((json.dumps(knowledge,indent=2,sort_keys=True)+'\n').encode()).decode()
    result=api.request(f'/repos/{REPOSITORY}/contents/{PATH}','PUT',{'message':'Update evidence-bound reusable code knowledge','branch':branch,'sha':old['sha'],'content':encoded})
    head=result['commit']['sha']
    require(re.fullmatch('[0-9a-f]{40}',head),'upgrade commit identity missing')
    body=f'''Refresh the Brain's reusable-code knowledge from independently hash-inspected public implementations and observed test paths. This does not execute source, claim production usefulness, grant rights, or claim revenue.

AUTO_REPAIR_FINGERPRINT: {fingerprint}

Source main: `{source_sha}`. Candidate head: `{head}`. Existing exact-head Foundation and App 5121826 remain mandatory. The trusted verifier alone may merge through repository protections; this worker never invokes merge or pushes main.'''
    pr=api.request(f'/repos/{REPOSITORY}/pulls','POST',{'head':branch,'base':'main','title':'Brain v2: refresh evidence-bound reuse knowledge','body':body})
    store.attempt('evolve','PASS',source_sha=source_sha,details={'pr_number':pr['number'],'head_sha':head})
    return {'status':'CANDIDATE_PR_CREATED','url':pr['html_url'],'head_sha':head,'source_sha':source_sha,'independent_review':'PENDING','authority_widened':False}
