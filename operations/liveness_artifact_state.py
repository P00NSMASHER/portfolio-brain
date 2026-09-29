#!/usr/bin/env python3
"""Read the existing watchdog receipt for state reporting, never grant authority.

A current check and a state change are separate facts. This bridge preserves the
ledger bytes/timestamp and accepts only digest-checked main-watchdog artifacts.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from runtime.artifact_restore import _atomic_write
from runtime.artifact_state import BudgetedHTTP
from operations.workflow_liveness import _hash_value
from value_proof.strict_json import strict_json_loads

ARTIFACT_NAME='portfolio-workflow-liveness'
WORKFLOW_PATH='.github/workflows/portfolio-cost-watchdog.yml'
MEMBER='workflow_liveness_receipt.json'
MAX_BYTES=1_048_576


def _time(value):
    if not isinstance(value,str) or not value.endswith('Z'):
        raise ValueError('watchdog timestamp must be UTC')
    return datetime.fromisoformat(value[:-1]+'+00:00')


def validate_receipt(doc):
    required={'schema_version','status','checked_at','hard_stop_reason','dispatches',
              'targets','authority_granted','api_requests','verified_work_target_count'}
    if not isinstance(doc,dict) or not required<=set(doc) or set(doc)-required-{'cost_state_proof'}:
        raise ValueError('watchdog receipt schema invalid')
    if doc['schema_version']!='1.0.0' or doc['authority_granted'] is not False:
        raise ValueError('watchdog identity/authority invalid')
    _time(doc['checked_at'])
    if type(doc['api_requests']) is not int or not 0<=doc['api_requests']<=20:
        raise ValueError('watchdog API budget invalid')
    if not isinstance(doc['dispatches'],list) or len(doc['dispatches'])>2:
        raise ValueError('watchdog dispatch count invalid')
    if not isinstance(doc['targets'],list) or not 1<=len(doc['targets'])<=8:
        raise ValueError('watchdog targets invalid')
    names=[r.get('workflow_name') for r in doc['targets'] if isinstance(r,dict)]
    if len(names)!=len(doc['targets']) or any(not isinstance(n,str) or not n for n in names) or len(set(names))!=len(names):
        raise ValueError('watchdog target identity invalid')
    verified=sum(r.get('status')=='HEALTHY_VERIFIED_WORK' for r in doc['targets'])
    if type(doc['verified_work_target_count']) is not int or doc['verified_work_target_count']!=verified:
        raise ValueError('watchdog verified count invalid')
    if any(r.get('status')=='HEALTHY_VERIFIED_WORK' and r.get('work_proof_status')!='VERIFIED_WORK' for r in doc['targets']):
        raise ValueError('watchdog work proof missing')


def restore(output:Path, metadata_output:Path, *, http=None, now=None)->str:
    # Clear only the temporary projection. A failed read must not reuse old proof.
    output.unlink(missing_ok=True); metadata_output.unlink(missing_ok=True)
    repo=os.environ.get('GITHUB_REPOSITORY'); token=os.environ.get('GITHUB_TOKEN')
    if not repo or not token:
        return 'NO_ACTIONS_CONTEXT'
    now=now or datetime.now(timezone.utc)
    http=http or BudgetedHTTP(token,max_requests=6,retries=0,backoff=0,deadline=time.monotonic()+60)
    base=f'https://api.github.com/repos/{repo}'
    data=http.json(f'{base}/actions/artifacts?name={ARTIFACT_NAME}&per_page=100')
    rows=[r for r in data.get('artifacts',[]) if r.get('name')==ARTIFACT_NAME
          and r.get('expired') is False and r.get('workflow_run',{}).get('head_branch')=='main'
          and str(r.get('workflow_run',{}).get('id'))!=os.environ.get('GITHUB_RUN_ID')]
    rows.sort(key=lambda r:(r.get('created_at',''),r.get('id',0)),reverse=True)
    # Bounded read-only fallback; fresh invalid evidence is never manufactured.
    for row in rows[:2]:
        try:
            rid=row['workflow_run']['id']; aid=row['id']
            if type(rid) is not int or type(aid) is not int: raise ValueError('artifact identity invalid')
            run=http.json(f'{base}/actions/runs/{rid}')
            if not (run.get('id')==rid and run.get('path')==WORKFLOW_PATH
                    and run.get('head_branch')=='main' and run.get('head_sha')==row['workflow_run'].get('head_sha')
                    and run.get('status')=='completed' and run.get('conclusion')=='success'
                    and run.get('repository',{}).get('full_name')==repo
                    and run.get('head_repository',{}).get('full_name')==repo):
                raise ValueError('watchdog producer not verified')
            raw=http.bytes(f'{base}/actions/artifacts/{aid}/zip')
            if len(raw)>MAX_BYTES or row.get('digest')!='sha256:'+hashlib.sha256(raw).hexdigest():
                raise ValueError('watchdog archive integrity invalid')
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                members=[i for i in z.infolist() if i.filename==MEMBER and not i.is_dir()]
                if len(members)!=1 or members[0].file_size>MAX_BYTES: raise ValueError('watchdog member invalid')
                body=z.read(members[0])
            doc=strict_json_loads(body.decode('utf-8')); validate_receipt(doc)
            checked=_time(doc['checked_at']); created=_time(row['created_at'])
            if not (_time(run['run_started_at'])<=checked<=now
                    and checked<=_time(run['updated_at'])
                    and (created-checked).total_seconds()>=-2
                    and created>=_time(run['run_started_at'])):
                raise ValueError('watchdog receipt chronology invalid')
            meta={'restore_status':'RESTORED','artifact_id':aid,'source_run_id':rid,
                  'source_head_sha':run['head_sha'],'source_workflow':WORKFLOW_PATH,
                  'artifact_created_at':row['created_at'],'receipt_hash':_hash_value(doc)}
            _atomic_write(output,body)
            _atomic_write(metadata_output,(json.dumps(meta,sort_keys=True)+'\n').encode())
            return 'RESTORED'
        except (OSError,ValueError,KeyError,TypeError,RuntimeError,zipfile.BadZipFile):
            continue
    return 'NO_VALID_LIVENESS_ARTIFACT'


def load_verified(directory:Path, *, now, max_age_minutes=150):
    try:
        doc=strict_json_loads((directory/MEMBER).read_text())
        meta=json.loads((directory/'workflow_liveness_restore.json').read_text())
        validate_receipt(doc)
        age=(now-_time(doc['checked_at'])).total_seconds()/60
        if not (meta.get('restore_status')=='RESTORED' and meta.get('source_workflow')==WORKFLOW_PATH
                and type(meta.get('source_run_id')) is int
                and meta.get('receipt_hash')==_hash_value(doc) and 0<=age<=max_age_minutes):
            return None
        return doc
    except (OSError,ValueError,TypeError,KeyError):
        return None
