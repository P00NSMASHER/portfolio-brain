"""Original read-only evidence for one supervised CaptureBrief website repair.

No merge, deployment, token forwarding, arbitrary URL or production acceptance.
A successful receipt binds original PR/CI/Pages evidence and actual served bytes.
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
from brain.v9.batch_provider import GitHubOriginalReader
from brain.v9.batch_queue import BatchFault, hashval

REPO = 'P00NSMASHER/capturebrief'
ASSET = 'assets/capturebrief.js'
LIVE = 'https://p00nsmasher.github.io/capturebrief/' + ASSET
ORIGINAL_HASH = 'e69445d718fd9e2d2605042736150c0bdcd3e6599977aa199cd5e5d49cf10c09'
CORRECTED_HASH = '7868b42bde47a2fb87a0f87ada3ea29eeaf9745d590f3852ab29bae8261173a8'
REQUIRED_JOBS = {'browser-check (chromium)', 'browser-check (webkit)'}
LIVE_STEP = 'Verify clipboard failure recovery on the published site'
REQUIRED_BUDGET = 10
FIELDS = {'schema_version', 'repository', 'source_branch', 'path',
          'original_source_sha', 'original_asset_sha256', 'candidate_sha',
          'pr_number', 'expected_asset_sha256', 'fingerprint', 'recipe', 'public_url'}

def need(value, code):
    if not value:
        raise BatchFault(code)

def validate_spec(spec):
    need(type(spec) is dict and set(spec) == FIELDS, 'PUBLICATION_SPEC_FIELDS')
    need(type(spec['schema_version']) is int and spec['schema_version'] == 1
         and spec['repository'] == REPO and spec['source_branch'] == 'gh-pages'
         and spec['path'] == ASSET and spec['public_url'] == LIVE
         and spec['recipe'] == 'CAPTUREBRIEF_CLIPBOARD_RECOVERY_V1'
         and spec['original_asset_sha256'] == ORIGINAL_HASH
         and spec['expected_asset_sha256'] == CORRECTED_HASH
         and hashval(spec['original_source_sha'], 40)
         and hashval(spec['candidate_sha'], 40) and hashval(spec['fingerprint'])
         and type(spec['pr_number']) is int and 0 < spec['pr_number'] < 10**9,
         'PUBLICATION_SPEC_SCOPE')
    return spec

class PublicationReader(GitHubOriginalReader):
    """Reuse the original no-redirect client and its fixed, bounded GET counter."""
    def _bytes(self, url, *, authenticated, maximum):
        need(self.used_gets < self.max_gets, 'READBACK_BUDGET_EXHAUSTED')
        self.used_gets += 1
        headers = {'User-Agent': 'Portfolio-Brain-publication-readback'}
        if authenticated:
            need(url.startswith('https://api.github.com/repos/' + REPO + '/'), 'PUBLICATION_URL_REFUSED')
            headers.update({'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
            if self._token:
                headers['Authorization'] = 'Bearer ' + self._token
        else:
            need(re.fullmatch(re.escape(LIVE) + r'\?brain-repair=[0-9a-f]{40}', url) is not None,
                 'PUBLICATION_URL_REFUSED')
        try:
            request = urllib.request.Request(url, headers=headers, method='GET')
            with self._opener.open(request, timeout=self.timeout) as response:
                need(response.status == 200, 'PUBLICATION_HTTP_NOT_OK')
                raw = response.read(maximum + 1)
        except (urllib.error.URLError, OSError) as exc:
            raise BatchFault('PUBLICATION_PROVIDER_UNAVAILABLE') from exc
        need(len(raw) <= maximum, 'PUBLICATION_RESPONSE_TOO_LARGE')
        return raw

    def _get(self, route):
        need(type(route) is str and re.fullmatch(
            r'(pulls/[1-9][0-9]*|branches/gh-pages|'
            r'commits/[0-9a-f]{40}/check-runs\?per_page=100|'
            r'compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}|'
            r'actions/runs\?head_sha=[0-9a-f]{40}&per_page=100|'
            r'actions/runs/[1-9][0-9]*/jobs\?per_page=100|'
            r'contents/assets/capturebrief\.js\?ref=[0-9a-f]{40})', route),
            'PUBLICATION_ROUTE_REFUSED')
        raw = self._bytes('https://api.github.com/repos/' + REPO + '/' + route,
                          authenticated=True, maximum=2*1024*1024)
        def pairs(values):
            obj = {}
            for key, value in values:
                need(key not in obj, 'PUBLICATION_DUPLICATE_JSON_KEY')
                obj[key] = value
            return obj
        try:
            doc = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                             parse_constant=lambda value: (_ for _ in ()).throw(BatchFault('PUBLICATION_NONFINITE')))
        except (UnicodeError, ValueError) as exc:
            raise BatchFault('PUBLICATION_JSON_INVALID') from exc
        need(type(doc) is dict, 'PUBLICATION_JSON_INVALID')
        return doc

    @staticmethod
    def _complete_page(doc, key):
        rows = doc.get(key)
        need(type(rows) is list and type(doc.get('total_count')) is int
             and doc['total_count'] == len(rows) and len(rows) <= 100
             and all(type(row) is dict for row in rows), 'PUBLICATION_CENSUS_INCOMPLETE')
        return rows

    def verify(self, spec):
        validate_spec(spec)
        need(self.gets_remaining >= REQUIRED_BUDGET, 'READBACK_BUDGET_EXHAUSTED')
        start = self.used_gets
        number, candidate = spec['pr_number'], spec['candidate_sha']
        pr = self._get('pulls/' + str(number))
        need(pr.get('number') == number and pr.get('merged') is True and pr.get('state') == 'closed'
             and pr.get('head', {}).get('sha') == candidate
             and pr.get('head', {}).get('repo', {}).get('full_name') == REPO
             and pr.get('base', {}).get('ref') == 'gh-pages'
             and pr.get('base', {}).get('repo', {}).get('full_name') == REPO
             and hashval(pr.get('merge_commit_sha'), 40), 'PUBLICATION_PR_NOT_EXACT_MERGE')
        merge_sha = pr['merge_commit_sha']
        checks = self._complete_page(self._get('commits/' + candidate + '/check-runs?per_page=100'), 'check_runs')
        for name in REQUIRED_JOBS:
            matching = [c for c in checks if c.get('name') == name]
            need(len(matching) == 1 and matching[0].get('head_sha') == candidate
                 and matching[0].get('app', {}).get('id') == 15368
                 and matching[0].get('status') == 'completed'
                 and matching[0].get('conclusion') == 'success', 'PUBLICATION_CANDIDATE_QA_NOT_VERIFIED')
        branch = self._get('branches/gh-pages')
        deployed = branch.get('commit', {}).get('sha')
        need(hashval(deployed, 40), 'PUBLICATION_BRANCH_INVALID')
        if deployed != merge_sha:
            comparison = self._get('compare/' + merge_sha + '...' + deployed)
            need(comparison.get('merge_base_commit', {}).get('sha') == merge_sha
                 and comparison.get('status') in ('ahead', 'identical')
                 and comparison.get('behind_by') == 0, 'PUBLICATION_REPAIR_NOT_IN_DEPLOYED_HISTORY')
        runs = self._complete_page(self._get('actions/runs?head_sha=' + deployed + '&per_page=100'), 'workflow_runs')
        quality = [r for r in runs if r.get('name') == 'Website quality'
                   and r.get('path') == '.github/workflows/site-quality.yml' and r.get('event') == 'push']
        pages = [r for r in runs if r.get('path') == 'dynamic/pages/pages-build-deployment' and r.get('event') == 'dynamic']
        for group in (quality, pages):
            need(group and all(type(r.get('id')) is int for r in group), 'PUBLICATION_ORIGINAL_RUN_MISSING')
            latest = max(group, key=lambda r: r['id'])
            need(latest.get('head_sha') == deployed and latest.get('head_branch') == 'gh-pages'
                 and latest.get('repository', {}).get('full_name') == REPO
                 and latest.get('status') == 'completed' and latest.get('conclusion') == 'success',
                 'PUBLICATION_ORIGINAL_RUN_NOT_SUCCESS')
        qa_run = max(quality, key=lambda r: r['id'])
        pages_run = max(pages, key=lambda r: r['id'])
        jobs = self._complete_page(self._get('actions/runs/' + str(qa_run['id']) + '/jobs?per_page=100'), 'jobs')
        for name in REQUIRED_JOBS:
            matching = [j for j in jobs if j.get('name') == name]
            need(len(matching) == 1 and matching[0].get('head_sha') == deployed
                 and matching[0].get('status') == 'completed' and matching[0].get('conclusion') == 'success',
                 'PUBLICATION_BROWSER_JOB_NOT_VERIFIED')
            steps = matching[0].get('steps', [])
            for required in (LIVE_STEP, 'Wait for GitHub Pages to publish this exact release', 'Verify the public deployment'):
                actual = [s for s in steps if s.get('name') == required]
                need(len(actual) == 1 and actual[0].get('status') == 'completed'
                     and actual[0].get('conclusion') == 'success', 'PUBLICATION_LIVE_STEP_NOT_VERIFIED')
        document = self._get('contents/' + ASSET + '?ref=' + deployed)
        need(document.get('type') == 'file' and document.get('encoding') == 'base64'
             and type(document.get('size')) is int and 0 < document['size'] < 256000,
             'PUBLICATION_ASSET_INVALID')
        raw = base64.b64decode(document['content'].replace('\n', ''), validate=True)
        need(len(raw) == document['size'] and hashlib.sha256(raw).hexdigest() == CORRECTED_HASH,
             'PUBLICATION_SOURCE_BYTES_MISMATCH')
        live = self._bytes(LIVE + '?brain-repair=' + deployed, authenticated=False, maximum=256000)
        need(hashlib.sha256(live).hexdigest() == CORRECTED_HASH, 'PUBLICATION_LIVE_BYTES_MISMATCH')
        need(self._get('branches/gh-pages').get('commit', {}).get('sha') == deployed,
             'PUBLICATION_SOURCE_MOVED_DURING_READBACK')
        return dict(schema_version=1, status='ORIGINAL_PUBLISHED_REPAIR_LIVE_VERIFIED',
                    repository=REPO, source_branch='gh-pages', path=ASSET,
                    pr_number=number, candidate_sha=candidate, merge_sha=merge_sha,
                    deployed_sha=deployed, asset_sha256=CORRECTED_HASH,
                    original_asset_sha256=ORIGINAL_HASH, quality_run_id=qa_run['id'],
                    pages_run_id=pages_run['id'], browsers=sorted(REQUIRED_JOBS),
                    provider_gets=self.used_gets-start, provider_writes=0,
                    execution_mode='SUPERVISED_REPAIR_NOT_UNATTENDED_AUTOMERGE',
                    production_accepted=False, six_hour_acceptance_passed=False)
