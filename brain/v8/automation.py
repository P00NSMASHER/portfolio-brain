"""Private task edit adapter for an existing authorized Chat owner, not a runtime API."""
from copy import deepcopy
from brain.core import digest,require
from brain.v8.private_state import PrivateFiles

FIELDS={'prompt','title','schedule','is_enabled'}


def _task(row):
    require(type(row) is dict and set(row)==FIELDS
            and type(row['prompt']) is str and 0<len(row['prompt'])<=100000
            and type(row['title']) is str and 0<len(row['title'])<=200
            and type(row['schedule']) is str and 0<len(row['schedule'])<=4000
            and type(row['is_enabled']) is bool,'V8_TASK_STATE_INVALID')
    return deepcopy(row)


class AutomationReconciler:
    def __init__(self,root,owned_ids):
        require(type(owned_ids) in {tuple,list,set,frozenset} and 0<len(owned_ids)<=32
                and all(type(x) is str and 0<len(x)<=80 for x in owned_ids),'V8_TASK_OWNERSHIP_INVALID')
        self.owned=frozenset(owned_ids)
        self.files=PrivateFiles(root)

    def stage(self,task_id,before,changes):
        require(type(task_id) is str and task_id in self.owned,'V8_TASK_NOT_OWNED')
        before=_task(before)
        # Default adapter edits prompts only. Schedule, enable and trusted policy
        # changes require a separately reviewed adapter, never a field in input.
        require(type(changes) is dict and set(changes)=={'prompt'},'V8_TASK_CHANGE_SCOPE')
        after=_task(dict(before,**changes))
        require(after!=before,'V8_TASK_NO_CHANGE')
        body=dict(task_id=task_id,before=before,after=after,changes=deepcopy(changes))
        ident=digest(body)
        with self.files.lock():
            if self.files.read('automation',ident) is None:
                self.files.write('automation',ident,dict(request=body,status='STAGED'))
        return ident

    def _load(self,ident):
        row=self.files.read('automation',ident)
        require(type(row) is dict and set(row)=={'request','status'} and type(row['request']) is dict,
                'V8_TASK_OPERATION_INVALID')
        body=row['request']
        require(set(body)=={'task_id','before','after','changes'} and digest(body)==ident
                and type(body['task_id']) is str
                and body['task_id'] in self.owned,'V8_TASK_OPERATION_NOT_OWNED')
        _task(body['before']); _task(body['after'])
        require(type(body['changes']) is dict and set(body['changes'])=={'prompt'}
                and dict(body['before'],**body['changes'])==body['after']
                and type(row['status']) is str
                and row['status'] in {'STAGED','INTENT','UNKNOWN','APPLIED','CONFLICT',
                                     'ROLLBACK_INTENT','ROLLBACK_UNKNOWN','ROLLED_BACK'},
                'V8_TASK_OPERATION_INVALID')
        return row

    @staticmethod
    def _receipt(ident,row,status=None):
        return dict(operation_id=ident,status=status or row['status'],
            before_sha256=digest(row['request']['before']),after_sha256=digest(row['request']['after']),
            atomic_provider_compare_and_swap=False,runtime_api_access_verified=False)

    def _operate(self,ident,read,update,rollback):
        with self.files.lock():
            row=self._load(ident)
            request=row['request']
            # A provider may complete after timeout or process death. Reserve
            # the task across operations until its durable intent is reconciled.
            unresolved={'INTENT','UNKNOWN','ROLLBACK_INTENT','ROLLBACK_UNKNOWN'}
            for other in self.files.iter_records('automation'):
                require(type(other) is dict and set(other)=={'request','status'}
                        and type(other['request']) is dict
                        and type(other['request'].get('task_id')) is str
                        and type(other['status']) is str,
                        'V8_TASK_OPERATION_INVALID')
                if (other['request']['task_id']==request['task_id']
                        and digest(other['request'])!=ident and other['status'] in unresolved):
                    return self._receipt(ident,row,'TASK_RECONCILIATION_REQUIRED')
            try: current=_task(read(request['task_id']))
            except (OSError,ValueError): return self._receipt(ident,row,'READ_UNAVAILABLE')
            expected=request['after'] if rollback else request['before']
            desired=request['before'] if rollback else request['after']
            done='ROLLED_BACK' if rollback else 'APPLIED'
            unknown='ROLLBACK_UNKNOWN' if rollback else 'UNKNOWN'
            intent='ROLLBACK_INTENT' if rollback else 'INTENT'
            allowed='APPLIED' if rollback else 'STAGED'
            if row['status'] in {intent,unknown} and current==desired:
                row['status']=done
            elif row['status']==done:
                if current!=desired: row['status']='CONFLICT'
            elif row['status']!=allowed:
                return self._receipt(ident,row)
            elif current!=expected:
                row['status']='CONFLICT'
            else:
                row['status']=intent
                self.files.write('automation',ident,row)
                try:
                    update(request['task_id'],{'prompt':desired['prompt']})
                    observed=_task(read(request['task_id']))
                    row['status']=done if observed==desired else 'CONFLICT'
                except (OSError,ValueError): row['status']=unknown
            self.files.write('automation',ident,row)
            return self._receipt(ident,row)

    def apply(self,ident,read,update):
        return self._operate(ident,read,update,False)

    def rollback(self,ident,read,update):
        return self._operate(ident,read,update,True)
