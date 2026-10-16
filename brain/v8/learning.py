"""Private durable reported outcomes; claimed actuals are not authenticated successes."""
from brain.core import digest,require
from brain.v8.contracts import SHA,HASH,matches,parse_utc
from brain.v8.inventory import CONTRACTS
from brain.v8.private_state import PrivateFiles

FIELDS={'schema_version','project_id','source_sha','attempt_id','outcome','data_kind','evidence_id','observed_at'}


def record_outcome(private_root,record):
    require(type(record) is dict and set(record)==FIELDS
            and type(record['schema_version']) is int and record['schema_version']==1
            and type(record['project_id']) is str and record['project_id'] in CONTRACTS
            and matches(SHA,record['source_sha']) and matches(HASH,record['attempt_id'])
            and matches(HASH,record['evidence_id']) and type(record['outcome']) is str and record['outcome'] in
            {'FAILED','ROLLED_BACK','LIVE_VERIFIED','UNKNOWN','NOT_USEFUL'}
            and type(record['data_kind']) is str and record['data_kind'] in {'ACTUAL','SIMULATED','ESTIMATED','UNKNOWN'},
            'V8_OUTCOME_RECORD_INVALID')
    parse_utc(record['observed_at'])
    ident=digest({k:record[k] for k in ('project_id','source_sha','attempt_id')})
    files=PrivateFiles(private_root)
    with files.lock():
        old=files.read('outcome',ident)
        require(old is None or old==record,'V8_OUTCOME_CONFLICT')
        if old is None: files.write('outcome',ident,record)
        rows=files.records('outcome')
    return dict(record_id=ident,counts=dict(observed=len(rows),
        failed=sum(r['outcome']=='FAILED' for r in rows),
        rolled_back=sum(r['outcome']=='ROLLED_BACK' for r in rows),
        actual_live_verified=0,
        reported_actual_live=sum(r['outcome']=='LIVE_VERIFIED' and r['data_kind']=='ACTUAL' for r in rows),
        unknown=sum(r['outcome']=='UNKNOWN' or r['data_kind']=='UNKNOWN' for r in rows)),
        evidence_authentication='REQUIRES_INDEPENDENT_PROVIDER_ADAPTER',causal_benefit=None,
        production_accepted=False)
