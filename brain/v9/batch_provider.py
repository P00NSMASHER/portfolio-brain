"""Bounded original GitHub evidence reads; no writes or release acceptance."""
from __future__ import annotations
import json,re,urllib.error,urllib.request
from brain.v9.batch_queue import BatchFault,PROJECTS,hashval
REQUIRED={'validate':15368,'portfolio-phase1-gate':5121826}
MAX_BYTES=2*1024*1024

def _same_document(first, second):
    # JSON comparison preserves number/bool distinctions lost by dict equality.
    return json.dumps(first,sort_keys=True,allow_nan=False) == json.dumps(
        second,sort_keys=True,allow_nan=False)

def validate_original_checks(doc,sha):
    if not hashval(sha,40) or type(doc) is not dict: raise BatchFault('CHECK_SOURCE_INVALID')
    rows=doc.get('check_runs');total=doc.get('total_count')
    if type(rows) is not list or type(total) is not int or total!=len(rows) or total>100:
        raise BatchFault('CHECK_CENSUS_INCOMPLETE')
    found={}
    for r in rows:
        if type(r) is not dict or type(r.get('name')) is not str:
            raise BatchFault('CHECK_ROW_MALFORMED')
        if r['name'] in REQUIRED:
            if r['name'] in found: raise BatchFault('CHECK_DUPLICATE_ISSUER')
            found[r['name']]=r
    if set(found)!=set(REQUIRED): raise BatchFault('CHECK_REQUIRED_ISSUER_MISSING')
    for name,issuer in REQUIRED.items():
        r=found[name]
        if (type(r.get('app')) is not dict or type(r['app'].get('id')) is not int
                or r['app']['id']!=issuer or r.get('head_sha')!=sha
                or r.get('status')!='completed' or r.get('conclusion')!='success'):
            raise BatchFault('CHECK_EXACT_HEAD_NOT_SUCCESS')
    return {'status':'ORIGINAL_CHECK_ISSUERS_MATCHED','candidate_sha':sha,
            'check_issuers':dict(REQUIRED),'production_accepted':False,
            'six_hour_acceptance_passed':False}

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl): return None

class GitHubOriginalReader:
    """No arbitrary endpoint, no token in output, strict per-run GET budget."""
    def __init__(self,*,token='',max_gets=8,timeout=8):
        if type(token) is not str or type(max_gets) is not int or not 1<=max_gets<=24:
            raise ValueError('READBACK_OPTIONS_INVALID')
        if type(timeout) is not int or not 1<=timeout<=30:
            raise ValueError('READBACK_TIMEOUT_INVALID')
        self._token=token;self.max_gets=max_gets;self.timeout=timeout;self.used_gets=0
        self._opener=urllib.request.build_opener(_NoRedirect())
    @property
    def gets_remaining(self): return self.max_gets-self.used_gets
    def _get(self,repo,suffix):
        if type(repo) is not str or repo not in set(PROJECTS.values()):
            raise BatchFault('READBACK_REPOSITORY_REFUSED')
        if type(suffix) is not str or not re.fullmatch(
                r'/(branches/main|pulls/[1-9][0-9]*|commits/[0-9a-f]{40}/check-runs\?per_page=100|actions/runs/[1-9][0-9]{0,11}(?:/jobs\?per_page=100)?)',suffix):
            raise BatchFault('READBACK_ROUTE_REFUSED')
        if self.used_gets>=self.max_gets: raise BatchFault('READBACK_BUDGET_EXHAUSTED')
        self.used_gets+=1
        headers={'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28',
                 'User-Agent':'Portfolio-Brain-original-readback'}
        if self._token: headers['Authorization']='Bearer '+self._token
        req=urllib.request.Request('https://api.github.com/repos/'+repo+suffix,
                                   headers=headers,method='GET')
        try:
            with self._opener.open(req,timeout=self.timeout) as response:
                if response.status!=200: raise BatchFault('READBACK_HTTP_NOT_OK')
                data=response.read(MAX_BYTES+1)
        except (urllib.error.URLError,OSError) as exc:
            raise BatchFault('READBACK_PROVIDER_UNAVAILABLE') from exc
        if len(data)>MAX_BYTES: raise BatchFault('READBACK_RESPONSE_TOO_LARGE')
        def unique(pairs):
            result={}
            for k,v in pairs:
                if k in result: raise BatchFault('READBACK_DUPLICATE_JSON_KEY')
                result[k]=v
            return result
        try:
            doc=json.loads(data.decode('utf-8'),object_pairs_hook=unique,
                           parse_constant=lambda x: (_ for _ in ()).throw(BatchFault('READBACK_NONFINITE')))
        except (UnicodeError,ValueError) as exc:
            raise BatchFault('READBACK_JSON_INVALID') from exc
        if type(doc) is not dict: raise BatchFault('READBACK_JSON_INVALID')
        return doc
    def failed_main_job(self, repo, sha, run_id, job_id):
        """Corroborate one first-attempt failure at the observed main revision."""
        if (not hashval(sha, 40) or any(type(n) is not int or not 0 < n < 10**12
                                       for n in (run_id, job_id))):
            raise BatchFault("FAILURE_IDENTITY_INVALID")
        route = "/actions/runs/" + str(run_id)
        run = self._get(repo, route)
        if not (run.get("id") == run_id and run.get("head_sha") == sha
                and run.get("head_branch") == "main"
                and run.get("repository", {}).get("full_name") == repo
                and run.get("head_repository", {}).get("full_name") == repo
                and run.get("event") in ("push", "schedule", "workflow_dispatch")
                and run.get("run_attempt") == 1 and run.get("status") == "completed"
                and run.get("conclusion") in ("failure", "timed_out")):
            raise BatchFault("ORIGINAL_FAILED_MAIN_RUN_UNVERIFIED")
        census = self._get(repo, route + "/jobs?per_page=100")
        jobs = census.get("jobs")
        if (type(jobs) is not list or type(census.get("total_count")) is not int
                or len(jobs) != census["total_count"] or len(jobs) > 100):
            raise BatchFault("ORIGINAL_FAILED_JOB_CENSUS_INCOMPLETE")
        matches = [j for j in jobs if type(j) is dict and j.get("id") == job_id]
        url = f"https://github.com/{repo}/actions/runs/{run_id}/job/{job_id}"
        if len(matches) != 1:
            raise BatchFault("ORIGINAL_FAILED_JOB_UNVERIFIED")
        job = matches[0]
        if not (job.get("run_id") == run_id and job.get("run_attempt") == 1
                and job.get("head_sha") == sha and job.get("head_branch") == "main"
                and job.get("html_url") == url and job.get("status") == "completed"
                and job.get("conclusion") in ("failure", "timed_out")
                and type(job.get("steps")) is list and 1 <= len(job["steps"]) <= 100):
            raise BatchFault("ORIGINAL_FAILED_JOB_UNVERIFIED")
        steps = [{"number": s["number"], "name": s["name"]}
                 for s in job["steps"] if type(s) is dict and s.get("status") == "completed"
                 and s.get("conclusion") in ("failure", "timed_out")
                 and type(s.get("number")) is int and 0 < s["number"] <= 1000
                 and type(s.get("name")) is str and 0 < len(s["name"]) <= 180
                 and s["name"].isprintable()]
        if not steps:
            raise BatchFault("ORIGINAL_FAILED_STEP_UNVERIFIED")
        return {"status": "ORIGINAL_MAIN_JOB_FAILURE_CONFIRMED", "url": url,
                "run_id": run_id, "job_id": job_id, "source_sha": sha,
                "event": run["event"], "failed_steps": steps, "root_cause_verified": False}

    def read_draft_only(self, repo, number, *, base_sha, head_sha, operation_id):
        """Reconcile original draft creation independent of CI success."""
        if (type(repo) is not str or repo not in set(PROJECTS.values())
                or type(number) is not int or not 0<number<10**9
                or not hashval(base_sha,40) or not hashval(head_sha,40)
                or not hashval(operation_id)):
            raise BatchFault('READBACK_IDENTITY_INVALID')
        first=self._get(repo,'/branches/main')
        if type(first.get('commit')) is not dict or first['commit'].get('sha')!=base_sha:
            raise BatchFault('READBACK_SOURCE_CHANGED')
        pr=self._get(repo,'/pulls/'+str(number))
        head=pr.get('head');base=pr.get('base')
        marker='BRAIN_BATCH_OPERATION_ID: '+operation_id
        if (type(head) is not dict or type(base) is not dict
                or type(head.get('repo')) is not dict or type(base.get('repo')) is not dict
                or type(pr.get('number')) is not int or pr.get('number')!=number or pr.get('state')!='open'
                or pr.get('draft') is not True or pr.get('merged') is not False
                or head.get('sha')!=head_sha or head['repo'].get('full_name')!=repo
                or base.get('ref')!='main' or base.get('sha')!=base_sha
                or base['repo'].get('full_name')!=repo or type(pr.get('body')) is not str
                or marker not in pr['body'].splitlines()):
            raise BatchFault('READBACK_DRAFT_OR_OPERATION_UNVERIFIED')
        if not _same_document(pr,self._get(repo,'/pulls/'+str(number))):
            raise BatchFault('READBACK_PR_CHANGED')
        second=self._get(repo,'/branches/main')
        if type(second.get('commit')) is not dict or second['commit'].get('sha')!=base_sha:
            raise BatchFault('READBACK_SOURCE_CHANGED')
        return dict(status='ORIGINAL_DRAFT_WRITE_OBSERVED_CHECKS_UNKNOWN',
                    repository=repo,base_sha=base_sha,candidate_sha=head_sha,
                    pr_number=number,operation_id=operation_id,original_get_count=4,
                    independent_check_verified=False,provider_writes=0,
                    production_accepted=False)

    def verify_draft_and_checks(self,repo,number,*,base_sha,head_sha,operation_id):
        if (type(repo) is not str or repo not in set(PROJECTS.values())
                or type(number) is not int or not 0<number<10**9
                or not hashval(base_sha,40) or not hashval(head_sha,40)
                or not hashval(operation_id)):
            raise BatchFault('READBACK_IDENTITY_INVALID')
        marker='BRAIN_BATCH_OPERATION_ID: '+operation_id
        first=self._get(repo,'/branches/main')
        if type(first.get('commit')) is not dict or first['commit'].get('sha')!=base_sha:
            raise BatchFault('READBACK_SOURCE_CHANGED')
        pr=self._get(repo,'/pulls/'+str(number))
        head=pr.get('head');base=pr.get('base')
        if (type(head) is not dict or type(base) is not dict
                or type(head.get('repo')) is not dict or type(base.get('repo')) is not dict
                or type(pr.get('number')) is not int or pr.get('number')!=number or pr.get('state')!='open'
                or pr.get('draft') is not True or pr.get('merged') is not False
                or head.get('sha')!=head_sha or head['repo'].get('full_name')!=repo
                or base.get('ref')!='main' or base.get('sha')!=base_sha
                or base['repo'].get('full_name')!=repo or type(pr.get('body')) is not str
                or marker not in pr['body'].splitlines()):
            raise BatchFault('READBACK_DRAFT_OR_OPERATION_UNVERIFIED')
        check_doc=self._get(repo,'/commits/'+head_sha+'/check-runs?per_page=100')
        result=validate_original_checks(check_doc,head_sha)
        if not _same_document(check_doc,self._get(
                repo,'/commits/'+head_sha+'/check-runs?per_page=100')):
            raise BatchFault('READBACK_CHECKS_CHANGED')
        if not _same_document(pr,self._get(repo,'/pulls/'+str(number))):
            raise BatchFault('READBACK_PR_CHANGED')
        second=self._get(repo,'/branches/main')
        if type(second.get('commit')) is not dict or second['commit'].get('sha')!=base_sha:
            raise BatchFault('READBACK_SOURCE_CHANGED')
        return dict(status='OBSERVED_BY_GITHUB_READBACK_NOT_RELEASED',
                    repository=repo,base_sha=base_sha,candidate_sha=head_sha,
                    pr_number=number,operation_id=operation_id,
                    check_issuers=result['check_issuers'],original_get_count=6,
                    production_accepted=False,six_hour_acceptance_passed=False,
                    provider_writes=0)
