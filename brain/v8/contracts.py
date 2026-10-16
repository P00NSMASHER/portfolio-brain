"""Source-bound local records. Supplied records do not prove provider authority."""
from copy import deepcopy
from datetime import datetime
import re
from brain.core import digest, require
from brain.intelligence import REPO

ID = re.compile(r'[A-Za-z0-9_.-]{1,80}\Z')
SHA = re.compile(r'[0-9a-f]{40}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
WORK_ID = re.compile(r'work:[0-9a-f]{64}\Z')
UTC = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z')
LOCAL_STATES = ('OBSERVED','DIAGNOSED','REPRODUCED','PATCHED','TESTED')
RELEASE_STATES = {'INDEPENDENTLY_VERIFIED','RELEASE_ELIGIBLE','RELEASED',
                  'LIVE_VERIFIED','MONITORED','LEARNED'}
STOP_STATES = {'BLOCKED','FAILED','ROLLBACK_REQUIRED'}
WORK_FIELDS = {'schema_version','work_id','project_id','repository','source_sha',
               'fingerprint','owner','resource','state','priority_tier','evidence_ids',
               'dependencies','created_at','updated_at','attempts','blocker'}
CAP_FIELDS = {'schema_version','executor','repository','resource','action','status',
              'evidence_id','observed_at','expires_at'}
BLOCK_CODES = {'CAPABILITY_UNAVAILABLE','SOURCE_DRIFT','DEPENDENCY_BLOCKED',
               'EXTERNAL_RESULT_UNKNOWN','PROVIDER_UNAVAILABLE','POLICY_DENIED','TEST_FAILURE'}
RETRY_CODES = {'CAPABILITY_CHANGED','SOURCE_REOBSERVED','DEPENDENCY_VERIFIED',
               'EXTERNAL_RECONCILED','PROVIDER_RECOVERED','POLICY_AUTHORIZED','NEW_EVIDENCE'}


def matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def parse_utc(value):
    require(matches(UTC,value), 'V8_UTC_INVALID')
    try:
        return datetime.fromisoformat(value[:-1]+'+00:00')
    except ValueError as exc:
        from brain.core import BrainError
        raise BrainError('V8_UTC_INVALID') from exc


def identifiers(values, pattern):
    require(type(values) is list and len(values)<=32
            and all(matches(pattern,x) for x in values), 'V8_ID_LIST_INVALID')
    require(len(set(values)) == len(values), 'V8_DUPLICATE_IDENTIFIER')


def validate_work(row):
    require(type(row) is dict and set(row)==WORK_FIELDS, 'V8_WORK_FIELDS_INVALID')
    require(type(row['schema_version']) is int and row['schema_version']==1,
            'V8_WORK_VERSION_INVALID')
    require(matches(ID,row['project_id']) and matches(ID,row['owner'])
            and matches(REPO,row['repository']) and matches(SHA,row['source_sha'])
            and matches(HASH,row['fingerprint']) and matches(HASH,row['resource']),
            'V8_WORK_IDENTITY_INVALID')
    identity={k:row[k] for k in ('project_id','repository','source_sha','fingerprint')}
    require(row['work_id']=='work:'+digest(identity), 'V8_WORK_SOURCE_SUBSTITUTION')
    require(type(row['state']) is str and row['state'] in set(LOCAL_STATES)|RELEASE_STATES|STOP_STATES,
            'V8_WORK_STATE_INVALID')
    require(type(row['priority_tier']) is int and 0<=row['priority_tier']<=4
            and type(row['attempts']) is int and 0<=row['attempts']<=100,
            'V8_WORK_COUNTER_INVALID')
    identifiers(row['evidence_ids'], HASH)
    identifiers(row['dependencies'], WORK_ID)
    require(parse_utc(row['updated_at'])>=parse_utc(row['created_at']), 'V8_WORK_TIME_REVERSED')
    blocker=row['blocker']
    if blocker is not None:
        require(type(blocker) is dict and set(blocker)=={'code','retry_condition','last_operation_id'},
                'V8_BLOCKER_FIELDS_INVALID')
        require(type(blocker['code']) is str and blocker['code'] in BLOCK_CODES
                and type(blocker['retry_condition']) is str and blocker['retry_condition'] in RETRY_CODES
                and matches(HASH,blocker['last_operation_id']), 'V8_BLOCKER_INVALID')
    require(row['state']!='BLOCKED' or blocker is not None, 'V8_BLOCKED_REASON_REQUIRED')
    return deepcopy(row)


def validate_capability(row, *, now):
    require(type(row) is dict and set(row)==CAP_FIELDS, 'V8_CAP_FIELDS_INVALID')
    require(type(row['schema_version']) is int and row['schema_version']==1,
            'V8_CAP_VERSION_INVALID')
    require(matches(ID,row['executor']) and matches(REPO,row['repository'])
            and matches(HASH,row['resource']) and matches(HASH,row['evidence_id']),
            'V8_CAP_IDENTITY_INVALID')
    require(type(row['action']) is str and row['action'] in
            {'READ','PATCH_BRANCH','RUN_TESTS','MERGE','DEPLOY','UPDATE_TASK'}
            and type(row['status']) is str and row['status'] in
            {'DECLARED','READ_CONFIRMED','WRITE_CONFIRMED','UNAVAILABLE'}, 'V8_CAP_STATUS_INVALID')
    require(row['status']!='READ_CONFIRMED' or row['action']=='READ', 'V8_READ_IS_NOT_WRITE')
    observed, expires, current=map(parse_utc,(row['observed_at'],row['expires_at'],now))
    require(observed<=current and expires>observed, 'V8_CAP_TIME_INVALID')
    result=deepcopy(row)
    result['effective_status']='STALE' if current>=expires else row['status']
    return result


def advance(row, target, *, evidence_ids, now):
    result=validate_work(row)
    require(type(target) is str, 'V8_TARGET_INVALID')
    require(target not in RELEASE_STATES, 'V8_INDEPENDENT_ADAPTER_REQUIRED')
    require(result['state'] in LOCAL_STATES, 'V8_TERMINAL_ATTEMPT')
    require(parse_utc(now)>=parse_utc(result['updated_at']), 'V8_TRANSITION_TIME_REVERSED')
    identifiers(evidence_ids,HASH)
    require(bool(evidence_ids), 'V8_TRANSITION_EVIDENCE_REQUIRED')
    index=LOCAL_STATES.index(result['state'])
    require(target in STOP_STATES or
            (index+1<len(LOCAL_STATES) and target==LOCAL_STATES[index+1]),
            'V8_TRANSITION_SKIPPED')
    result.update(state=target, evidence_ids=list(evidence_ids), updated_at=now)
    return validate_work(result)
