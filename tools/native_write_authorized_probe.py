"""Owner-authorized, one-document permission test; never general activation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

HELPER_BLOB = '041056175a90d67bb05550d3696021871d72b0ac'
helper = Path(__file__).with_name('native_permission_completion_probe.py')
raw = helper.read_bytes()
assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == HELPER_BLOB
spec = importlib.util.spec_from_file_location('pinned_native_permission_helper', helper)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
probe.HEAD = '4b874598aa00815c0fa0e63ec4a7159892654b01'
probe.BRANCH = 'canary/native-write-authorized-20261020'
probe.LAB = 'review/native-write-authorized-20261020'
probe.DOC = 'docs/genesis/NATIVE_WRITE_AUTHORIZED_CANARY.md'
probe.TEXT = '''# Authorized native enrollment canary

This static document is the entire change for one owner-authorized native
GitHub auto-merge test. It changes no code, workflow, credential or protection.

Only the guarded test job receives contents:write plus pull-requests:write.
GitHub must enforce both existing issuer-pinned checks before any merge.
The request must bind this exact head and preserve intent before submission.
No uncertain request may be retried. Success does not activate general autonomy.
'''
original_execute = probe.execute_once

def execute_once(api, number, node):
    result = original_execute(api, number, node)
    result['permissions'] = 'contents:write,pull-requests:write'
    return result

probe.execute_once = execute_once

def check_context():
    probe.need(os.environ.get('GITHUB_JOB') == 'guarded-enrollment'
               and os.environ.get('GITHUB_WORKFLOW') == 'Owner-authorized native write canary',
               'AUTHORIZED_JOB_CONTEXT')

if __name__ == '__main__':
    try:
        check_context()
        probe.need(len(sys.argv) == 2 and sys.argv[1] in ('prepare','attempt'), 'MODE_INVALID')
        raise SystemExit(probe.main())
    except probe.Stop as error:
        print(json.dumps({'status':'HOLD','reason':str(error),'native_post_not_confirmed':True}))
        raise SystemExit(3)
