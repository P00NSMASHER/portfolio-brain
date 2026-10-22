"""Regression contract for the bounded, non-deploying Brain v9 batch."""
import sqlite3
import tempfile
from pathlib import Path
import unittest

from brain.v9.batch_queue import BatchQueue, BatchFault
from brain.v9.batch_release import review_release
from brain.v9.batch_observation import ObservationBudget

T0 = "2026-10-22T03:00:00Z"
T1 = "2026-10-22T03:01:00Z"
T2 = "2026-10-22T03:25:00Z"
SHA = "a" * 40
NEXT = "c" * 40
EVIDENCE = "e" * 64
REPO = "P00NSMASHER/permitplate-nyc"


def issue(**kwargs):
    doc = dict(project_id="permitplate", repository=REPO,
               source_sha=SHA, fingerprint="b" * 64,
               owner="retally-product", path="src/reconcile.py",
               priority=1)
    doc.update(kwargs)
    return doc


def check(name, app_id, *, sha=NEXT, result="success"):
    return dict(name=name, app_id=app_id, head_sha=sha,
                status="completed", conclusion=result)


def release(**kwargs):
    result = dict(schema_version=1, base_sha=SHA, candidate_sha=NEXT,
                  observed_main_sha=SHA, observed_candidate_sha=NEXT,
                  all_changes_integrated=True, batch_closed=True,
                  unresolved_blockers=0,
                  check_runs=[check("validate", 15368),
                              check("portfolio-phase1-gate", 5121826)],
                  independent_original_state_replay=False)
    result.update(kwargs)
    return result


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "work.sqlite"
        self.q = BatchQueue(self.path)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def test_duplicate_observation_preserves_ownership_and_stage(self):
        ident = self.q.observe(issue(), now=T0)
        token = self.q.claim(ident, "retally-product", now=T0, ttl_seconds=1200)
        self.q.advance(ident, token, "DIAGNOSED", evidence_sha=EVIDENCE, now=T1)
        self.assertEqual(self.q.observe(issue(), now=T1), ident)
        item = self.q.snapshot()["work"][ident]
        self.assertEqual(item["stage"], "DIAGNOSED")
        self.assertIsNotNone(item["claim"])
        self.assertEqual(self.q.metrics(now=T1)["work_items"], 1)

    def test_separate_connections_cannot_claim_same_owner_or_repository(self):
        first = self.q.observe(issue(), now=T0)
        other = self.q.observe(issue(project_id="capturebrief",
                     repository="P00NSMASHER/capturebrief", path="src/brief.py",
                     fingerprint="f" * 64), now=T0)
        token = self.q.claim(first, "retally-product", now=T0)
        another = BatchQueue(self.path)
        try:
            with self.assertRaisesRegex(BatchFault, "CLAIM_CONFLICT"):
                another.claim(other, "retally-product", now=T1)
            self.assertTrue(token)
        finally:
            another.close()

    def test_expired_token_fenced_across_restart(self):
        ident = self.q.observe(issue(), now=T0)
        token = self.q.claim(ident, "retally-product", now=T0, ttl_seconds=60)
        replacement = self.q.claim(ident, "retally-product", now=T2, ttl_seconds=60)
        self.assertNotEqual(token, replacement)
        with self.assertRaisesRegex(BatchFault, "CLAIM_STALE"):
            self.q.advance(ident, token, "DIAGNOSED", evidence_sha=EVIDENCE, now=T2)
        self.q.advance(ident, replacement, "DIAGNOSED", evidence_sha=EVIDENCE, now=T2)

    def test_unknown_effect_survives_restart_and_blocks_all_claims(self):
        ident = self.q.observe(issue(), now=T0)
        token = self.q.claim(ident, "retally-product", now=T0, ttl_seconds=1200)
        for stage in ("DIAGNOSED", "PATCHED", "TESTED"):
            self.q.advance(ident, token, stage, evidence_sha=EVIDENCE, now=T1)
        operation_id = self.q.begin_effect(ident, token, action="CREATE_DRAFT_PR", now=T1)
        self.q.mark_unknown(ident, operation_id, now=T2)
        self.q.close()
        self.q = BatchQueue(self.path)
        with self.assertRaisesRegex(BatchFault, "RECONCILIATION_REQUIRED"):
            self.q.claim(ident, "retally-product", now=T2)
        self.assertEqual(self.q.metrics(now=T2)["uncertain_effects"], 1)

    def test_unknown_effect_cannot_be_declared_done_from_self_attestation(self):
        ident = self.q.observe(issue(), now=T0)
        token = self.q.claim(ident, "retally-product", now=T0)
        for stage in ("DIAGNOSED", "PATCHED", "TESTED"):
            self.q.advance(ident, token, stage, evidence_sha=EVIDENCE, now=T1)
        op = self.q.begin_effect(ident, token, action="CREATE_DRAFT_PR", now=T1)
        self.q.mark_unknown(ident, op, now=T1)
        with self.assertRaisesRegex(BatchFault, "PROVIDER_READBACK_REQUIRED"):
            self.q.reconcile(ident, op, {"confirmed": True}, now=T2)
        self.assertEqual(self.q.metrics(now=T2)["actual_live_verified"], 0)

    def test_bad_transition_does_not_relabel_proof(self):
        ident = self.q.observe(issue(), now=T0)
        token = self.q.claim(ident, "retally-product", now=T0)
        with self.assertRaisesRegex(BatchFault, "TRANSITION_DENIED"):
            self.q.advance(ident, token, "LIVE_VERIFIED", evidence_sha=EVIDENCE, now=T1)
        self.assertEqual(self.q.snapshot()["work"][ident]["stage"], "OBSERVED")

    def test_sqlite_mutation_detected_by_replay(self):
        ident = self.q.observe(issue(), now=T0)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE batch_event SET body='{}' WHERE sequence=1")
        with self.assertRaisesRegex(BatchFault, "JOURNAL_TAMPERED"):
            self.q.snapshot()

    def test_backup_restore_matches_exact_checkpoint(self):
        ident = self.q.observe(issue(), now=T0)
        self.q.claim(ident, "retally-product", now=T0)
        receipt = self.q.restore_drill()
        self.assertEqual(receipt["status"], "ISOLATED_RESTORE_REPLAY_PASSED")
        self.assertFalse(receipt["production_accepted"])

    def test_rejects_wrong_owner_source_and_traversal(self):
        with self.assertRaisesRegex(BatchFault, "WORK_PATH_INVALID"):
            self.q.observe(issue(path="../.github/workflows/evil.yml"), now=T0)
        ident = self.q.observe(issue(), now=T0)
        with self.assertRaisesRegex(BatchFault, "CLAIM_OWNER_INVALID"):
            self.q.claim(ident, "school-data", now=T0)
        with self.assertRaisesRegex(BatchFault, "WORK_IDENTITY_INVALID"):
            self.q.observe(issue(source_sha="oops"), now=T0)

    def test_stale_future_clock_does_not_bypass_ownership(self):
        ident = self.q.observe(issue(), now=T0)
        token = self.q.claim(ident, "retally-product", now=T0)
        with self.assertRaisesRegex(BatchFault, "TIME_REVERSED"):
            self.q.advance(ident, token, "DIAGNOSED", evidence_sha=EVIDENCE,
                           now="2026-10-21T03:00:00Z")


class ReleaseTests(unittest.TestCase):
    def test_all_green_is_readiness_not_execution(self):
        out = review_release(release())
        self.assertEqual(out["status"], "TECHNICALLY_READY_FOR_GOVERNED_RELEASE")
        self.assertFalse(out["provider_writes"])
        self.assertFalse(out["production_accepted"])
        self.assertFalse(out["six_hour_acceptance_passed"])

    def test_missing_or_wrong_issuer_is_hold(self):
        for row in (
                release(check_runs=[check("validate", 15368)]),
                release(check_runs=[check("validate", 15368),
                       check("portfolio-phase1-gate", 123)]),
                release(check_runs=[check("validate", 15368),
                       check("portfolio-phase1-gate", 5121826, result="pending")]),
        ):
            with self.subTest(row=row["check_runs"]):
                self.assertEqual(review_release(row)["status"], "HOLD_TECHNICAL_EVIDENCE")

    def test_stale_sha_closed_state_and_blockers_are_holds(self):
        for input in (
                release(observed_candidate_sha="f" * 40),
                release(observed_main_sha="f" * 40),
                release(batch_closed=False),
                release(unresolved_blockers=1),
                release(all_changes_integrated=False),
        ):
            self.assertNotEqual(
                review_release(input)["status"],
                "TECHNICALLY_READY_FOR_GOVERNED_RELEASE")

    def test_self_declared_independent_replay_cannot_certify_soak(self):
        out = review_release(release(independent_original_state_replay=True))
        self.assertFalse(out["six_hour_acceptance_passed"])
        self.assertFalse(out["production_accepted"])


class ObservationTests(unittest.TestCase):
    def test_changed_sources_and_ttl_only(self):
        cache = ObservationBudget(max_gets=3, ttl_seconds=300)
        self.assertTrue(cache.should_fetch("retally", fingerprint=EVIDENCE, now=T0))
        cache.record("retally", fingerprint=EVIDENCE, now=T0)
        self.assertFalse(cache.should_fetch("retally", fingerprint=EVIDENCE, now=T1))
        self.assertTrue(cache.should_fetch("retally", fingerprint="f" * 64, now=T1))
        self.assertTrue(cache.should_fetch("retally", fingerprint=EVIDENCE, now=T2))

    def test_limit_cannot_expand_and_stale_is_not_green(self):
        cache = ObservationBudget(max_gets=1, ttl_seconds=300)
        cache.record("abvm", fingerprint=EVIDENCE, now=T0)
        self.assertFalse(cache.should_fetch("retally", fingerprint=EVIDENCE, now=T1))
        self.assertEqual(cache.health("retally", now=T1), "UNKNOWN_UNOBSERVED")
        self.assertEqual(cache.health("abvm", now=T2), "STALE_NOT_VERIFIED")
        with self.assertRaises(ValueError):
            ObservationBudget(max_gets=25, ttl_seconds=300)


if __name__ == "__main__":
    unittest.main()
