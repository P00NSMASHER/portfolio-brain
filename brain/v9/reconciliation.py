"""Read-only reconciliation of an exact draft intent; never acceptance or absence proof."""
from copy import deepcopy
import base64
import hashlib
import re
import time
from urllib.parse import quote
from brain.core import digest, require
from brain.v8.contracts import parse_utc
from brain.v9.github_observer import _read, _https_get, _sha, _REPO, MAX_RESPONSE

_FIELDS = {'schema_version', 'repository', 'base_sha', 'head_sha', 'pull_number',
           'expected_files', 'actor_login'}


def validate_intent(intent):
    require(type(intent) is dict and set(intent) == _FIELDS, 'V9_DRAFT_INTENT_FIELDS')
    require(type(intent['schema_version']) is int and intent['schema_version'] == 1,
            'V9_DRAFT_INTENT_VERSION')
    require(type(intent['repository']) is str and _REPO.fullmatch(intent['repository']),
            'V9_DRAFT_REPOSITORY')
    _sha(intent['base_sha']); _sha(intent['head_sha'])
    require(intent['base_sha'] != intent['head_sha'], 'V9_DRAFT_SAME_SOURCE')
    require(type(intent['pull_number']) is int and 0 < intent['pull_number'] < 10**9,
            'V9_DRAFT_NUMBER')
    require(type(intent['actor_login']) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,99}(?:\[bot\])?', intent['actor_login']),
            'V9_DRAFT_ACTOR')
    files = intent['expected_files']
    require(type(files) is dict and 0 < len(files) <= 16, 'V9_DRAFT_FILE_BOUND')
    for path, sha in files.items():
        require(type(path) is str and 0 < len(path) <= 1024
                and all(32 < ord(c) < 127 for c in path) and '\\' not in path
                and all(p not in ('', '.', '..') for p in path.split('/')), 'V9_DRAFT_PATH')
        _sha(sha)
    return deepcopy(intent)


def observe_draft(intent, *, token, now, transport=None):
    """Up to 27 bounded GETs, 60-second budget; injected transport is test evidence.

    Missing/uncertain responses raise: they never prove that a write did not occur.
    Stable endpoint observations are not atomic locks or a grant to write/release.
    """
    intent = validate_intent(intent)
    require(type(token) is str and 0 < len(token) <= 4096
            and all(33 <= ord(c) <= 126 for c in token), 'V9_GITHUB_TOKEN_INVALID')
    parse_utc(now)
    deadline = time.monotonic() + 60
    def get(path, credential):
        require(time.monotonic() < deadline, 'V9_GITHUB_TIME_BOUND')
        value = transport(path, credential) if transport is not None else _https_get(path, credential, deadline=deadline)
        require(time.monotonic() < deadline, 'V9_GITHUB_TIME_BOUND')
        return value
    repo, base, head = (intent[k] for k in ('repository', 'base_sha', 'head_sha'))
    root = '/repos/' + repo
    def read(path):
        return _read(get, root + path, token)
    metadata = read('')
    require(metadata.get('full_name') == repo and type(metadata.get('permissions')) is dict
            and metadata['permissions'].get('pull') is True, 'V9_DRAFT_REPOSITORY_PERMISSION')
    branch = metadata.get('default_branch')
    require(type(branch) is str and 0 < len(branch) <= 255
            and all(32 < ord(c) < 127 for c in branch), 'V9_DRAFT_DEFAULT_BRANCH')
    def check_default():
        ref = read('/git/ref/heads/' + quote(branch, safe=''))
        require(ref.get('ref') == 'refs/heads/' + branch and type(ref.get('object')) is dict
                and ref['object'].get('type') == 'commit' and ref['object'].get('sha') == base,
                'V9_DRAFT_SOURCE_DRIFT')
    def check_pr():
        pr = read('/pulls/' + str(intent['pull_number']))
        require(type(pr.get('number')) is int and pr['number'] == intent['pull_number']
                and pr.get('state') == 'open' and pr.get('draft') is True
                and pr.get('merged') is False and pr.get('merged_at') is None
                and type(pr.get('user')) is dict and pr['user'].get('login') == intent['actor_login'],
                'V9_DRAFT_IDENTITY')
        for side, sha in (('base', base), ('head', head)):
            value = pr.get(side)
            require(type(value) is dict and value.get('sha') == sha
                    and type(value.get('repo')) is dict and value['repo'].get('full_name') == repo
                    and type(value.get('ref')) is str and 0 < len(value['ref']) <= 255
                    and all(32 < ord(c) < 127 for c in value['ref']), 'V9_DRAFT_REF')
        require(pr['base']['ref'] == branch, 'V9_DRAFT_BASE_BRANCH')
        return pr['head']['ref']
    check_default()
    head_branch = check_pr()
    def check_candidate_ref():
        ref = read('/git/ref/heads/' + quote(head_branch, safe=''))
        require(ref.get('ref') == 'refs/heads/' + head_branch and type(ref.get('object')) is dict
                and ref['object'].get('type') == 'commit' and ref['object'].get('sha') == head,
                'V9_DRAFT_CANDIDATE_DRIFT')
    check_candidate_ref()
    commit = read('/git/commits/' + head)
    require(commit.get('sha') == head and type(commit.get('parents')) is list
            and len(commit['parents']) == 1 and type(commit['parents'][0]) is dict
            and commit['parents'][0].get('sha') == base and type(commit.get('tree')) is dict,
            'V9_DRAFT_ANCESTRY')
    tree_sha = _sha(commit['tree'].get('sha'))
    comparison = read('/compare/' + base + '...' + head)
    require(type(comparison.get('ahead_by')) is int and comparison['ahead_by'] == 1
            and type(comparison.get('behind_by')) is int and comparison['behind_by'] == 0
            and type(comparison.get('merge_base_commit')) is dict
            and comparison['merge_base_commit'].get('sha') == base, 'V9_DRAFT_COMPARISON')
    changes = comparison.get('files')
    expected = intent['expected_files']
    require(type(changes) is list and len(changes) == len(expected), 'V9_DRAFT_CHANGE_BOUND')
    seen = set()
    for change in changes:
        require(type(change) is dict and type(change.get('filename')) is str
                and change['filename'] in expected and change['filename'] not in seen
                and change.get('status') in ('added', 'modified') and 'previous_filename' not in change
                and change.get('sha') == expected[change['filename']], 'V9_DRAFT_CHANGE')
        seen.add(change['filename'])
    tree = read('/git/trees/' + tree_sha + '?recursive=1')
    require(tree.get('sha') == tree_sha and tree.get('truncated') is False
            and type(tree.get('tree')) is list, 'V9_DRAFT_TREE')
    entries = {}
    for entry in tree['tree']:
        require(type(entry) is dict and type(entry.get('path')) is str
                and entry['path'] not in entries, 'V9_DRAFT_TREE_ENTRY')
        entries[entry['path']] = entry
    files = []
    for path, blob in sorted(expected.items()):
        entry = entries.get(path)
        require(type(entry) is dict and entry.get('type') == 'blob'
                and entry.get('mode') in ('100644', '100755') and entry.get('sha') == blob,
                'V9_DRAFT_FILE_MODE')
        data = read('/contents/' + quote(path, safe='/') + '?ref=' + head)
        require(data.get('type') == 'file' and data.get('path') == path and data.get('sha') == blob
                and 'target' not in data and 'submodule_git_url' not in data
                and data.get('truncated', False) is False and data.get('encoding') == 'base64'
                and type(data.get('content')) is str and type(data.get('size')) is int
                and 0 <= data['size'] <= MAX_RESPONSE, 'V9_DRAFT_CONTENT')
        try:
            raw = base64.b64decode(data['content'].replace('\n', ''), validate=True)
        except (ValueError, UnicodeError):
            raise ValueError('V9_DRAFT_BASE64_INVALID') from None
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        require(len(raw) == data['size'] and actual == blob, 'V9_DRAFT_BLOB_MISMATCH')
        files.append(dict(path=path, blob_sha=blob, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw)))
    require(check_pr() == head_branch, 'V9_DRAFT_HEAD_BRANCH_DRIFT')
    check_candidate_ref()
    check_default()
    # Reobserve metadata too: switching default branches must not preserve a false stable-base receipt.
    final = read('')
    require(final.get('full_name') == repo and final.get('default_branch') == branch
            and type(final.get('permissions')) is dict and final['permissions'].get('pull') is True,
            'V9_DRAFT_DEFAULT_BRANCH_DRIFT')
    return dict(schema_version=1, evidence_kind='AUTHENTICATED_GITHUB_DRAFT_OBSERVATION'
                if transport is None else 'INJECTED_TRANSPORT_OBSERVATION', observed_at=now,
                intent_digest=digest(intent), repository=repo, base_sha=base, head_sha=head,
                pull_number=intent['pull_number'], actor_login=intent['actor_login'],
                default_branch=branch, head_branch=head_branch, files=files,
                outcome='EXACT_DRAFT_OBSERVED', write_authority=False, independent_acceptance=False,
                production_accepted=False, release_authority=False)
