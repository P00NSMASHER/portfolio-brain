"""Read-only durable-state snapshot race must retry exact Git objects, not fake success."""
import unittest
from tests.test_v5_deployed_state_compatibility import read_consistent_state_revision

A = "a"*40
B = "b"*40
C = "c"*40
RAW_A = b"SQLite format 3\x00snapshot-a"
RAW_B = b"SQLite format 3\x00snapshot-b"


class OriginalGitState:
    def __init__(self, tips, fetched, *, reader_error=False):
        self.tips = iter(tips)
        self.fetched = iter(fetched)
        self.calls = []
        self.reads = []
        self.reader_error = reader_error

    def git(self, *args):
        self.calls.append(args)
        if args[:3] == ("ls-remote", "origin", "refs/heads/brain-state-v2"):
            return next(self.tips)
        if args[:3] == ("fetch", "--quiet", "--no-tags"):
            return ""
        if args == ("rev-parse", "FETCH_HEAD"):
            return next(self.fetched)
        raise AssertionError("Unexpected original Git call " + repr(args))

    def verify(self, sha):
        self.reads.append(sha)
        if self.reader_error:
            raise AssertionError("Original manifest/blob verification failed")
        return (RAW_A if sha == A else RAW_B, sha, "original_archive", sha)


class StateReadbackTests(unittest.TestCase):
    def evaluate(self, proof, max_attempts=2):
        return read_consistent_state_revision(
            git_reader=proof.git, state_reader=proof.verify,
            max_attempts=max_attempts)

    def test_no_race_needs_only_one_hash_verified_snapshot(self):
        proof = OriginalGitState([A,A], [A])
        state, raw, blob, fmt, manifest, tries = self.evaluate(proof)
        self.assertEqual((state,raw,blob,fmt,manifest,tries),
                         (A,RAW_A,A,"original_archive",A,1))
        self.assertEqual(proof.reads,[A])
        self.assertFalse(any(args[0] in ("push", "commit", "update-ref")
                             for args in proof.calls))

    def test_one_actual_branch_move_rechecks_new_original_bytes(self):
        proof = OriginalGitState([A,B,B,B], [A,B])
        state, raw, blob, fmt, manifest, tries = self.evaluate(proof)
        self.assertEqual(state,B)
        self.assertEqual(raw,RAW_B)
        self.assertEqual(tries,2)
        self.assertEqual(proof.reads,[A,B])
        self.assertEqual(len([x for x in proof.calls if x[0]=="fetch"]),2)

    def test_move_before_first_fetch_is_also_not_a_false_pass(self):
        proof = OriginalGitState([A,B,B], [B,B])
        state, raw, blob, _, _, tries = self.evaluate(proof)
        self.assertEqual(state,B)
        self.assertEqual(raw,RAW_B)
        self.assertEqual(tries,2)
        self.assertEqual(proof.reads,[B])

    def test_second_unresolved_state_move_fails_closed(self):
        proof = OriginalGitState([A,B,B,C], [A,B])
        with self.assertRaisesRegex(AssertionError, "STATE_REF_CHANGED_BEYOND_BOUNDED_READBACK"):
            self.evaluate(proof)
        self.assertEqual(proof.reads,[A,B])

    def test_original_git_blob_corruption_never_retries_to_green(self):
        proof = OriginalGitState([A,A], [A], reader_error=True)
        with self.assertRaisesRegex(AssertionError, "manifest/blob"):
            self.evaluate(proof)
        self.assertEqual(proof.reads,[A])
        self.assertEqual(len([x for x in proof.calls if x[0]=="fetch"]),1)

    def test_bad_provider_sha_and_unbounded_retries_denied(self):
        proof = OriginalGitState(["not-a-sha"],[])
        with self.assertRaisesRegex(AssertionError,"STATE_REF_IDENTITY_INVALID"):
            self.evaluate(proof)
        proof = OriginalGitState([A,A],[A])
        with self.assertRaisesRegex(ValueError,"BOUNDED"):
            self.evaluate(proof,max_attempts=0)
        with self.assertRaisesRegex(ValueError,"BOUNDED"):
            self.evaluate(proof,max_attempts=200)


if __name__=="__main__":
    unittest.main()
