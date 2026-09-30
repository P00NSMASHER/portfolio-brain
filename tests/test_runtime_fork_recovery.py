import io
import json
import unittest
import zipfile

from runtime.artifact_restore import InvalidStateArtifact
from runtime.artifact_state import _resolve_dominant_runtime_fork, _resolve_exact_main_observation_fork
from runtime.state import advance_cycle, bootstrap_state, canonical_hash, cycle_id_for


def make_receipt(state, *, mode, finished_at, observations):
    target = observations[0]['repository_id'] if mode == 'observe' and len(observations) == 1 else None
    body = {
        'schema_version': '1.0.0',
        'cycle_id': cycle_id_for(state, mode=mode, target_repository_id=target, observations=observations),
        'mode': mode,
        'started_at': finished_at,
        'finished_at': finished_at,
        'status': 'PASS',
        'reason': None,
        'observations': observations,
        'api_requests': len(observations),
    }
    return {**body, 'receipt_hash': canonical_hash(body)}


def observation(state, rid, at, current_sha=None):
    prior = state['repositories'][rid]['cursor_sha']
    current = current_sha or prior
    return {
        'repository_id': rid,
        'source_ref': state['repositories'][rid]['source_ref'],
        'observed_at': at,
        'status': 'CHANGED' if current != prior else 'UNCHANGED',
        'prior_sha': prior,
        'current_sha': current,
    }


def bundle(state, receipt):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('runtime_state.json', json.dumps(state).encode())
        archive.writestr('cycle_receipt.json', json.dumps(receipt).encode())
    return out.getvalue()


def candidate(artifact_id, created_at, url, *, head_sha=None):
    return {
        'id': artifact_id,
        'name': 'portfolio-runtime-state',
        'created_at': created_at,
        'expires_at': '2026-10-28T00:00:00Z',
        'archive_download_url': url,
        'expired': False,
        'workflow_run': {
            'id': artifact_id + 100,
            'head_branch': 'main',
            'head_sha': head_sha or str(artifact_id).zfill(40),
        },
    }


class RuntimeForkRecoveryTests(unittest.TestCase):
    def fork(self, *, conflicting_observe=False):
        base = bootstrap_state(now='2026-09-28T08:00:00Z')
        parent_receipt = make_receipt(base, mode='sync', finished_at='2026-09-28T09:00:00Z', observations=[])
        parent = advance_cycle(base, parent_receipt)

        observe_sha = 'e' * 40 if conflicting_observe else parent['repositories']['REPO-008']['cursor_sha']
        observe_rows = [observation(parent, 'REPO-008', '2026-09-28T10:00:00Z', observe_sha)]
        observe_receipt = make_receipt(parent, mode='observe', finished_at='2026-09-28T10:00:00Z', observations=observe_rows)
        observe_state = advance_cycle(parent, observe_receipt)

        sync_rows = [
            observation(parent, 'REPO-003', '2026-09-28T10:01:00Z', 'd' * 40),
            observation(parent, 'REPO-008', '2026-09-28T10:01:00Z'),
        ]
        sync_receipt = make_receipt(parent, mode='sync', finished_at='2026-09-28T10:01:00Z', observations=sync_rows)
        sync_state = advance_cycle(parent, sync_receipt)
        return observe_state, observe_receipt, sync_state, sync_receipt

    def test_unique_later_sync_that_subsumes_observe_fork_is_selected(self):
        observe_state, observe_receipt, sync_state, sync_receipt = self.fork()
        data = {'artifacts': [candidate(2, '2026-09-28T10:02:00Z', 'sync'), candidate(1, '2026-09-28T10:01:00Z', 'observe')]}
        payloads = {'sync': bundle(sync_state, sync_receipt), 'observe': bundle(observe_state, observe_receipt)}
        selected, fork_ids = _resolve_dominant_runtime_fork(
            data, current_run='999', expected_head_branch='main', download=payloads.__getitem__,
            max_archive_bytes=100000, max_member_bytes=50000,
        )
        self.assertEqual(selected['artifacts'][0]['id'], 2)
        self.assertEqual(fork_ids, [2, 1])

    def test_divergent_observe_cursor_still_fails_closed(self):
        observe_state, observe_receipt, sync_state, sync_receipt = self.fork(conflicting_observe=True)
        data = {'artifacts': [candidate(2, '2026-09-28T10:02:00Z', 'sync'), candidate(1, '2026-09-28T10:01:00Z', 'observe')]}
        payloads = {'sync': bundle(sync_state, sync_receipt), 'observe': bundle(observe_state, observe_receipt)}
        with self.assertRaisesRegex(InvalidStateArtifact, 'no unique dominant sync state'):
            _resolve_dominant_runtime_fork(
                data, current_run='999', expected_head_branch='main', download=payloads.__getitem__,
                max_archive_bytes=100000, max_member_bytes=50000,
            )

    def test_exact_current_main_observe_supersedes_ancestor_observe_fork(self):
        base = bootstrap_state(now='2026-09-28T08:00:00Z')
        parent_receipt = make_receipt(base, mode='sync', finished_at='2026-09-28T09:00:00Z', observations=[])
        parent = advance_cycle(base, parent_receipt)
        stale_rows = [observation(parent, 'REPO-008', '2026-09-28T10:00:00Z')]
        exact_rows = [observation(parent, 'REPO-008', '2026-09-28T10:01:00Z')]
        stale_receipt = make_receipt(parent, mode='observe', finished_at='2026-09-28T10:00:00Z', observations=stale_rows)
        exact_receipt = make_receipt(parent, mode='observe', finished_at='2026-09-28T10:01:00Z', observations=exact_rows)
        stale_state = advance_cycle(parent, stale_receipt)
        exact_state = advance_cycle(parent, exact_receipt)
        stale_sha = 'a' * 40
        exact_sha = 'b' * 40
        data = {'artifacts': [
            candidate(2, '2026-09-28T10:02:00Z', 'exact', head_sha=exact_sha),
            candidate(1, '2026-09-28T10:01:00Z', 'stale', head_sha=stale_sha),
        ]}
        payloads = {'exact': bundle(exact_state, exact_receipt), 'stale': bundle(stale_state, stale_receipt)}
        selected, fork_ids = _resolve_exact_main_observation_fork(
            data,
            current_run='999',
            expected_head_branch='main',
            current_sha=exact_sha,
            download=payloads.__getitem__,
            compare=lambda base_sha, head_sha: {'merge_base_commit': {'sha': base_sha}},
            max_archive_bytes=100000,
            max_member_bytes=50000,
        )
        self.assertEqual(selected['artifacts'][0]['id'], 2)
        self.assertEqual(fork_ids, [2, 1])

    def test_exact_main_observe_cannot_supersede_unrelated_source(self):
        base = bootstrap_state(now='2026-09-28T08:00:00Z')
        parent_receipt = make_receipt(base, mode='sync', finished_at='2026-09-28T09:00:00Z', observations=[])
        parent = advance_cycle(base, parent_receipt)
        rows1 = [observation(parent, 'REPO-008', '2026-09-28T10:00:00Z')]
        rows2 = [observation(parent, 'REPO-008', '2026-09-28T10:01:00Z')]
        receipt1 = make_receipt(parent, mode='observe', finished_at='2026-09-28T10:00:00Z', observations=rows1)
        receipt2 = make_receipt(parent, mode='observe', finished_at='2026-09-28T10:01:00Z', observations=rows2)
        state1 = advance_cycle(parent, receipt1)
        state2 = advance_cycle(parent, receipt2)
        stale_sha = 'a' * 40
        exact_sha = 'b' * 40
        data = {'artifacts': [
            candidate(2, '2026-09-28T10:02:00Z', 'exact', head_sha=exact_sha),
            candidate(1, '2026-09-28T10:01:00Z', 'stale', head_sha=stale_sha),
        ]}
        payloads = {'exact': bundle(state2, receipt2), 'stale': bundle(state1, receipt1)}
        with self.assertRaisesRegex(InvalidStateArtifact, 'not ancestor'):
            _resolve_exact_main_observation_fork(
                data,
                current_run='999',
                expected_head_branch='main',
                current_sha=exact_sha,
                download=payloads.__getitem__,
                compare=lambda _base_sha, _head_sha: {'merge_base_commit': {'sha': 'c' * 40}},
                max_archive_bytes=100000,
                max_member_bytes=50000,
            )


if __name__ == '__main__':
    unittest.main()
