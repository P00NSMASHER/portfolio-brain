"""Read-only API-bound verification of one *native scheduled* Brain cycle.

This cannot start a cycle, change state, or pronounce the two-hour soak passed.
Use only an existing run ID; every fact is fetched anew from GitHub's API.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from urllib import error, request
import zipfile

from soak_v3.audit import EvidenceError, REQUIRED_STEPS, require, sha40, verify_artifact, verify_sqlite

REPO = 'P00NSMASHER/portfolio-brain'
API = 'https://api.github.com/repos/' + REPO

class DropCredentialRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(newurl.startswith('https://'), 'REDIRECT_NOT_HTTPS')
        # Never forward the GitHub token or Authorization to storage hosts.
        return request.Request(newurl, headers={'User-Agent':'Mozilla/5.0', 'Accept':'application/zip'})

class GitHubReadOnly:
    def __init__(self, token, *, transport=None):
        require(isinstance(token, str) and len(token)>0 or transport is not None, 'GITHUB_TOKEN_REQUIRED')
        self.token=token
        self.transport=transport
        self.calls=0
        self.opener=request.build_opener(DropCredentialRedirect())
    def get(self, suffix, *, limit=2_000_000):
        require(type(suffix) is str and suffix.startswith('/') and '://' not in suffix and '..' not in suffix.split('/'), 'API_PATH_INVALID')
        self.calls+=1
        require(self.calls<=12, 'API_CALL_BUDGET')
        if self.transport:
            return self.transport(suffix)
        req=request.Request(API+suffix,headers={'Authorization':'Bearer '+self.token,
            'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28',
            'User-Agent':'PortfolioBrain-soak-v3-readonly'},method='GET')
        try:
            with self.opener.open(req,timeout=15) as resp:
                raw=resp.read(limit+1)
        except (error.URLError, TimeoutError, OSError):
            raise EvidenceError('GITHUB_API_UNAVAILABLE') from None
        require(0<len(raw)<=limit,'API_RESPONSE_SIZE_INVALID')
        return raw
    def json(self, suffix):
        try:
            obj=json.loads(self.get(suffix))
        except (ValueError, TypeError) as exc:
            raise EvidenceError('API_JSON_INVALID') from exc
        require(type(obj) is dict,'API_JSON_OBJECT_REQUIRED')
        return obj

def git_blob_hash(content):
    return hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()

def verify_native_run(api, run_id, source_sha):
    require(type(run_id) is int and run_id>0,'RUN_ID_INVALID')
    sha40(source_sha)
    live=api.json(f'/actions/runs/{run_id}')
    require(live.get('id')==run_id and live.get('event')=='schedule', 'NATIVE_SCHEDULE_EVENT_NOT_VERIFIED')
    require(live.get('head_sha')==source_sha and live.get('head_branch')=='main', 'NATIVE_RUN_SOURCE_NOT_VERIFIED')
    require(live.get('status')=='completed' and live.get('conclusion')=='success' and live.get('run_attempt')==1, 'NATIVE_RUN_FAILED_OR_RETRIED')
    main=api.json('/branches/main')
    require(main.get('commit',{}).get('sha')==source_sha, 'CURRENT_MAIN_DRIFT')
    jobs=api.json(f'/actions/runs/{run_id}/jobs?per_page=100')
    require(jobs.get('total_count')==1 and len(jobs.get('jobs',[]))==1,'NATIVE_JOBS_INCOMPLETE')
    job=jobs['jobs'][0]
    require(job.get('name')=='monitor' and job.get('status')=='completed' and job.get('conclusion')=='success','NATIVE_MONITOR_JOB_FAILED')
    steps={s['name']:s['conclusion'] for s in job.get('steps',[]) if isinstance(s,dict) and 'name' in s}
    require(all(steps.get(k)=='success' for k in REQUIRED_STEPS),'NATIVE_REQUIRED_STEP_FAILED')
    archives=api.json(f'/actions/runs/{run_id}/artifacts?per_page=100')
    items=archives.get('artifacts',[])
    require(type(items) is list and len(items)==1, 'ARTIFACTS_INCOMPLETE_OR_AMBIGUOUS')
    artifact=items[0]
    require(artifact.get('expired') is False and artifact.get('workflow_run',{}).get('id')==run_id and artifact.get('workflow_run',{}).get('head_sha')==source_sha,'ARTIFACT_RUN_IDENTITY_MISMATCH')
    require(artifact.get('name')==f'brain-v2-cycle-{source_sha}-{run_id}-1','ARTIFACT_NAME_MISMATCH')
    return artifact

def verify_baseline(api, run_id, source_sha):
    artifact=verify_native_run(api,run_id,source_sha)
    zip_bytes=api.get(f'/actions/artifacts/{artifact["id"]}/zip',limit=20_000_000)
    require(len(zip_bytes)<=20_000_000,'ARTIFACT_TOO_LARGE')
    require('sha256:'+hashlib.sha256(zip_bytes).hexdigest()==artifact.get('digest'),'ARTIFACT_API_DIGEST_MISMATCH')
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            delivery=json.loads(z.read('delivery.json'))
    except (ValueError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise EvidenceError('DELIVERY_RECEIPT_MISSING') from exc
    state_commit=sha40(delivery.get('state_commit'))
    state_parent=sha40(delivery.get('state_parent'))
    snapshot=api.json(f'/contents/state.sqlite?ref={state_commit}')
    require(snapshot.get('encoding')=='base64' and type(snapshot.get('content')) is str,'STATE_BLOB_UNAVAILABLE')
    try:
        state_bytes=base64.b64decode(snapshot['content'],validate=False)
    except ValueError as exc:
        raise EvidenceError('STATE_BLOB_DECODE_INVALID') from exc
    require(git_blob_hash(state_bytes)==snapshot.get('sha'),'STATE_GIT_BLOB_IDENTITY_INVALID')
    with tempfile.TemporaryDirectory() as temp:
        archive_path=Path(temp)/'run.zip'
        state_path=Path(temp)/'state.sqlite'
        archive_path.write_bytes(zip_bytes)
        state_path.write_bytes(state_bytes)
        zip_proof=verify_artifact(archive_path,artifact['digest'],run_id=run_id,source_sha=source_sha,
                                  state_parent=state_parent,state_commit=state_commit)
        state_proof=verify_sqlite(state_path,expected_sequence=zip_proof['state_sequence'],
                                  expected_chain=zip_proof['canonical_hash'],expected_source=source_sha)
    return {'status':'NATIVE_BASELINE_VERIFIED','soak_pass':False,'run_id':run_id,
            'source_sha':source_sha,'artifact_id':artifact['id'],
            'artifact_digest':artifact['digest'],'state_parent':state_parent,
            'state_commit':state_commit,'state_sequence':state_proof['sequence'],
            'canonical_hash':state_proof['canonical_hash'],
            'sqlite_sha256':state_proof['sha256'],'pending_events':0,
            'remote_blob_sha':snapshot['sha']}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-id',type=int,required=True)
    parser.add_argument('--source-sha',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        result=verify_baseline(GitHubReadOnly(os.environ.get('GITHUB_TOKEN','')),args.run_id,args.source_sha)
    except (EvidenceError, KeyError, TypeError, OSError) as exc:
        result={'status':'BLOCKED','soak_pass':False,'reason':str(exc)[:200]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='NATIVE_BASELINE_VERIFIED' else 1

if __name__=='__main__':
    raise SystemExit(main())
