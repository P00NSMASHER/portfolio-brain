"""Registry declarations must never become inferred acceptance or measurements."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from brain.core import BrainError
from brain.v9.registry import MAX_BYTES, load_registry, validate_registry

ROOT = Path(__file__).resolve().parents[1]


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads((ROOT / 'docs/genesis/V9_CAPABILITY_MATRIX.json').read_text())
        self.score = json.loads((ROOT / 'docs/genesis/SCORECARD.json').read_text())

    def validate(self):
        return validate_registry(self.matrix, self.score, repository_root=ROOT)

    def test_real_registry_reports_declarations_without_mutation(self):
        original = copy.deepcopy((self.matrix, self.score))
        report = self.validate()
        self.assertEqual(sum(report.capability_counts.values()), 66)
        self.assertEqual(len(report.unmeasured_metrics), 14)
        self.assertEqual(report.measured_metrics, ())
        self.assertIsNone(report.component_source_revisions['github-source-observer'])
        self.assertEqual(report.component_source_revisions['local-mission-foundation'],
                         'aaa4bd8982eb594bbdefa6374c430823075853e0')
        self.assertIn('File existence does not establish passing tests.', report.limitations)
        self.assertEqual((self.matrix, self.score), original)
        self.assertEqual(asdict(load_registry(ROOT)), asdict(report))

    def test_duplicates_missing_ids_wrong_tiers_and_unrecognized_status_fail(self):
        for key, value in [('id', 2), ('id', True), ('tier', 4),
                           ('name', self.matrix['capabilities'][1]['name'].upper()),
                           ('status', 'PERFECT')]:
            with self.subTest(key=key, value=value):
                saved = self.matrix['capabilities'][0][key]
                self.matrix['capabilities'][0][key] = value
                with self.assertRaises(BrainError):
                    self.validate()
                self.matrix['capabilities'][0][key] = saved
        self.matrix['capabilities'].pop()
        with self.assertRaises(BrainError):
            self.validate()

    def test_evidence_and_test_files_are_required_for_tested_components(self):
        component = self.matrix['components'][0]
        for key, value in [('evidence', []), ('test_paths', []),
                           ('test_paths', ['tests/does-not-exist.py']),
                           ('source_paths', ['../outside.py']),
                           ('source_paths', ['/etc/passwd']),
                           ('source_paths', ['brain//v9/missions.py']),
                           ('production_verified', True), ('source_revision', 'main')]:
            with self.subTest(key=key, value=value):
                saved = copy.deepcopy(component)
                component[key] = value
                with self.assertRaises(BrainError):
                    self.validate()
                component.clear()
                component.update(saved)

    def test_source_revision_is_preserved_but_never_inferred_from_baseline(self):
        component = self.matrix['components'][0]
        component['source_revision'] = 'a' * 40
        report = self.validate()
        self.assertEqual(report.component_source_revisions[component['id']], 'a' * 40)
        self.assertNotEqual(report.baseline_source, 'a' * 40)

    def test_unknown_is_not_zero_and_measurement_requires_evidence(self):
        metric = self.score['metrics']['autonomous_repairs_delivered']
        for update in ({'value': 0}, {'status': 'MEASURED', 'value': 1},
                       {'status': 'MEASURED', 'value': True, 'evidence': ['receipt']},
                       {'status': 'MEASURED', 'value': -1, 'evidence': ['receipt']},
                       {'status': 'MEASURED', 'value': float('nan'), 'evidence': ['receipt']}):
            with self.subTest(update=update):
                saved = copy.deepcopy(metric)
                metric.update(update)
                with self.assertRaises(BrainError):
                    self.validate()
                metric.clear()
                metric.update(saved)
        metric.update(status='MEASURED', value=0, evidence=['source-bound-external-receipt'])
        report = self.validate()
        self.assertEqual(report.measured_metrics, ('autonomous_repairs_delivered',))
        self.assertIn('Evidence references are declarations; not independently authenticated.',
                      report.limitations)

    def test_baseline_mismatch_and_authority_change_fail(self):
        self.score['baseline_source'] = 'a' * 40
        with self.assertRaises(BrainError):
            self.validate()
        self.score['baseline_source'] = self.matrix['baseline_source']
        self.matrix['authority'] = 'RELEASE_AUTHORIZED'
        with self.assertRaises(BrainError):
            self.validate()

    def test_bounded_duplicate_safe_reader_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / 'docs/genesis'
            docs.mkdir(parents=True)
            path = docs / 'V9_CAPABILITY_MATRIX.json'
            for data in ('{"x":1,"x":2}', '{"x":NaN}', ' ' * (MAX_BYTES + 1),
                         '[' * 2000, '[]'):
                with self.subTest(data=data[:20]):
                    path.write_text(data)
                    with self.assertRaises((BrainError, ValueError)):
                        load_registry(root)
            path.unlink()
            path.symlink_to(ROOT / 'docs/genesis/V9_CAPABILITY_MATRIX.json')
            with self.assertRaises(BrainError):
                load_registry(root)
            alias = root / 'alias'
            alias.symlink_to(ROOT, target_is_directory=True)
            with self.assertRaises(BrainError):
                load_registry(alias)

    def test_reference_symlinks_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'linked.py').symlink_to(ROOT / 'brain/v9/missions.py')
            for row in self.matrix['capabilities']:
                row['reusable_components'] = []
            self.matrix['components'][0]['source_paths'] = ['linked.py']
            with self.assertRaises(BrainError):
                validate_registry(self.matrix, self.score, repository_root=root)


if __name__ == '__main__':
    unittest.main()
