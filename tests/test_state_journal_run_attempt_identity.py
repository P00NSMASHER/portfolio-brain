import copy
import unittest

from state_journal.contracts import event_identity, validate_source_evidence
from state_journal.events import make_event
from state_journal.transport import EVENT_PREFIX, validate_provider_event
from test_state_journal import SHA
from test_state_journal_transport import UPLOADS, fixture


class StateJournalRunAttemptIdentityTests(unittest.TestCase):
    def test_attempt_one_identity_is_backwards_compatible(self):
        legacy = fixture()[-1]
        self.assertEqual(
            legacy["event_id"],
            event_identity(legacy["run_id"], legacy["event_type"], legacy["source_sha"], 1),
        )
        self.assertNotIn("run_attempt", legacy)

    def test_new_retry_attempt_gets_distinct_deterministic_identity(self):
        legacy = fixture()[-1]
        retry = make_event(
            legacy["producer"],
            legacy["run_id"],
            legacy["source_sha"],
            copy.deepcopy(legacy["changes"]),
            run_attempt=2,
        )
        self.assertEqual(retry["run_attempt"], 2)
        self.assertNotEqual(retry["event_id"], legacy["event_id"])
        self.assertNotEqual(retry["event_hash"], legacy["event_hash"])
        self.assertEqual(
            retry["event_id"],
            event_identity(retry["run_id"], retry["event_type"], retry["source_sha"], 2),
        )

    def test_legacy_retry_artifact_is_upgraded_without_discarding_raw_hash(self):
        meta, run, jobs, raw, legacy = fixture()
        run["run_attempt"] = 2
        jobs["jobs"][0]["run_attempt"] = 2
        meta["name"] = f"{EVENT_PREFIX}{legacy['run_id']}-{legacy['producer']}-{legacy['source_sha']}-2"

        upgraded, evidence = validate_provider_event(meta, run, jobs, raw, UPLOADS)

        self.assertEqual(upgraded["run_attempt"], 2)
        self.assertNotEqual(upgraded["event_id"], legacy["event_id"])
        self.assertEqual(evidence["source_run_attempt"], 2)
        self.assertEqual(evidence["source_event_hash"], legacy["event_hash"])
        self.assertEqual(evidence["event_hash"], upgraded["event_hash"])
        validate_source_evidence(evidence, upgraded)

    def test_explicit_event_attempt_must_match_provider_attempt(self):
        meta, run, jobs, raw, legacy = fixture()
        retry = make_event(
            legacy["producer"], legacy["run_id"], legacy["source_sha"],
            copy.deepcopy(legacy["changes"]), run_attempt=2,
        )
        import io, json, hashlib, zipfile
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("event.json", json.dumps(retry))
        raw = stream.getvalue()
        meta["digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        meta["name"] = f"{EVENT_PREFIX}{legacy['run_id']}-{legacy['producer']}-{legacy['source_sha']}-1"
        with self.assertRaisesRegex(Exception, "attempt"):
            validate_provider_event(meta, run, jobs, raw, UPLOADS)


if __name__ == "__main__":
    unittest.main()
