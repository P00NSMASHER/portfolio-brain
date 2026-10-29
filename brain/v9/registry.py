"""Read-only validation of declared v9 maturity; never certification or promotion.

Repository paths are checked as files, not executed. Evidence references are
preserved, not fetched or treated as independent proof of successful execution.
"""
from collections import Counter
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from brain.core import require

MAX_BYTES = 1_000_000
STATUSES = ('NOT_STARTED', 'SPECIFIED', 'IMPLEMENTED', 'TESTED',
            'SANDBOX_VERIFIED', 'LIVE_SCOPED', 'PRODUCTION_VERIFIED',
            'OUTCOME_VERIFIED', 'BLOCKED')
EVIDENCED = set(STATUSES[3:8])
METRICS = frozenset(('autonomous_repairs_delivered', 'mean_time_to_diagnose_seconds',
                    'mean_time_to_recover_seconds', 'recurring_failures_prevented',
                    'human_interventions', 'cross_repository_improvements_delivered',
                    'critical_regressions_detected', 'deployment_reliability',
                    'rollback_reliability', 'reusable_capabilities_created',
                    'performance_improvement', 'resource_consumption',
                    'verified_research_outcomes', 'new_functionality_delivered'))


@dataclass(frozen=True)
class RegistryReport:
    """Counts describe declarations only; missing provenance remains explicit."""
    baseline_source: str
    capability_counts: dict[str, int]
    component_counts: dict[str, int]
    measured_metrics: tuple[str, ...]
    unmeasured_metrics: tuple[str, ...]
    component_evidence: dict[str, tuple[str, ...]]
    component_source_revisions: dict[str, str | None]
    limitations: tuple[str, ...] = (
        'Report only; no release authority or maturity advancement.',
        'File existence does not establish passing tests.',
        'Evidence references are declarations; not independently authenticated.',
        'Baseline revision does not bind component evidence to current source.',
        'Local filesystem checks assume no hostile concurrent path replacement.',
    )


def _strings(value: Any, *, nonempty: bool = False) -> list[str]:
    require(type(value) is list and len(value) <= 256
            and all(type(item) is str and 0 < len(item) <= 2048 for item in value)
            and (not nonempty or bool(value)), 'V9_REGISTRY_STRINGS')
    return value


def _file(root: Path, value: str, *, directory: bool = False) -> Path:
    require(type(value) is str and 0 < len(value) <= 1024
            and '\\' not in value, 'V9_REGISTRY_PATH')
    parts = (value[:-1] if directory and value.endswith('/') else value).split('/')
    require(not PurePosixPath(value).is_absolute()
            and all(part not in ('', '.', '..') for part in parts), 'V9_REGISTRY_PATH')
    current = root
    for part in parts:
        current = current / part
        require(not current.is_symlink(), 'V9_REGISTRY_SYMLINK')
    require(current.is_dir() if directory else current.is_file(), 'V9_REGISTRY_FILE_MISSING')
    return current


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'V9_REGISTRY_DUPLICATE_KEY')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('V9_REGISTRY_NONFINITE_JSON')


def _read(root: Path, path: str) -> dict:
    target = _file(root, path)
    fd = os.open(target, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, 'V9_REGISTRY_SIZE')
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError('V9_REGISTRY_JSON') from error
    require(type(value) is dict, 'V9_REGISTRY_OBJECT')
    return value


def _sha(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{40}', value) is not None,
            'V9_REGISTRY_SOURCE')


def _status(row):
    require(type(row) is dict and row.get('status') in STATUSES, 'V9_REGISTRY_STATUS')
    _strings(row.get('evidence'), nonempty=row['status'] in EVIDENCED)


def validate_registry(matrix: dict, scorecard: dict, *, repository_root: Path) -> RegistryReport:
    """Validate schema and local references without changing input or running code."""
    root = Path(repository_root).absolute()
    require(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)),
            'V9_REGISTRY_ROOT')
    require(type(matrix) is dict and type(scorecard) is dict, 'V9_REGISTRY_OBJECT')
    for document in (matrix, scorecard):
        require(type(document.get('schema_version')) is int
                and document['schema_version'] == 1, 'V9_REGISTRY_VERSION')
        _sha(document.get('baseline_source'))
    require(matrix['baseline_source'] == scorecard['baseline_source'], 'V9_REGISTRY_BASELINE')
    require(matrix.get('authority') == 'REPORT_ONLY_NOT_RELEASE_AUTHORIZATION',
            'V9_REGISTRY_AUTHORITY')
    rows = matrix.get('capabilities')
    require(type(rows) is list and len(rows) == 66, 'V9_REGISTRY_CAPABILITIES')
    ids, names = set(), set()
    for row in rows:
        _status(row)
        number, name = row.get('id'), row.get('name')
        require(type(number) is int and 1 <= number <= 66 and number not in ids,
                'V9_REGISTRY_ID')
        require(type(name) is str and 0 < len(name.strip()) <= 200
                and name.casefold().strip() not in names, 'V9_REGISTRY_NAME')
        tier = 1 if number <= 12 else 2 if number <= 27 else 3 if number <= 42 else 4
        require(type(row.get('tier')) is int and row['tier'] == tier, 'V9_REGISTRY_TIER')
        for field in ('required_tools', 'required_permissions', 'supported_operations',
                      'security_constraints', 'test_coverage', 'verification_requirements'):
            _strings(row.get(field))
        require(type(row.get('execution_environment')) is str
                and bool(row['execution_environment']), 'V9_REGISTRY_ENVIRONMENT')
        limits = row.get('resource_limits')
        require(type(limits) is dict and 0 < len(limits) <= 32
                and all(type(key) is str and type(value) is int and value >= 0
                        for key, value in limits.items()), 'V9_REGISTRY_LIMITS')
        for path in _strings(row.get('reusable_components')):
            _file(root, path, directory=path.endswith('/'))
        if row['status'] == 'BLOCKED':
            dependency = row.get('remaining_dependency')
            require(type(dependency) is str and 0 < len(dependency.strip()) <= 2048,
                    'V9_REGISTRY_BLOCKER')
        ids.add(number)
        names.add(name.casefold().strip())
    components = matrix.get('components', [])
    require(type(components) is list and len(components) <= 256, 'V9_REGISTRY_COMPONENTS')
    evidence, revisions = {}, {}
    for row in components:
        _status(row)
        identity = row.get('id')
        require(type(identity) is str and re.fullmatch('[a-z0-9][a-z0-9-]{0,99}', identity)
                and identity not in evidence, 'V9_REGISTRY_COMPONENT_ID')
        related = row.get('full_capabilities')
        require(type(related) is list and 0 < len(related) <= 66
                and all(type(item) is int and item in ids for item in related)
                and len(set(related)) == len(related), 'V9_REGISTRY_COMPONENT_LINK')
        for field in ('source_paths', 'test_paths'):
            required = row['status'] in EVIDENCED or (
                field == 'source_paths' and row['status'] == 'IMPLEMENTED')
            for path in _strings(row.get(field), nonempty=required):
                _file(root, path)
        require(type(row.get('production_verified')) is bool
                and row['production_verified'] == (row['status'] in
                    ('PRODUCTION_VERIFIED', 'OUTCOME_VERIFIED')), 'V9_REGISTRY_PRODUCTION')
        require(type(row.get('environment')) is str and bool(row['environment']),
                'V9_REGISTRY_ENVIRONMENT')
        for field in ('permissions', 'operations'):
            _strings(row.get(field), nonempty=True)
        revision = row.get('source_revision')
        if revision is not None:
            _sha(revision)
        evidence[identity] = tuple(row['evidence'])
        revisions[identity] = revision
    metrics = scorecard.get('metrics')
    require(type(metrics) is dict and set(metrics) == METRICS, 'V9_REGISTRY_METRICS')
    measured, unknown = [], []
    for name, metric in metrics.items():
        require(type(metric) is dict, 'V9_REGISTRY_METRIC')
        state, value = metric.get('status'), metric.get('value')
        require(state in ('UNMEASURED', 'MEASURED'), 'V9_REGISTRY_METRIC_STATUS')
        _strings(metric.get('evidence'), nonempty=state == 'MEASURED')
        if state == 'UNMEASURED':
            require(value is None and not metric['evidence'], 'V9_REGISTRY_UNKNOWN_VALUE')
            unknown.append(name)
        else:
            require(type(value) in (int, float) and abs(value) <= 1e100 and math.isfinite(value),
                    'V9_REGISTRY_METRIC_VALUE')
            require(name == 'performance_improvement' or value >= 0,
                    'V9_REGISTRY_METRIC_RANGE')
            if name in ('deployment_reliability', 'rollback_reliability'):
                require(value <= 1, 'V9_REGISTRY_METRIC_RANGE')
            measured.append(name)
    return RegistryReport(matrix['baseline_source'], dict(Counter(r['status'] for r in rows)),
                          dict(Counter(r['status'] for r in components)), tuple(sorted(measured)),
                          tuple(sorted(unknown)), evidence, revisions)


def load_registry(repository_root: Path) -> RegistryReport:
    """Read only the fixed registry paths with bounded, duplicate-safe JSON parsing."""
    root = Path(repository_root).absolute()
    require(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)),
            'V9_REGISTRY_ROOT')
    return validate_registry(_read(root, 'docs/genesis/V9_CAPABILITY_MATRIX.json'),
                             _read(root, 'docs/genesis/SCORECARD.json'), repository_root=root)
