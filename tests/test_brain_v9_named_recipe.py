"""Source-backed regression: named action steps previously refused safe repair."""
import hashlib
from pathlib import Path
import unittest
from brain.core import BrainError
from brain.repair_patch_executor import CHECKOUT, NODE, generate
from brain.v8.engineering import exercise_repair

SOURCE = Path(__file__).parent / 'fixtures/v9/permitplate-tests.source.txt'
REPO = 'P00NSMASHER/permitplate-nyc'
HEAD = 'cf0b459217245a7799550104cc37a9bad462bdf2'
PATH = '.github/workflows/permitplate-tests.yml'


def request(raw):
    return dict(schema_version=1, repository=REPO, source_head_sha=HEAD,
                path=PATH, original_sha256=hashlib.sha256(raw).hexdigest(),
                repair_kind='READONLY_CI_CHECKOUT_HARDENING',
                independent_gate_required=True)


class NamedRecipeTests(unittest.TestCase):
    def test_original_git_blob_and_exact_minimal_change(self):
        raw = SOURCE.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        self.assertEqual(blob, '167cf0a263b41da50927b300decdbce6ecadeaf9')
        result = generate(request(raw), raw)
        expected = raw.decode().replace('actions/checkout@v4\n', CHECKOUT + '\n'
            '        with:\n          persist-credentials: false\n').replace('actions/setup-node@v4', NODE)
        self.assertEqual(result['changed_content'], expected)
        self.assertFalse(result['merge_authority'])

    def test_real_source_negative_and_positive_regression_runs(self):
        raw = SOURCE.read_bytes()
        result = exercise_repair(request(raw), raw)
        self.assertNotEqual(result['original_returncode'], 0)
        self.assertEqual(result['corrected_returncode'], 0)
        self.assertFalse(result['third_party_code_executed'])

    def test_ambiguous_named_checkout_is_refused(self):
        original = SOURCE.read_text()
        for before, after in [
            ('        uses: actions/checkout@v4', '        uses: actions/checkout@v4\n        with:\n          ref: other'),
            ('      - name: Check out repository', '      - name: Check out repository\n        if: true'),
            ('      - name: Check out repository', '      - name: |\n          Check out repository'),
            ('        uses: actions/checkout@v4', '        uses: actions/checkout@v4\n        env:\n          OPTION: value'),
            ('        uses: actions/checkout@v4', '        uses: actions/checkout@v4\n\n        with:\n          ref: other'),
            ('        uses: actions/checkout@v4', '        uses: actions/checkout@v4 # ambiguous'),
            ('      - name: Check out repository\n        uses: actions/checkout@v4',
             '      - name: Write example\n        run: |\n          - name: Check out repository\n            uses: actions/checkout@v4'),
            ('    steps:\n      - name: Check out repository',
             '    run: |\n      - name: Check out repository'),
            ('jobs:\n  regression:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n',
             'description: |\n'),
            ('jobs:\n', 'jobs: |\n'),
            ('  regression:\n', '  regression: |\n'),
        ]:
            raw = original.replace(before, after).encode()
            with self.subTest(after=after), self.assertRaises(BrainError):
                generate(request(raw), raw)


if __name__ == '__main__':
    unittest.main()
