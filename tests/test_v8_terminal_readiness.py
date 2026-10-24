"""Adversarial review-only tests for a future source-bound six-hour terminal audit."""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import unittest
from unittest.mock import patch
import zipfile

from verification import v8_terminal_readiness as audit

SOURCE = audit.FINAL_SOURCE
FIRST = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


def snap(i):
    return f"{i:040x}"


class MockOriginalProvider:
    def __init__(self):
        self.calls = []

    def get(self, suffix):
        self.calls.append(suffix)
        if suffix == "branches/main":
            return {"commit": {"sha": SOURCE}, "protected": True}
        if suffix.startswith("git/commits/"):
            child = suffix.rsplit("/", 1)[-1]
            parent = snap(int(child, 16) - 1)
            return {"sha": child, "parents": [{"sha": parent}]}
        raise AssertionError("unexpected API path " + suffix)


def model_row(i):
    return {
        "id": i + 1, "name": "brain-cycle-v2",
        "head_sha": SOURCE, "head_branch": "main", "created_at":
        (FIRST + timedelta(minutes=30*i)).isoformat().replace("+00:00", "Z"),
    }


def validated_run(api, row):
    i = row["id"] - 1
    return {
        "run_id": row["id"], "event": "workflow_dispatch",
        "origin": "CLOUDFLARE_SIGNED",
        "completed": FIRST + timedelta(minutes=30*i),
    }


def source_receipt(api, rid):
    i = rid - 1
    return {
        "delivery": {"state_parent": snap(i), "state_commit": snap(i+1)},
        "doctor": {"state_sequence": i+1, "canonical_hash": "a"*64},
        "publication": {"raw_sha256": "b"*64},
        "signed_cloudflare_origin": {
            "status": "CLOUDFLARE_SIGNED_ORIGIN_VERIFIED",
            "signed_origin": True, "soak_pass": False, "source_sha": SOURCE,
            "slot": i, "scheduled_at": "2026-10-17T09:00:00Z",
        }
    }


class SourceBoundWindow(unittest.TestCase):
    def evaluate(self, rows):
        provider = MockOriginalProvider()
        with (patch.object(audit, "original_census", return_value=rows),
              patch.object(audit, "checked_original_run", side_effect=validated_run),
              patch.object(audit, "checked_zip", side_effect=source_receipt)):
            return audit.evaluate(provider)

    def test_first_real_automatic_core_starts_the_window_not_task_wakeup(self):
        rows = [model_row(i) for i in range(13)]
        result = self.evaluate(rows)
        self.assertEqual(result["anchor_run"], 1)
        self.assertEqual(result["anchor_completion_utc"], FIRST.isoformat())
        self.assertEqual(result["completion_span_seconds"], 21_600)
        self.assertEqual(result["maximum_gap_seconds"], 1800)
        self.assertEqual(result["status"],
                         "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED")
        self.assertFalse(result["acceptance_pass"])
        self.assertEqual(result["verified_original_cores"], 13)

    def test_until_terminal_completed_no_acceptance_even_at_future_wall_clock(self):
        result = self.evaluate([model_row(i) for i in range(12)])
        self.assertEqual(result["status"], "WINDOW_RUNNING_NOT_ACCEPTED")
        self.assertEqual(result["seconds_remaining_minimum"], 1800)
        self.assertFalse(result["acceptance_pass"])

    def test_missed_cycle_exceeding_ninety_minutes_fails(self):
        rows = [model_row(i) for i in (0,1,2,6,7,8,9,10,11,12)]
        ranks = {row["id"]: i for i,row in enumerate(rows)}
        def continuous_state(provider, rid):
            proof = source_receipt(provider, rid)
            rank = ranks[rid]
            proof["delivery"]["state_parent"] = snap(rank)
            proof["delivery"]["state_commit"] = snap(rank + 1)
            proof["doctor"]["state_sequence"] = rank + 1
            return proof
        with (patch.object(audit, "original_census", return_value=rows),
              patch.object(audit, "checked_original_run", side_effect=validated_run),
              patch.object(audit, "checked_zip", side_effect=continuous_state)):
            with self.assertRaisesRegex(audit.Hold, "ORIGINAL_QUALIFYING_GAP_EXCEEDED"):
                audit.evaluate(MockOriginalProvider())

    def test_no_actual_automatic_run_never_starts(self):
        r = self.evaluate([])
        self.assertEqual(r["status"], "WAITING_FIRST_ORIGINAL_AUTOMATIC_COMPLETION")
        self.assertFalse(r["acceptance_pass"])

    def test_unchanged_source_is_required(self):
        with patch.object(audit, "original_census", return_value=[]):
            class Changed:
                def get(self, path):
                    return {"commit": {"sha": "0"*40}, "protected": True}
            with self.assertRaisesRegex(audit.Hold, "CURRENT_PROTECTED_MAIN_SOURCE_MOVED"):
                audit.evaluate(Changed())

    def test_continuous_state_publication_chain_not_optional(self):
        rows = [model_row(i) for i in range(13)]
        def corrupted(api, rid):
            proof = source_receipt(api, rid)
            if rid == 7:
                proof["delivery"]["state_parent"] = "f"*40
            return proof
        provider = MockOriginalProvider()
        with (patch.object(audit, "original_census", return_value=rows),
              patch.object(audit, "checked_original_run", side_effect=validated_run),
              patch.object(audit, "checked_zip", side_effect=corrupted)):
            with self.assertRaisesRegex(audit.Hold, "ORIGINAL_STATE_LINEAGE_GAP"):
                audit.evaluate(provider)

    def test_failed_original_automatic_core_not_credited(self):
        def bad_run(api, row):
            raise audit.Hold("ORIGINAL_AUTOMATIC_RUN_NOT_SUCCESS_FIRST_ATTEMPT")
        with (patch.object(audit, "original_census", return_value=[model_row(0)]),
              patch.object(audit, "checked_original_run", side_effect=bad_run)):
            with self.assertRaisesRegex(audit.Hold, "FIRST_ATTEMPT"):
                audit.evaluate(MockOriginalProvider())

    def test_raw_sqlite_replay_requires_completed_real_window(self):
        with self.assertRaisesRegex(audit.Hold, "SIX_HOUR_PROVIDER_CENSUS_NOT_VERIFIED"):
            audit.replay_terminal(source_dir=".",state_dir=".",evidence={
                "status":"WINDOW_RUNNING_NOT_ACCEPTED"})


class ProviderIntegrity(unittest.TestCase):
    def test_gh_read_only_allowlist_rejects_mutations_and_other_repos(self):
        good = (
            "branches/main", "actions/runs?per_page=100&page=1",
            "actions/runs/123", "actions/runs/123/jobs?per_page=100",
            "actions/runs/123/artifacts?per_page=100",
            "git/commits/" + "a"*40,
        )
        for value in good:
            self.assertTrue(audit.OriginalGitHub.allowed(value), value)
        for value in (
            "git/refs", "pulls", "branches/development",
            "actions/workflows/foundation-ci.yml/dispatches",
            "actions/runs?per_page=100&page=0",
            "actions/runs/1/attempts/2", "../repos/another",
            "git/commits/not-sha",
        ):
            self.assertFalse(audit.OriginalGitHub.allowed(value), value)

    def test_strict_json_rejects_duplicates_and_unsafe_timestamps(self):
        with self.assertRaisesRegex(audit.Hold, "DUPLICATE_ORIGINAL_JSON_KEY"):
            audit.strict_json(b'{"status":"PASS","status":"FAIL"}')
        for value in ("2026-10-17", "today", "2026-10-17T05:00:00+00:00"):
            with self.subTest(value=value), self.assertRaises(audit.Hold):
                audit.dt(value)

    def test_original_artifact_sha_crc_and_payload_checks(self):
        rid = 15
        delivery = {
            "run_id": str(rid), "run_attempt": "1", "source_sha": SOURCE,
            "publication_verified": True, "soak_completed": False,
        }
        doctor = {
            "source_sha": SOURCE, "status": "PASS", "pending_events": 0,
            "verified_canonical_state": True, "state_sequence": 12,
            "canonical_hash": "e"*64,
        }
        publication = {"raw_sha256": "f"*64}
        origin = {
            "status": "CLOUDFLARE_SIGNED_ORIGIN_VERIFIED",
            "signed_origin": True, "source_sha": SOURCE,
            "soak_pass": False, "slot": 2987030,
            "scheduled_at": "2026-10-17T09:00:00Z",
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
            for name,item in (
                ("delivery.json",delivery),
                ("doctor/report.json",doctor),
                ("state-publication.json",publication),
                ("cloudflare-origin.json",origin),
            ):
                z.writestr(name,json.dumps(item))
        raw = buf.getvalue()
        digest = hashlib.sha256(raw).hexdigest()

        class Fixture:
            def __init__(self,wrong_digest=False):
                self.wrong_digest = wrong_digest
            def get(self,path):
                self_path=f"actions/runs/{rid}/artifacts?per_page=100"
                assert path==self_path
                return {"total_count":1,"artifacts":[{
                    "id":87, "name":f"brain-v2-cycle-{SOURCE}-{rid}-1",
                    "expired":False,"digest":"sha256:"+(
                        "0"*64 if self.wrong_digest else digest),
                    "size_in_bytes":len(raw)
                }]}
            def artifact_zip(self,artifact_id):
                assert artifact_id == 87
                return raw
        evidence=audit.checked_zip(Fixture(),rid)
        self.assertEqual(evidence["signed_cloudflare_origin"]["signed_origin"],True)
        self.assertEqual(evidence["zip_digest"],"sha256:"+digest)
        with self.assertRaisesRegex(audit.Hold, "ORIGINAL_ZIP_BYTE_OR_PROVIDER_HASH_MISMATCH"):
            audit.checked_zip(Fixture(wrong_digest=True),rid)


if __name__=="__main__":
    unittest.main()
