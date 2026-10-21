"""Hostile, network-free tests: a matching Cloudflare JSON is NOT authenticated."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from verification import cloudflare_provider_reconcile as cf

BASE = datetime(2026, 10, 21, 7, 20, 50, tzinfo=timezone.utc)
STAMP = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")


def original():
    # One of the 13 genuine cores was native-scheduled and has no CF origin.
    slots = [i for i in range(13) if i != 6]
    return {
        "production_source": cf.SOURCE,
        "status": "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
        "completion_span_seconds": 21611,
        "verified_original_cores": 13,
        "acceptance_pass": False,
        "release_or_merge_authorized": False,
        "external_cloudflare_provider_accepted": False,
        "terminal_replay": {
            "status": "ORIGINAL_TERMINAL_RAW_SQLITE_REPLAY_VERIFIED",
            "pending_events": 0,
        },
        "signed_cloudflare_origins": [
            {"run_id": 9000+i, "slot": 400000+i,
             "scheduled_at": STAMP(BASE+timedelta(minutes=30*i)).replace("Z", ".000Z"),
             "artifact_sha256": "sha256:"+"a"*64}
            for i in slots
        ],
    }


def provider(proof=None):
    proof = original() if proof is None else proof
    return {"data": {"viewer": {"accounts": [{
        "workersInvocationsAdaptive": [
            {"dimensions": {"scriptName": cf.WORKER_SCRIPT, "status": "success",
                            "datetime": row["scheduled_at"].replace(".000Z", "Z")},
             "sum": {"requests": 1, "errors": 0}}
            for row in proof["signed_cloudflare_origins"]
        ],
    }]}}}


_MISSING = object()


class OriginalCloudflareCompareTests(unittest.TestCase):
    def hold(self, proof=None, response=_MISSING, reason=None):
        proof = original() if proof is None else proof
        response = provider(proof) if response is _MISSING else response
        result = cf.compare_cloudflare_rows(proof, response)
        self.assertEqual(result.status, "HOLD")
        self.assertFalse(result.authenticated_cloudflare_provider)
        self.assertFalse(result.source_acceptance_issued)
        self.assertFalse(result.merge_authorized)
        self.assertEqual(result.github_writes, 0)
        if reason is not None:
            self.assertEqual(result.reason, reason)
        return result

    def test_complete_matching_data_is_still_not_original_provider_authentication(self):
        proof = original()
        result = cf.compare_cloudflare_rows(proof, provider(proof))
        self.assertEqual(result.status,
                         "CONTENT_MATCHED_PROVIDER_AUTHENTICATION_STILL_REQUIRED")
        self.assertEqual(result.expected_signed_dispatches, 12)
        self.assertEqual(result.matched_original_invocations, 12)
        self.assertFalse(result.authenticated_cloudflare_provider)
        self.assertFalse(result.source_acceptance_issued)
        self.assertFalse(result.merge_authorized)
        self.assertEqual(result.github_writes, 0)

    def test_original_zero_millisecond_dispatch_matches_whole_second_cloudflare(self):
        proof = original()
        self.assertTrue(all(row["scheduled_at"].endswith(".000Z")
                            for row in proof["signed_cloudflare_origins"]))
        result = cf.compare_cloudflare_rows(proof, provider(proof))
        self.assertEqual(result.status,
                         "CONTENT_MATCHED_PROVIDER_AUTHENTICATION_STILL_REQUIRED")
        self.assertFalse(result.authenticated_cloudflare_provider)

    def test_provider_zero_millisecond_datetime_is_accepted(self):
        proof = original()
        response = provider(proof)
        rows = response["data"]["viewer"]["accounts"][0]["workersInvocationsAdaptive"]
        rows[0]["dimensions"]["datetime"] = rows[0]["dimensions"]["datetime"].replace(
            "Z", ".000Z")
        result = cf.compare_cloudflare_rows(proof, response)
        self.assertEqual(result.matched_original_invocations, 12)
        self.assertFalse(result.source_acceptance_issued)

    def test_nonzero_subsecond_dispatch_or_provider_timestamp_holds(self):
        proof = original()
        proof["signed_cloudflare_origins"][0]["scheduled_at"] = "2026-10-21T07:20:50.001Z"
        self.hold(proof=proof, reason="UTC_TIMESTAMP_MALFORMED")
        for wrong in ("2026-10-21T07:20:50.000001Z",
                      "2026-10-21T07:20:50.123Z",
                      "2026-10-21T07:20:50.0000000Z"):
            with self.subTest(wrong=wrong):
                response = provider()
                response["data"]["viewer"]["accounts"][0][
                    "workersInvocationsAdaptive"][0]["dimensions"]["datetime"] = wrong
                self.hold(response=response, reason="UTC_TIMESTAMP_MALFORMED")

    def test_schedules_are_not_misclassified_as_cloudflare_calls(self):
        result = cf.compare_cloudflare_rows(original(), provider())
        self.assertEqual(result.expected_signed_dispatches, 12)
        self.assertNotEqual(result.expected_signed_dispatches, 13)

    def test_exact_script_only_and_bounded_readonly_query(self):
        query = cf.query_envelope(original(), account_tag="f"*32)
        self.assertEqual(query["variables"]["scriptName"], cf.WORKER_SCRIPT)
        self.assertEqual(query["variables"]["datetimeStart"], "2026-10-21T07:18:50Z")
        self.assertEqual(query["variables"]["datetimeEnd"], "2026-10-21T13:22:50Z")
        self.assertIn("workersInvocationsAdaptive", query["query"])
        self.assertIn("datetime_geq", query["query"])
        self.assertNotIn("Authorization", query["query"])
        self.assertNotIn("mutation", query["query"])
        self.assertNotIn("TOKEN", repr(query))
        for wrong in (None, True, "a", "A"*32, 1):
            with self.subTest(account=repr(wrong)):
                with self.assertRaises(ValueError):
                    cf.query_envelope(original(), account_tag=wrong)

    def test_missing_exact_original_invocation_holds(self):
        response = provider()
        response["data"]["viewer"]["accounts"][0]["workersInvocationsAdaptive"].pop()
        self.hold(response=response, reason="CLOUDFLARE_SIGNED_DISPATCH_MISSING")

    def test_duplicate_exact_timestamp_holds(self):
        response = provider()
        rows = response["data"]["viewer"]["accounts"][0]["workersInvocationsAdaptive"]
        rows.append(deepcopy(rows[0]))
        self.hold(response=response, reason="CLOUDFLARE_DUPLICATE_INVOCATION")

    def test_moved_datetime_or_extra_invocation_holds(self):
        response = provider()
        response["data"]["viewer"]["accounts"][0]["workersInvocationsAdaptive"][0][
            "dimensions"]["datetime"] = "2026-10-21T07:21:50Z"
        self.hold(response=response, reason="CLOUDFLARE_EXTRA_OR_DIFFERENT_INVOCATION")

    def test_wrong_script_status_request_count_and_errors_hold(self):
        for component, name, wrong in [
            ("dimensions", "scriptName", "other-worker"),
            ("dimensions", "status", "error"),
            ("sum", "requests", 0),
            ("sum", "requests", 2),
            ("sum", "requests", True),
            ("sum", "errors", 1),
            ("sum", "errors", False),
        ]:
            with self.subTest(field=name, value=wrong):
                response = provider()
                response["data"]["viewer"]["accounts"][0][
                    "workersInvocationsAdaptive"][0][component][name] = wrong
                self.hold(response=response,
                          reason="CLOUDFLARE_SCRIPT_COUNT_OR_ERROR_INVALID")

    def test_graphql_errors_and_ambiguous_accounts_hold(self):
        for response in (
            {"errors": [{"message": "SECRET_PROVIDER_ERROR"}]},
            {"data": {"viewer": {"accounts": []}}},
            {"data": {"viewer": {"accounts": [{}, {}]}}},
            {"data": {"viewer": {"accounts": None}}},
            {"data": {}},
            {},
        ):
            with self.subTest(shape=repr(response)[:60]):
                result = self.hold(response=response)
                self.assertNotIn("SECRET_PROVIDER_ERROR", result.reason)

    def test_forged_acceptance_or_omitted_terminal_replay_holds(self):
        for change in (
            lambda p: p.update(acceptance_pass=True),
            lambda p: p.update(release_or_merge_authorized=True),
            lambda p: p.update(external_cloudflare_provider_accepted=True),
            lambda p: p.update(status="WINDOW_RUNNING_NOT_ACCEPTED"),
            lambda p: p.update(completion_span_seconds=21600-1),
            lambda p: p.update(production_source="0"*40),
            lambda p: p.update(terminal_replay={}),
            lambda p: p["terminal_replay"].update(pending_events=1),
        ):
            proof = original()
            change(proof)
            self.hold(proof=proof,
                      reason="ORIGINAL_TERMINAL_SOURCE_PROOF_NOT_READY")

    def test_missing_duplicate_malformed_signed_origins_hold(self):
        cases = []
        p = original(); p["signed_cloudflare_origins"] = []; cases.append(p)
        p = original(); p["signed_cloudflare_origins"][1]["run_id"] = 9000; cases.append(p)
        p = original(); p["signed_cloudflare_origins"][1]["slot"] = 400000; cases.append(p)
        p = original(); p["signed_cloudflare_origins"][1]["scheduled_at"] = (
            p["signed_cloudflare_origins"][0]["scheduled_at"]); cases.append(p)
        p = original(); p["signed_cloudflare_origins"][0]["artifact_sha256"] = "sha256:invalid"; cases.append(p)
        p = original(); p["signed_cloudflare_origins"].reverse(); cases.append(p)
        p = original(); p["signed_cloudflare_origins"][0]["run_id"] = True; cases.append(p)
        for proof in cases:
            with self.subTest(first=repr(proof["signed_cloudflare_origins"][:1])[:100]):
                self.hold(proof=proof)

    def test_invalid_untrusted_response_types_hold_without_exposing_exception(self):
        for value in ([], "secret", True, None, {"data": []}, {"errors": "bad"}):
            with self.subTest(value=repr(value)):
                self.hold(response=value)

    def test_overlong_and_non_utc_timestamp_holds(self):
        p = original()
        p["signed_cloudflare_origins"][-1]["scheduled_at"] = "2026-10-22T14:20:50Z"
        self.hold(proof=p, reason="ORIGINAL_SIGNED_WINDOW_EXCEEDS_BOUND")
        p = original()
        p["signed_cloudflare_origins"][0]["scheduled_at"] = "2026-10-21T07:20:50-04:00"
        self.hold(proof=p, reason="UTC_TIMESTAMP_MALFORMED")


if __name__ == "__main__":
    unittest.main()
