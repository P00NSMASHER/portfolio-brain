"""Bounded read-only runtime canary; never evidence of repair or release authority."""
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


def probe(get, repository, installation_id, app_slug):
    if repository not in REPOSITORIES:
        raise ValueError('RUNTIME_REPOSITORY_NOT_REVIEWED')
    if installation_id != INSTALLATION_ID or app_slug != APP_SLUG:
        raise ValueError('RUNTIME_APP_IDENTITY_MISMATCH')
    full_name = 'P00NSMASHER/' + repository
    inventory = get('/installation/repositories?per_page=100')
    rows = inventory.get('repositories')
    if (inventory.get('total_count') != 1 or type(rows) is not list
            or len(rows) != 1 or rows[0].get('full_name') != full_name):
        raise ValueError('RUNTIME_TOKEN_REPOSITORY_SCOPE_MISMATCH')
    prefix = '/repos/' + full_name
    repo = get(prefix)
    if repo.get('full_name') != full_name or repo.get('archived') is not False:
        raise ValueError('RUNTIME_REPOSITORY_IDENTITY_MISMATCH')
    branch = repo.get('default_branch')
    if type(branch) is not str or not branch or len(branch) > 255:
        raise ValueError('RUNTIME_BRANCH_INVALID')
    head = get(prefix + '/branches/' + urllib.parse.quote(branch, safe=''))
    sha = head.get('commit', {}).get('sha')
    if type(sha) is not str or re.fullmatch('[0-9a-f]{40}', sha) is None:
        raise ValueError('RUNTIME_SOURCE_INVALID')
    # Read endpoints test each requested capability without changing project state.
    get(prefix + '/actions/runs?per_page=1')
    get(prefix + '/commits/' + sha + '/check-runs?per_page=1')
    get(prefix + '/commits/' + sha + '/status')
    get(prefix + '/pulls?state=open&per_page=1')
    return {
        'schema_version': 1, 'repository': full_name, 'source_sha': sha,
        'installation_id': INSTALLATION_ID, 'app_slug': APP_SLUG,
        'result': 'AUTHENTICATED_READ_CANARY_PASSED',
        'token_repository_count': 1, 'provider_write_actions_verified': False,
        'release_authority_verified': False, 'acceptance_started': False,
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('RUNTIME_REDIRECT_REJECTED')


def main():
    token = os.environ.get('GH_TOKEN', '')
    if not token:
        raise ValueError('RUNTIME_TOKEN_MISSING')
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
                    os.environ.get('INSTALLATION_ID', ''), os.environ.get('APP_SLUG', ''))
    receipt.update(observed_at=datetime.now(timezone.utc).isoformat(),
                   workflow_source_sha=os.environ.get('GITHUB_SHA'),
                   run_id=os.environ.get('GITHUB_RUN_ID'))
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never echo provider bodies, credential-bearing requests, or environment.
        raise SystemExit('RUNTIME_READ_CANARY_FAILED; no write authority granted') from None
