#!/usr/bin/env python3
"""Restore the newest validated exact-run workflow-liveness receipt."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from runtime.artifact_http import open_url
from runtime.artifact_restore import _atomic_write

ARTIFACT_NAME = 'portfolio-workflow-liveness'
MEMBER_NAME = 'workflow_liveness_receipt.json'
MAX_BYTES = 1_048_576


class LivenessArtifactError(RuntimeError):
    pass


def _time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith('Z'):
        raise LivenessArtifactError('liveness timestamp must be UTC')
    return datetime.fromisoformat(value[:-1] + '+00:00').astimezone(timezone.utc)


def validate_receipt(document: dict) -> None:
    required = {
        'api_requests','authority_granted','checked_at','dispatches','hard_stop_reason',
        'schema_version','status','targets','verified_work_target_count'
    }
    if not isinstance(document, dict) or set(document) != required:
        raise LivenessArtifactError('workflow liveness receipt fields changed')
    if document['schema_version'] != '1.0.0' or document['authority_granted'] is not False:
        raise LivenessArtifactError('workflow liveness receipt identity/authority invalid')
    _time(document['checked_at'])
    if document['status'] not in {'HEALTHY_VERIFIED_WORK','RECENT_RUNS_WORK_UNVERIFIED','RECOVERY_DISPATCHED','BLOCKED_ADMISSION_PREFLIGHT'}:
        raise LivenessArtifactError('workflow liveness status invalid')
    if type(document['api_requests']) is not int or document['api_requests'] < 0:
        raise LivenessArtifactError('workflow liveness API count invalid')
    if not isinstance(document['dispatches'], list) or not isinstance(document['targets'], list):
        raise LivenessArtifactError('workflow liveness collections invalid')
    if not 1 <= len(document['targets']) <= 8:
        raise LivenessArtifactError('workflow liveness target count invalid')
    verified = 0
    seen = set()
    for row in document['targets']:
        if not isinstance(row, dict):
            raise LivenessArtifactError('workflow liveness target invalid')
        name = row.get('workflow_name')
        if not isinstance(name, str) or not name or name in seen:
            raise LivenessArtifactError('workflow liveness target identity invalid')
        seen.add(name)
        if not isinstance(row.get('workflow_file'), str) or not row['workflow_file'].endswith('.yml'):
            raise LivenessArtifactError('workflow liveness target file invalid')
        if type(row.get('dispatch_required')) is not bool:
            raise LivenessArtifactError('workflow liveness dispatch flag invalid')
        if row.get('latest_run_id') is not None and type(row.get('latest_run_id')) is not int:
            raise LivenessArtifactError('workflow liveness run id invalid')
        if row.get('status') == 'HEALTHY_VERIFIED_WORK':
            if row.get('work_proof_status') != 'VERIFIED_WORK':
                raise LivenessArtifactError('verified target missing work proof')
            verified += 1
    if document['verified_work_target_count'] != verified:
        raise LivenessArtifactError('workflow liveness verified target count mismatch')


def _canonical_hash(document: dict) -> str:
    raw = json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def restore(output: Path, metadata_output: Path | None = None) -> str:
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('PORTFOLIO_GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY')
    current_run = os.environ.get('GITHUB_RUN_ID')
    expected_branch = os.environ.get('GITHUB_REF_NAME')
    if not token or not repo:
        return 'NO_ACTIONS_CONTEXT'
    used = 0

    def get(url: str) -> bytes:
        nonlocal used
        last = None
        for attempt in range(3):
            if used >= 6:
                raise LivenessArtifactError('liveness artifact request budget exceeded')
            used += 1
            request = urllib.request.Request(url, headers={
                'Accept':'application/vnd.github+json',
                'Authorization':f'Bearer {token}',
                'X-GitHub-Api-Version':'2022-11-28',
                'User-Agent':'portfolio-brain-workflow-liveness-restore/1.0',
            }, method='GET')
            try:
                with open_url(request, timeout=20) as response:
                    return response.read()
            except Exception as exc:
                last = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        raise LivenessArtifactError(str(last))

    data = json.loads(get(f'https://api.github.com/repos/{repo}/actions/artifacts?name={ARTIFACT_NAME}&per_page=100').decode())
    candidates = [
        row for row in data.get('artifacts', [])
        if not row.get('expired')
        and str((row.get('workflow_run') or {}).get('id')) != str(current_run)
        and (expected_branch is None or (row.get('workflow_run') or {}).get('head_branch') == expected_branch)
    ]
    candidates.sort(key=lambda row: (row.get('created_at',''), row.get('id',0)), reverse=True)
    valid = []
    for row in candidates[:5]:
        url = row.get('archive_download_url')
        if not isinstance(url, str) or not url:
            continue
        try:
            raw = get(url)
            if len(raw) > MAX_BYTES:
                raise LivenessArtifactError('liveness artifact archive too large')
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                matches = [info for info in archive.infolist() if info.filename == MEMBER_NAME and not info.is_dir()]
                if len(matches) != 1 or matches[0].file_size > MAX_BYTES:
                    raise LivenessArtifactError('liveness receipt member invalid')
                body = archive.read(matches[0])
            document = json.loads(body.decode('utf-8'))
            validate_receipt(document)
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile, LivenessArtifactError):
            continue
        valid.append((document['checked_at'], _canonical_hash(document), row, body))
    if not valid:
        return 'NO_VALID_LIVENESS_ARTIFACT'
    newest_time = max(_time(entry[0]) for entry in valid)
    newest = [entry for entry in valid if _time(entry[0]) == newest_time]
    if len({entry[1] for entry in newest}) != 1:
        raise LivenessArtifactError('conflicting newest workflow liveness receipts')
    checked_at, receipt_hash, row, body = newest[0]
    _atomic_write(output, body)
    if metadata_output is not None:
        run = row.get('workflow_run') or {}
        metadata = {
            'schema_version':'1.0.0','restore_status':'RESTORED','artifact_id':row.get('id'),
            'artifact_name':row.get('name'),'artifact_created_at':row.get('created_at'),
            'artifact_expires_at':row.get('expires_at'),'source_run_id':run.get('id'),
            'source_head_sha':run.get('head_sha'),'receipt_checked_at':checked_at,
            'receipt_hash':receipt_hash,'candidates_inspected':min(len(candidates),5),
        }
        _atomic_write(metadata_output, (json.dumps(metadata, sort_keys=True) + '\n').encode('utf-8'))
    return 'RESTORED'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--metadata-output', default=None)
    args = parser.parse_args()
    print(restore(Path(args.output), None if args.metadata_output is None else Path(args.metadata_output)))


if __name__ == '__main__':
    main()
