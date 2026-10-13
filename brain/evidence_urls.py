"""V7 canonical original GitHub CI evidence URL validators.

Only canonical commit and check-run pages from the EXACT repository are
accepted for check evidence. URL strings are never fetched or executed here.
Reject redirect/query/fragment, encoded delimiters, lookalike hosts/repos,
traversal and unrelated same-repository pages.
"""
from __future__ import annotations

import re

_REPO = re.compile(r"[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}\Z")
_COMMIT = re.compile(r"commit/[0-9a-f]{40}\Z")
_CHECK_RUN = re.compile(
    r"(?:runs/[1-9][0-9]*|"
    r"actions/runs/[1-9][0-9]*(?:/job/[1-9][0-9]*)?)\Z"
)


def _path(value, repository):
    if (type(value) is not str or type(repository) is not str
            or _REPO.fullmatch(repository) is None or len(value) > 1200):
        return None
    prefix = f"https://github.com/{repository}/"
    if not value.startswith(prefix):
        return None
    # Only ASCII literal path segments allowed; exact full-match regex
    # below disallows username, slash escapes, ports, query and fragments.
    suffix = value[len(prefix):]
    if not suffix or not suffix.isascii() or any(
        ord(c) < 33 or ord(c) > 126 for c in suffix
    ):
        return None
    return suffix


def check_run_ref(value, repository):
    """Only actual GitHub check-run / workflow job evidence under one repo."""
    suffix = _path(value, repository)
    return suffix is not None and _CHECK_RUN.fullmatch(suffix) is not None


def commit_ref(value, repository, revision=None):
    """An original source commit page, optionally exactly one expected SHA."""
    suffix = _path(value, repository)
    if suffix is None or _COMMIT.fullmatch(suffix) is None:
        return False
    return revision is None or (
        type(revision) is str and suffix == "commit/" + revision
    )


def repo_evidence_ref(value, repository):
    """Allowlist original commit or CI check-run pages, nothing else."""
    return commit_ref(value, repository) or check_run_ref(value, repository)

_BLOB = re.compile(
    r"blob/[0-9a-f]{40}/[A-Za-z0-9_.@+/-]{1,500}\Z"
)


def blob_ref(value, repository, revision=None, source_path=None):
    """Review-only immutable GitHub code blob reference, not reuse rights.

    Require a literal exact repository, full commit SHA, and canonical
    unencoded source path. Reject encoded traversal, URL parameters, unusual
    schemes, fragments and misleading lookalikes. No link is followed.
    """
    suffix = _path(value, repository)
    if suffix is None or _BLOB.fullmatch(suffix) is None:
        return False
    blob_sha, path = suffix[5:].split("/", 1)
    parts = path.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        return False
    if revision is not None and (
        type(revision) is not str or blob_sha != revision
    ):
        return False
    if source_path is not None and (
        type(source_path) is not str or path != source_path
    ):
        return False
    return True
