"""Read-only recovery decisions from a stable durable queue checkpoint.

No unknown provider effect is automatically retried, even after its
original lease expires. No task scheduling, code execution or remote writes.
"""
from __future__ import annotations
from datetime import datetime
from brain.v9.batch_queue import BatchFault

def at(value):
    if type(value) is not str or not value.endswith('Z'):
        raise BatchFault('RECOVERY_CLOCK_INVALID')
    try: return datetime.fromisoformat(value[:-1]+'+00:00')
    except ValueError as exc: raise BatchFault('RECOVERY_CLOCK_INVALID') from exc

def recovery_plan(queue,*,now,limit=5):
    today=at(now)
    if type(limit) is not int or not 1<=limit<=5:
        raise BatchFault('RECOVERY_LIMIT_INVALID')
    before=queue.checkpoint()
    items=queue.snapshot().get('work')
    after=queue.checkpoint()
    if before!=after: raise BatchFault('RECOVERY_SNAPSHOT_MOVED')
    if type(items) is not dict or len(items)>256:
        raise BatchFault('RECOVERY_SOURCE_INVALID')
    result=[]
    for work_id,row in items.items():
        if type(row) is not dict or row.get('work_id')!=work_id:
            raise BatchFault('RECOVERY_SOURCE_INVALID')
        created=at(row['created_at'])
        if today<created: raise BatchFault('RECOVERY_CLOCK_REVERSED')
        pending=row.get('pending')
        claim=row.get('claim')
        if pending is not None:
            operation=pending.get('operation_id')
            if pending.get('status') not in ('INTENT','UNKNOWN') or type(operation) is not str:
                raise BatchFault('RECOVERY_SOURCE_INVALID')
            next_action='ORIGINAL_PROVIDER_RECONCILIATION_REQUIRED_NO_RETRY'
        elif claim is not None and today<at(claim.get('expires_at')):
            operation=None;next_action='LIVE_OWNER_LEASE_DO_NOT_REASSIGN'
        elif claim is not None:
            operation=None;next_action='REOBSERVE_SOURCE_BEFORE_NEW_FENCED_CLAIM'
        elif row.get('stage')=='TESTED' and row.get('effects'):
            operation=None;next_action='VERIFY_ORIGINAL_INDEPENDENT_CHECKS'
        else:
            operation=None;next_action='REOBSERVE_SOURCE_BEFORE_CLAIM'
        result.append(dict(work_id=work_id,project_id=row['project_id'],
            owner=row['owner'],source_sha=row['source_sha'],priority=row['priority'],
            stage=row['stage'],blocked_seconds=(today-created).total_seconds(),
            operation_id=operation,next_action=next_action,
            reobserve_source=True,provider_writes=0))
    result.sort(key=lambda x:(x['priority'],-x['blocked_seconds'],x['work_id']))
    chosen=result[:limit]
    return dict(status='READ_ONLY_RECOVERY_PLAN_NOT_ACTION',
         queue_checkpoint=before,actions=chosen,deferred=len(result)-len(chosen),
         uncertain_external_effects=sum(x['operation_id'] is not None for x in result),
         provider_writes=0,production_accepted=False,task_or_scheduler_mutations=0)
