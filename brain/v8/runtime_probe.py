"""Bounded, read-only GitHub App probe; endpoint responses must prove access."""
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

REPOSITORIES = frozenset({
    'portfolio-brain', 'trading-platform', 'abvmschoolstarworld',
    'github-value-hunt-ledger', 'PipsQuestWorld', 'permitplate-nyc',
    'capturebrief', 'x402-product-factory',
})
INSTALLATION_ID = '172257326'
APP_SLUG = 'portfolio-brain-v8-runtime'
MAX_RESPONSE_BYTES = 1048576
_SHA = re.compile(r'[0-9a-f]{40}\Z')
_BRANCH = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,254}\Z')
_STATUS = frozenset({'error', 'failure', 'pending', 'success'})


def _object(value, code):
    if type(value) is not dict:
        raise ValueError(code)
    return value


def _collection(value, key, code):
    value = _object(value, code)
    rows = value.get(key)
    count = value.get('total_count')
    if (type(rows) is not list or type(count) is not int
            or count < len(rows) or any(type(row) is not dict for row in rows)):
        raise ValueError(code)
    return rows, count


def probe(get, repository, installation_id, app_slug):
    """Prove narrow authenticated reads, not write or release authority."""
    if type(repository) is not str or repository not in REPOSITORIES:
        raise ValueError('RUNTIME_REPOSITORY_NOT_REVIEWED')
    if installation_id != INSTALLATION_ID or app_slug != APP_SLUG:
        raise ValueError('RUNTIME_APP_IDENTITY_MISMATCH')
    full_name = 'P00NSMASHER/' + repository
    inventory, total = _collection(
        get('/installation/repositories?per_page=100'),
        'repositories', 'RUNTIME_TOKEN_REPOSITORY_SCOPE_MISMATCH')
    if (total != 1 or len(inventory) != 1
            or inventory[0].get('full_name') != full_name):
        raise ValueError('RUNTIME_TOKEN_REPOSITORY_SCOPE_MISMATCH')

    prefix = '/repos/' + full_name
    repo = _object(get(prefix), 'RUNTIME_REPOSITORY_RESPONSE_INVALID')
    if repo.get('full_name') != full_name or repo.get('archived') is not False:
        raise ValueError('RUNTIME_REPOSITORY_IDENTITY_MISMATCH')
    branch = repo.get('default_branch')
    if (type(branch) is not str or _BRANCH.fullmatch(branch) is None
            or '..' in branch or branch.endswith('.lock')):
        raise ValueError('RUNTIME_BRANCH_INVALID')

    head = _object(get(prefix + '/branches/' + urllib.parse.quote(branch, safe='')),
                   'RUNTIME_BRANCH_RESPONSE_INVALID')
    commit = _object(head.get('commit'), 'RUNTIME_SOURCE_INVALID')
    sha = commit.get('sha')
    if type(sha) is not str or _SHA.fullmatch(sha) is None:
        raise ValueError('RUNTIME_SOURCE_INVALID')

    # A 200 response with an error-shaped or incomplete JSON body is NOT proof.
    _collection(get(prefix + '/actions/runs?per_page=1'),
                'workflow_runs', 'RUNTIME_ACTIONS_RESPONSE_INVALID')
    _collection(get(prefix + '/commits/' + sha + '/check-runs?per_page=1'),
                'check_runs', 'RUNTIME_CHECKS_RESPONSE_INVALID')
    status = _object(get(prefix + '/commits/' + sha + '/status'),
                     'RUNTIME_STATUS_RESPONSE_INVALID')
    statuses = status.get('statuses')
    if (status.get('sha') != sha or status.get('state') not in _STATUS
            or type(statuses) is not list
            or any(type(row) is not dict for row in statuses)):
        raise ValueError('RUNTIME_STATUS_RESPONSE_INVALID')
    pulls = get(prefix + '/pulls?state=open&per_page=1')
    if type(pulls) is not list or any(type(p) is not dict for p in pulls):
        raise ValueError('RUNTIME_PULLS_RESPONSE_INVALID')

    return {
        'schema_version': 1, 'repository': full_name, 'source_sha': sha,
        'installation_id': INSTALLATION_ID, 'app_slug': APP_SLUG,
        'result': 'AUTHENTICATED_READ_CANARY_PASSED',
        'token_repository_count': 1,
        'provider_write_actions_verified': False,
        'release_authority_verified': False, 'acceptance_started': False,
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('RUNTIME_REDIRECT_REJECTED')


def main():
    token = os.environ.get('GH_TOKEN', '')
    source = os.environ.get('GITHUB_SHA', '')
    if not token:
        raise ValueError('RUNTIME_TOKEN_MISSING')
    if _SHA.fullmatch(source) is None:
        raise ValueError('RUNTIME_WORKFLOW_SOURCE_INVALID')
    opener = urllib.request.build_opener(NoRedirect())

    def get(path):
        request = urllib.request.Request('https://api.github.com' + path, headers={
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }, method='GET')
        with opener.open(request, timeout=20) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError('RUNTIME_RESPONSE_TOO_LARGE')
        return json.loads(data)

    receipt = probe(get, os.environ.get('PROBE_REPOSITORY', ''),
                    os.environ.get('INSTALLATION_ID', ''),
                    os.environ.get('APP_SLUG', ''))
    receipt.update(observed_at=datetime.now(timezone.utc).isoformat(),
                   workflow_source_sha=source,
                   run_id=os.environ.get('GITHUB_RUN_ID'))
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never echo provider bodies, requests, tokens, or environment.
        raise SystemExit('RUNTIME_READ_CANARY_FAILED; no write authority granted') from None
