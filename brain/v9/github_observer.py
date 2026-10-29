"""Bounded authenticated read-only GitHub observations; never a release grant.

The optional transport is a unit-test seam, not a trust boundary. Evidence is an
observation made by this process, not a signed attestation or durable permission.
"""
import base64
import hashlib
import http.client
import json
import re
import time
from urllib.parse import quote
from brain.core import require
from brain.v8.contracts import parse_utc

MAX_RESPONSE = 1024 * 1024
TIMEOUT = 15
_SHA = re.compile(r'[0-9a-f]{40}')
_REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'V9_GITHUB_DUPLICATE_JSON')
        result[key] = value
    return result


def _https_get(path, token, *, deadline=None):
    """Direct TLS connection: no proxies, redirects, URL input, or body logging."""
    deadline = time.monotonic() + TIMEOUT if deadline is None else min(deadline, time.monotonic() + TIMEOUT)
    require(deadline > time.monotonic(), 'V9_GITHUB_TIME_BOUND')
    connection = http.client.HTTPSConnection('api.github.com', timeout=min(TIMEOUT, deadline - time.monotonic()))
    try:
        connection.request('GET', path, headers={
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'portfolio-brain-v9-source-observer'})
        response = connection.getresponse()
        require(response.status == 200, 'V9_GITHUB_HTTP_REJECTED')
        require(response.getheader('Content-Encoding', 'identity') == 'identity',
                'V9_GITHUB_ENCODING_REJECTED')
        chunks, count = [], 0
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'V9_GITHUB_TIME_BOUND')
            sock = connection.sock
            if sock is not None:
                sock.settimeout(min(TIMEOUT, remaining))
            chunk = response.read1(min(65536, MAX_RESPONSE + 1 - count))
            require(time.monotonic() < deadline, 'V9_GITHUB_TIME_BOUND')
            if not chunk:
                break
            count += len(chunk)
            require(count <= MAX_RESPONSE, 'V9_GITHUB_RESPONSE_BOUND')
            chunks.append(chunk)
        payload = b''.join(chunks)
        return payload
    except (OSError, http.client.HTTPException):
        raise ValueError('V9_GITHUB_TRANSPORT_FAILED') from None
    finally:
        connection.close()


def _read(transport, path, token):
    try:
        payload = transport(path, token)
        require(type(payload) is bytes and len(payload) <= MAX_RESPONSE,
                'V9_GITHUB_RESPONSE_BOUND')
        data = json.loads(payload.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        require(type(data) is dict, 'V9_GITHUB_RESPONSE_OBJECT')
        return data
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError('V9_GITHUB_INVALID_RESPONSE') from None


def _sha(value):
    require(type(value) is str and _SHA.fullmatch(value), 'V9_GITHUB_SHA_INVALID')
    return value


def observe_repositories(requests, *, token, now, transport=None):
    """Observe up to 16 repos/16 files each at stable default-branch heads.

    No source bytes or credentials appear in returned evidence. Total requests
    are bounded to 336, each response to 1 MiB and response deadline to 15 seconds, with a 60-second observation budget.
    Head stability only covers each observation interval; callers must recheck
    immediately before any independently authorized write.
    """
    require(type(token) is str and 0 < len(token) <= 4096
            and all(33 <= ord(char) <= 126 for char in token), 'V9_GITHUB_TOKEN_INVALID')
    parse_utc(now)
    require(type(requests) is dict and 0 < len(requests) <= 16, 'V9_GITHUB_REPO_BOUND')
    require(all(type(repo) is str and _REPO.fullmatch(repo) for repo in requests),
            'V9_GITHUB_REPOSITORY_INVALID')
    require(len({repo.casefold() for repo in requests}) == len(requests), 'V9_GITHUB_REPOSITORY_ALIAS')
    for paths in requests.values():
        require(type(paths) is list and len(paths) <= 16 and all(type(p) is str for p in paths)
                and len(set(paths)) == len(paths),
                'V9_GITHUB_PATH_BOUND')
        require(all(type(path) is str and 0 < len(path) <= 1024
                    and all(32 < ord(c) < 127 for c in path)
                    and '\\' not in path and all(p not in ('', '.', '..') for p in path.split('/'))
                    for path in paths), 'V9_GITHUB_PATH_INVALID')
    deadline = time.monotonic() + 60
    def get(path, token):
        require(time.monotonic() < deadline, 'V9_GITHUB_TIME_BOUND')
        result = transport(path, token) if transport is not None else _https_get(path, token, deadline=deadline)
        require(time.monotonic() < deadline, 'V9_GITHUB_TIME_BOUND')
        return result
    heads, evidence = {}, []
    for repo, paths in sorted(requests.items()):
        root = '/repos/' + repo
        metadata = _read(get, root, token)
        require(metadata.get('full_name') == repo, 'V9_GITHUB_CANONICAL_REPOSITORY')
        permissions = metadata.get('permissions')
        require(type(permissions) is dict and permissions.get('pull') is True,
                'V9_GITHUB_READ_PERMISSION_REQUIRED')
        branch = metadata.get('default_branch')
        require(type(branch) is str and 0 < len(branch) <= 255 and all(32 < ord(c) < 127 for c in branch),
                'V9_GITHUB_BRANCH_INVALID')
        branch_path = root + '/git/ref/heads/' + quote(branch, safe='')

        def head():
            result = _read(get, branch_path, token)
            require(result.get('ref') == 'refs/heads/' + branch and type(result.get('object')) is dict
                    and result['object'].get('type') == 'commit', 'V9_GITHUB_REF_INVALID')
            return _sha(result['object'].get('sha'))

        source_sha = head()
        files = []
        tree_entries = {}
        if paths:
            commit = _read(get, root + '/git/commits/' + source_sha, token)
            require(commit.get('sha') == source_sha and type(commit.get('tree')) is dict,
                    'V9_GITHUB_COMMIT_INVALID')
            tree_sha = _sha(commit['tree'].get('sha'))
            tree = _read(get, root + '/git/trees/' + tree_sha + '?recursive=1', token)
            require(tree.get('sha') == tree_sha and tree.get('truncated') is False
                    and type(tree.get('tree')) is list, 'V9_GITHUB_TREE_INVALID')
            for entry in tree['tree']:
                require(type(entry) is dict and type(entry.get('path')) is str
                        and entry['path'] not in tree_entries, 'V9_GITHUB_TREE_ENTRY_INVALID')
                tree_entries[entry['path']] = entry
        for path in paths:
            entry = tree_entries.get(path)
            require(type(entry) is dict and entry.get('type') == 'blob'
                    and entry.get('mode') in ('100644', '100755'), 'V9_GITHUB_FILE_MODE_INVALID')
            data = _read(get, root + '/contents/' + quote(path, safe='/') + '?ref=' + source_sha, token)
            require(data.get('type') == 'file' and data.get('path') == path
                    and 'target' not in data and 'submodule_git_url' not in data
                    and data.get('truncated', False) is False and data.get('encoding') == 'base64',
                    'V9_GITHUB_FILE_TYPE_INVALID')
            content, size = data.get('content'), data.get('size')
            require(type(content) is str and type(size) is int and 0 <= size <= MAX_RESPONSE,
                    'V9_GITHUB_FILE_CONTENT_INVALID')
            try:
                raw = base64.b64decode(content.replace('\n', ''), validate=True)
            except (ValueError, UnicodeError):
                raise ValueError('V9_GITHUB_BASE64_INVALID') from None
            blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            require(len(raw) == size and blob == _sha(data.get('sha')) and blob == _sha(entry.get('sha')), 'V9_GITHUB_BLOB_MISMATCH')
            files.append(dict(path=path, blob_sha=blob, sha256=hashlib.sha256(raw).hexdigest(), size=size))
        require(head() == source_sha, 'V9_GITHUB_SOURCE_CHANGED')
        heads[repo] = source_sha
        evidence.append(dict(repository=repo, default_branch=branch, source_sha=source_sha,
                             permissions_observed={'pull': True}, files=files))
    return dict(schema_version=1, evidence_kind='AUTHENTICATED_GITHUB_READ_OBSERVATION' if transport is None
                else 'INJECTED_TRANSPORT_OBSERVATION', observed_at=now, source_heads=heads,
                repositories=evidence, write_authority=False, production_accepted=False)
