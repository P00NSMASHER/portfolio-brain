"""One-shot, exact-source canary. Never a recurring production merge controller."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sys
import time

REPO = 'P00NSMASHER/portfolio-brain'
REPO_ID = 1387747549
MAIN = '35ad71868f74e6d4f749a35630a1b86802b91ed0'
HEAD = '6ebe7d1523c96c2752ae7608ca662dc1c9192b7f'
BRANCH = 'canary/native-permission-completion-20261020'
LAB = 'review/native-permission-completion-20261020'
DOC = 'docs/genesis/NATIVE_PERMISSION_COMPLETION_CANARY.md'
TEXT = '''# Native enrollment permission canary

This static document is the complete change for a one-time, owner-authorized
GitHub-native enrollment permission test. It changes no application behavior,
workflow, credential, policy, or branch protection.

The test uses the existing restricted Actions token and an exact-head condition.
GitHub must continue enforcing all existing protected merge requirements.
A successful enrollment is not a successful merge or permission to expand
production autonomy. An uncertain request must not be retried.
'''
QUERY = '''query($number:Int!) { repository(owner:"P00NSMASHER",name:"portfolio-brain") {
 databaseId nameWithOwner autoMergeAllowed isArchived
 rulesets(first:100) { pageInfo { hasNextPage } nodes { databaseId name enforcement
 bypassActors(first:100) { totalCount pageInfo {hasNextPage} } } }
 pullRequest(number:$number) { id headRefOid baseRefOid state isDraft mergeStateStatus
 viewerCanEnableAutoMerge autoMergeRequest { enabledAt } reviewThreads(first:100) {
 pageInfo { hasNextPage } nodes { isResolved } } }
} }'''
MUTATION = '''mutation($id:ID!,$expected_head:GitObjectID!) {
 enablePullRequestAutoMerge(input:{pullRequestId:$id,expectedHeadOid:$expected_head,mergeMethod:SQUASH}) {
 pullRequest { id headRefOid autoMergeRequest {enabledAt} } }
}'''

class Stop(ValueError):
    pass

def need(ok, code):
    if not ok:
        raise Stop(code)

def blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

class API:
    def __init__(self):
        self.calls = 0
        self.posts = 0
        self.started = time.monotonic()
    def __call__(self, method, path, data=None):
        need(self.calls < 80 and time.monotonic()-self.started < 240, 'BOUNDED_PROBE_EXHAUSTED')
        read = method == 'GET' and path.startswith('/repos/'+REPO+'/') and data is None
        query = method == 'POST' and path == '/graphql' and data.get('query') == QUERY
        write = method == 'POST' and path == '/graphql' and data.get('query') == MUTATION
        need(read or query or write, 'UNREVIEWED_ENDPOINT')
        if write:
            need(self.posts == 0 and set(data['variables']) == {'id','expected_head'}
                 and data['variables']['expected_head'] == HEAD, 'WRITE_BOUND')
            self.posts += 1
        self.calls += 1
        conn = http.client.HTTPSConnection('api.github.com', timeout=15)
        headers = {'Authorization':'Bearer '+os.environ['GH_TOKEN'],
                   'Accept':'application/vnd.github+json',
                   'X-GitHub-Api-Version':'2022-11-28','User-Agent':'brain-native-one-shot'}
        try:
            conn.request(method,path,body=json.dumps(data).encode() if data else None,headers=headers)
            reply = conn.getresponse()
            raw = reply.read(1048577)
            need(reply.status == 200 and len(raw) <= 1048576, 'PROVIDER_HTTP_'+str(reply.status))
            return json.loads(raw)
        finally:
            conn.close()

def get(api,path):
    return api('GET','/repos/'+REPO+path)

def identity(pr, number):
    need(type(pr) is dict and pr.get('number') == number and pr.get('state') == 'open'
         and pr.get('draft') is False and pr.get('merged') is False
         and pr.get('auto_merge') is None and pr.get('changed_files') == 1
         and pr.get('user',{}).get('login') == 'P00NSMASHER', 'CANARY_IDENTITY')
    for side, sha, ref in [('head',HEAD,BRANCH),('base',MAIN,'main')]:
        v = pr.get(side,{})
        need(v.get('sha') == sha and v.get('ref') == ref
             and v.get('repo',{}).get('id') == REPO_ID
             and v.get('repo',{}).get('full_name') == REPO, 'SOURCE_OR_TARGET_DRIFT')
    need(type(pr.get('node_id')) is str and pr['node_id'].startswith('PR_'), 'NODE_ID')
    return pr['node_id']

def checks_ready(checks):
    need(type(checks) is dict and type(checks.get('total_count')) is int
         and 0 <= checks['total_count'] < 100 and type(checks.get('check_runs')) is list
         and len(checks['check_runs']) == checks['total_count'], 'CHECK_CENSUS')
    rows = checks['check_runs']
    need(all(type(c) is dict and c.get('head_sha') == HEAD for c in rows), 'CHECK_HEAD')
    status = {}
    for name, app in [('validate',15368),('portfolio-phase1-gate',5121826)]:
        found = [c for c in rows if c.get('name') == name]
        need(len(found) <= 1, 'AMBIGUOUS_CHECK')
        if not found:
            status[name] = 'missing'; continue
        c = found[0]
        need(c.get('app',{}).get('id') == app, 'CHECK_ISSUER')
        if c.get('status') == 'completed':
            need(c.get('conclusion') == 'success', 'FAILED_REQUIRED_CHECK')
            status[name] = 'success'
        else:
            need(c.get('status') in ['queued','in_progress'] and c.get('conclusion') is None, 'CHECK_STATE')
            status[name] = 'pending'
    need(not all(v == 'success' for v in status.values()), 'WINDOW_ALREADY_CLOSED_NO_POST')
    return status['validate'] == 'success', status

def guard(api, number):
    main = get(api,'/branches/main')
    need(main.get('protected') is True and main.get('commit',{}).get('sha') == MAIN, 'MAIN_CHANGED')
    pr = get(api,'/pulls/'+str(number)); node = identity(pr,number)
    ready, statuses = checks_ready(get(api,'/commits/'+HEAD+'/check-runs?per_page=100'))
    need(ready, 'FOUNDATION_NOT_READY')
    need(pr.get('mergeable') is True and pr.get('mergeable_state') == 'blocked', 'NOT_GENUINELY_BLOCKED')
    rules = get(api,'/rulesets/24182301')
    need(rules.get('id') == 24182301 and rules.get('enforcement') == 'active'
         and rules.get('conditions',{}).get('ref_name') == {'include':['refs/heads/main'],'exclude':[]}
         and ('bypass_actors' not in rules or rules['bypass_actors'] == []), 'RULESET_CHANGED')
    types = {r['type']:r.get('parameters',{}) for r in rules['rules']}
    need({'deletion','non_fast_forward','pull_request','required_status_checks'} <= types.keys(), 'PROTECTION_MISSING')
    c = types['required_status_checks']
    need(c.get('strict_required_status_checks_policy') is True
         and {('validate',15368),('portfolio-phase1-gate',5121826)} <= {
             (r['context'],r['integration_id']) for r in c['required_status_checks']}
         and types['pull_request'].get('required_review_thread_resolution') is True,'REQUIRED_GATES_CHANGED')
    response = api('POST','/graphql',{'query':QUERY,'variables':{'number':number}})
    need(not response.get('errors'),'GRAPHQL_READ_FAILED')
    repo = response['data']['repository']
    need(repo['databaseId'] == REPO_ID and repo['nameWithOwner'] == REPO
         and repo['autoMergeAllowed'] is True and repo['isArchived'] is False,'REPOSITORY_IDENTITY')
    rs = repo['rulesets']; need(rs['pageInfo']['hasNextPage'] is False,'RULESET_CENSUS')
    one = [r for r in rs['nodes'] if r['databaseId'] == 24182301]
    need(len(one) == 1 and one[0]['enforcement'] == 'ACTIVE'
         and one[0]['bypassActors']['totalCount'] == 0
         and one[0]['bypassActors']['pageInfo']['hasNextPage'] is False,'BYPASS_UNVERIFIED')
    q = repo['pullRequest']
    need(q['id'] == node and q['headRefOid'] == HEAD and q['baseRefOid'] == MAIN
         and q['state'] == 'OPEN' and q['isDraft'] is False and q['autoMergeRequest'] is None
         and q['mergeStateStatus'] == 'BLOCKED' and q['viewerCanEnableAutoMerge'] is True,'NATIVE_INELIGIBLE')
    threads = q['reviewThreads']
    need(threads['pageInfo']['hasNextPage'] is False
         and all(x['isResolved'] is True for x in threads['nodes']),'UNRESOLVED_REVIEW')
    return node,statuses

def execute_once(api, number, node):
    """One attempted mutation, followed by original-provider readback; no retry."""
    response = None
    code = 'UNKNOWN_AFTER_POST'
    try:
        response = api('POST','/graphql',{'query':MUTATION,'variables':{'id':node,'expected_head':HEAD}})
        errors = response.get('errors')
        if errors:
            kinds = {e.get('type') for e in errors if type(e) is dict}
            if len(kinds) == 1 and next(iter(kinds)) in {'FORBIDDEN','UNPROCESSABLE','NOT_FOUND'}:
                code = 'NATIVE_POST_REJECTED_'+next(iter(kinds))
    except Exception:
        pass
    try:
        observed = get(api,'/pulls/'+str(number))
        same = observed.get('number') == number and observed.get('node_id') == node and observed.get('head',{}).get('sha') == HEAD
        if same and observed.get('state') == 'open' and type(observed.get('auto_merge')) is dict:
            if not response or response.get('errors'):
                code = 'ENROLLMENT_VISIBLE_AFTER_UNCERTAIN_POST'
            else:
                native = response.get('data',{}).get('enablePullRequestAutoMerge',{}).get('pullRequest',{})
                if (native.get('id') == node and native.get('headRefOid') == HEAD
                        and type(native.get('autoMergeRequest')) is dict
                        and type(native['autoMergeRequest'].get('enabledAt')) is str
                        and observed['auto_merge'].get('merge_method') == 'squash'):
                    code = 'NATIVE_ENROLLMENT_CONFIRMED'
        elif same and observed.get('merged') is True:
            code = 'MERGE_OBSERVED_REQUIRES_INDEPENDENT_PROVENANCE'
        return {'status':code,'attempted_native_posts':1,'head_sha':HEAD,'pr':number,
                'rest_enrolled':bool(observed.get('auto_merge')),'rest_merged':observed.get('merged'),
                'readback_same_head':same,'permissions':'contents:read,pull-requests:write'}
    except Exception:
        return {'status':code,'attempted_native_posts':1,'head_sha':HEAD,'pr':number,'readback':'unavailable'}

def main():
    need(os.environ.get('GITHUB_REPOSITORY') == REPO and os.environ.get('GITHUB_REF_NAME') == LAB
         and os.environ.get('GITHUB_EVENT_NAME') == 'push' and os.environ.get('GITHUB_RUN_ATTEMPT') == '1','EXECUTION_CONTEXT')
    api = API(); root = Path('proof'); root.mkdir(exist_ok=True)
    if sys.argv[1] == 'prepare':
        number = None
        for _ in range(6):
            rows = get(api,'/pulls?state=open&head=P00NSMASHER:'+BRANCH+'&per_page=100')
            need(type(rows) is list and len(rows) < 100,'PR_CENSUS')
            matches = [p for p in rows if p.get('head',{}).get('sha') == HEAD]
            need(len(matches) <= 1,'PR_AMBIGUOUS')
            if matches:
                number = matches[0]['number']; break
            time.sleep(5)
        need(type(number) is int,'CANARY_MISSING')
        compare = get(api,'/compare/'+MAIN+'...'+HEAD)
        need(compare.get('merge_base_commit',{}).get('sha') == MAIN
             and compare.get('ahead_by') == 1 and compare.get('behind_by') == 0
             and len(compare.get('files',[])) == 1 and compare['files'][0].get('filename') == DOC
             and compare['files'][0].get('status') == 'added','NOT_EXACT_DOC_ONLY_CANARY')
        content = get(api,'/contents/'+DOC+'?ref='+HEAD)
        raw = base64.b64decode(content['content'].replace('\n',''),validate=True)
        need(raw == TEXT.encode() and content.get('sha') == blob(raw),'CANARY_CONTENT_CHANGED')
        for _ in range(18):
            ready, state = checks_ready(get(api,'/commits/'+HEAD+'/check-runs?per_page=100'))
            if ready: break
            time.sleep(10)
        need(ready,'FOUNDATION_NOT_READY')
        node, state = guard(api,number)
        intent = dict(pr=number,node=node,head_sha=HEAD,base_sha=MAIN,doc_sha=blob(raw),
                      source_sha=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
                      status='PREPARED_INTENT_NO_POST',checks=state)
        (root/'intent.json').write_text(json.dumps(intent,sort_keys=True))
        print(json.dumps(intent,sort_keys=True))
    else:
        intent = json.loads((root/'intent.json').read_text())
        need(intent['head_sha'] == HEAD and intent['base_sha'] == MAIN
             and intent['source_sha'] == os.environ['GITHUB_SHA'] and intent['run_id'] == os.environ['GITHUB_RUN_ID'],'INTENT_DRIFT')
        node,_ = guard(api,intent['pr']); need(node == intent['node'],'NODE_DRIFT')
        result = execute_once(api,intent['pr'],node)
        (root/'result.json').write_text(json.dumps(result,sort_keys=True))
        print(json.dumps(result,sort_keys=True))
        return 0 if result['status'] == 'NATIVE_ENROLLMENT_CONFIRMED' else 2
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Stop as error:
        print(json.dumps({'status':'HOLD','reason':str(error),'native_post_not_confirmed':True}))
        raise SystemExit(3)
