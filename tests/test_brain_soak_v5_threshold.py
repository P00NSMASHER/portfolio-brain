"""V5 six-hour pre-acceptance gate; no real provider access or PASS claims.

All fixtures are simulated. Positive outcomes mean PRE_POSTVALIDATION only;
an independent raw artifact/provider/state auditor still must evaluate reality.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from soak_v3.audit import (
    EvidenceError, REQUIRED_STEPS, evaluate_v5_window, evaluate_window,
    V5_MIN_SPAN_SECONDS,
)

SHA = "a"*40
PARENT = "b"*40
BEGIN = datetime(2026, 10, 10, 1, 50, tzinfo=timezone.utc)


def stamp(when):
    return when.isoformat().replace("+00:00", "Z")


def fixtures(hours=None, *, automatic=True):
    if hours is None:
        hours = [n/2 for n in range(13)]
    records = []
    for i, hour in enumerate(hours):
        start = BEGIN + timedelta(hours=hour)
        item = {
            "run_id": 9000+i,
            "attempt": 1,
            "event": "workflow_dispatch" if automatic else "push",
            "source_sha": SHA,
            "started_at": stamp(start),
            "completed_at": stamp(start + timedelta(seconds=45)),
            "status": "completed",
            "conclusion": "success",
            "steps": {k: "success" for k in REQUIRED_STEPS},
            "artifact": {
                "status": "PASS", "state_sequence": 600+i*7,
                "canonical_hash": format(i+1, "064x"),
            },
            "state": {
                "status": "PASS",
                "parent": PARENT if i == 0 else format(i, "040x"),
                "commit": format(i+1, "040x"),
                "sequence": 600+i*7,
                "canonical_hash": format(i+1, "064x"),
            },
        }
        if automatic:
            item["external_clock"] = {
                "kind": "cloudflare_cron_v1",
                "source_sha": SHA,
                "provider_cron_verified": True,
                "signed_origin_verified": True,
                "core_receipt_verified": True,
                "state_verified": True,
            }
        records.append(item)
    return records


def first_incomplete(records):
    """Make the earliest synthetic provider core unfinished without fabricating completion."""
    records[0]["status"] = "in_progress"
    records[0]["conclusion"] = None
    records[0]["completed_at"] = None
    return records


def census(records, *, coverage=True):
    return {
        "coverage_complete": coverage,
        "provenance": "GITHUB_API_PROVIDER_METADATA",
        "soak_pass": False,
        "core_runs": [
            {
                "run_id": item["run_id"],
                "run_attempt": item["attempt"],
                "head_sha": item["source_sha"],
                "event": item["event"],
                "created_at": item["started_at"],
                "run_started_at": item["started_at"],
                "status": item["status"],
                "conclusion": item["conclusion"],
                "job": ({
                    "id": 200_000 + item["run_id"],
                    "run_id": item["run_id"],
                    "attempt_scope": item["attempt"],
                    "head_sha": item["source_sha"],
                    "name": "monitor",
                    "status": "completed",
                    "conclusion": item["conclusion"],
                    "started_at": item["started_at"],
                    "completed_at": item["completed_at"],
                } if item["status"] == "completed" else None),
            }
            for item in records
        ],
    }


def inspect(records, *, inventory=None, hours=8, now=6.1, main=SHA):
    return evaluate_v5_window(
        records, inventory=census(records) if inventory is None else inventory,
        source_sha=SHA, current_main=main, first_state_parent=PARENT,
        started_at=stamp(BEGIN),
        deadline_at=stamp(BEGIN+timedelta(hours=hours)),
        now=stamp(BEGIN+timedelta(hours=now)),
    )


class V5SixHourGate(unittest.TestCase):
    def test_six_hour_evidence_can_only_reach_independent_postvalidation(self):
        records=fixtures()
        result=inspect(records)
        self.assertEqual(result.status, "PRE_POSTVALIDATION")
        self.assertEqual(result.reason, "POST_SOAK_INDEPENDENT_CHECKS_REQUIRED")
        self.assertEqual(result.span_seconds, V5_MIN_SPAN_SECONDS)
        self.assertEqual(result.maximum_gap_observed, 1800)
        self.assertEqual(len(result.automatic_run_ids), 13)
        self.assertNotEqual(result.status, "PASS")

    def test_legacy_two_hour_v3_window_unchanged_and_insufficient_for_v5(self):
        early=fixtures([0,.5,1,1.5,2])
        common=dict(
            source_sha=SHA, current_main=SHA, first_state_parent=PARENT,
            started_at=stamp(BEGIN),
            deadline_at=stamp(BEGIN+timedelta(hours=8)),
            now=stamp(BEGIN+timedelta(hours=2,minutes=5)),
        )
        self.assertEqual(
            evaluate_window(early,**common).status, "PRE_POSTVALIDATION"
        )
        result=evaluate_v5_window(early,inventory=census(early),**common)
        self.assertEqual(result.status, "WAITING")
        self.assertEqual(result.reason, "SOAK_DURATION_INCOMPLETE")

    def test_unfinished_six_hour_window_never_silently_passes(self):
        early=fixtures([n/2 for n in range(8)])
        result=inspect(early,now=4)
        self.assertEqual(result.status,"WAITING")
        self.assertEqual(result.reason,"SOAK_DURATION_INCOMPLETE")

    def test_provider_census_missing_a_failed_core_is_rejected(self):
        records=fixtures()
        missing=deepcopy(records)
        del missing[5]
        with self.assertRaisesRegex(EvidenceError,"V5_CENSUS_RECORD_MISMATCH"):
            inspect(missing,inventory=census(records))

    def test_false_coverage_or_missing_inventory_is_blocked(self):
        records=fixtures()
        with self.assertRaisesRegex(EvidenceError,"V5_PROVIDER_INVENTORY_REQUIRED"):
            inspect(records,inventory=census(records,coverage=False))
        with self.assertRaisesRegex(EvidenceError,"V5_PROVIDER_INVENTORY_REQUIRED"):
            inspect(records,inventory={})

    def test_duplicate_provider_rows_and_malformed_attempts_block(self):
        records=fixtures()
        data=census(records)
        data["core_runs"].append(deepcopy(data["core_runs"][0]))
        with self.assertRaisesRegex(EvidenceError,"V5_PROVIDER_DUPLICATE_RUN"):
            inspect(records,inventory=data)
        data=census(records)
        data["core_runs"][0]["run_attempt"]=True
        with self.assertRaisesRegex(EvidenceError,"V5_PROVIDER_RUN_ID_INVALID"):
            inspect(records,inventory=data)

    def test_provider_source_event_status_and_conclusion_cannot_be_laundered(self):
        records=fixtures()
        for field, forged in (
            ("head_sha", "c"*40),
            ("event", "push"),
            ("status", "queued"),
            ("conclusion", "failure"),
        ):
            with self.subTest(field=field):
                provider=census(records)
                provider["core_runs"][6][field]=forged
                with self.assertRaisesRegex(
                    EvidenceError, "V5_PROVIDER_"
                ):
                    inspect(records,inventory=provider)

    def test_provider_created_time_must_precede_run_start(self):
        records=fixtures()
        provider=census(records)
        provider["core_runs"][6]["created_at"]=stamp(
            BEGIN+timedelta(hours=3,minutes=2)
        )
        with self.assertRaisesRegex(EvidenceError,
                                    "V5_PROVIDER_STARTED_BEFORE_CREATED"):
            inspect(records,inventory=provider)

    def test_manifest_clock_inflation_cannot_forge_six_hour_span(self):
        # Provider completes only 5.5 hours after the first run. An altered
        # manifest stretches the last completion by 30 minutes: the legacy
        # reducer would enter postvalidation, but strict V5 must reject it.
        records = fixtures([n / 2 for n in range(12)])
        original_provider = census(records)
        records[-1]["completed_at"] = stamp(
            BEGIN + timedelta(hours=6, seconds=45)
        )
        common = dict(
            source_sha=SHA, current_main=SHA,
            first_state_parent=PARENT, started_at=stamp(BEGIN),
            deadline_at=stamp(BEGIN + timedelta(hours=8)),
            now=stamp(BEGIN + timedelta(hours=6.2)),
        )
        self.assertEqual(
            evaluate_window(records, **common).status,
            "PRE_POSTVALIDATION",
        )
        with self.assertRaisesRegex(
            EvidenceError, "V5_PROVIDER_JOB_COMPLETED_MISMATCH"
        ):
            inspect(records, inventory=original_provider, now=6.2)

    def test_manifest_run_start_must_equal_original_github_run_start(self):
        records = fixtures()
        inventory = census(records)
        records[6]["started_at"] = stamp(
            BEGIN + timedelta(hours=3, seconds=10)
        )
        with self.assertRaisesRegex(
            EvidenceError, "V5_PROVIDER_RUN_STARTED_MISMATCH"
        ):
            inspect(records, inventory=inventory)

    def test_missing_provider_job_or_attempt_is_not_inferred(self):
        records = fixtures()
        for field, reason in (
            ("job", "V5_PROVIDER_JOB_REQUIRED"),
            ("run_started_at", "V5_PROVIDER_RUN_START_REQUIRED"),
            ("run_attempt", "V5_PROVIDER_RUN_ID_INVALID"),
        ):
            with self.subTest(field=field):
                inventory = census(records)
                del inventory["core_runs"][6][field]
                with self.assertRaisesRegex(EvidenceError, reason):
                    inspect(records, inventory=inventory)

    def test_wrong_job_identity_and_rerun_attempt_fail_closed(self):
        records = fixtures()
        for field, bad in (
            ("run_id", 999),
            ("attempt_scope", 2),
            ("head_sha", "e" * 40),
            ("name", "unrelated-check"),
            ("id", True),
        ):
            with self.subTest(field=field):
                inventory = census(records)
                inventory["core_runs"][6]["job"][field] = bad
                with self.assertRaisesRegex(
                    EvidenceError, "V5_PROVIDER_JOB_IDENTITY_INVALID"
                ):
                    inspect(records, inventory=inventory)
        inventory = census(records)
        inventory["core_runs"][6]["job"]["id"] = (
            inventory["core_runs"][5]["job"]["id"]
        )
        with self.assertRaisesRegex(
            EvidenceError, "V5_PROVIDER_JOB_DUPLICATE"
        ):
            inspect(records, inventory=inventory)
        rerun = fixtures()
        rerun[6]["attempt"] = 2
        inventory = census(rerun)
        inventory["core_runs"][6]["job"]["attempt_scope"] = 1
        with self.assertRaisesRegex(
            EvidenceError, "V5_PROVIDER_JOB_IDENTITY_INVALID"
        ):
            inspect(rerun, inventory=inventory)

    def test_job_result_and_chronology_must_match_original_provider(self):
        records = fixtures()
        for field, bad, reason in (
            ("status", "in_progress", "V5_PROVIDER_JOB_COMPLETION_INVALID"),
            ("conclusion", "failure", "V5_PROVIDER_JOB_RESULT_INVALID"),
            ("started_at", stamp(BEGIN + timedelta(hours=4)),
             "V5_PROVIDER_JOB_TIME_INVALID"),
            ("completed_at", None, "V5_PROVIDER_JOB_TIME_REQUIRED"),
            ("completed_at", stamp(BEGIN + timedelta(hours=7)),
             "V5_PROVIDER_JOB_TIME_INVALID"),
        ):
            with self.subTest(field=field, value=bad):
                inventory = census(records)
                inventory["core_runs"][6]["job"][field] = bad
                with self.assertRaisesRegex(EvidenceError, reason):
                    inspect(records, inventory=inventory)

    def test_failed_and_unfinished_provider_rows_cannot_earn_clock_credit(self):
        records = fixtures([0, .5, 1])
        records[1]["status"] = "in_progress"
        records[1]["conclusion"] = None
        records[1]["completed_at"] = None
        inventory = census(records)
        self.assertEqual(
            inspect(records, inventory=inventory, now=1.2).status,
            "WAITING",
        )
        records[1]["completed_at"] = stamp(
            BEGIN + timedelta(hours=.5, seconds=45)
        )
        with self.assertRaisesRegex(
            EvidenceError, "V5_PROVIDER_UNFINISHED_COMPLETION_INVALID"
        ):
            inspect(records, inventory=inventory, now=1.2)
        failed = fixtures([0, .5, 1])
        failed[1]["conclusion"] = "failure"
        self.assertEqual(
            inspect(failed, inventory=census(failed), now=1.2).reason,
            "CORE_EXECUTION_FAILED",
        )

    def test_missing_signed_origin_cannot_satisfy_six_hour_span(self):
        records=fixtures()
        records[-1]["external_clock"]["signed_origin_verified"]=False
        result=inspect(records)
        self.assertEqual(result.status,"WAITING")
        self.assertEqual(result.reason,"SOAK_DURATION_INCOMPLETE")
        self.assertNotIn(records[-1]["run_id"],result.automatic_run_ids)

    def test_all_manual_dispatches_are_not_autoscheduled(self):
        records=fixtures()
        for row in records:
            del row["external_clock"]
        result=inspect(records)
        self.assertEqual(result.status,"WAITING")
        self.assertEqual(result.reason,"INSUFFICIENT_GENUINE_AUTOMATIC_CYCLES")
        self.assertEqual(result.automatic_run_ids,())

    def test_later_confirmed_core_failure_overrides_earlier_incomplete(self):
        records = first_incomplete(fixtures([0, .5, 1]))
        records[-1]["conclusion"] = "failure"
        provider = census(records)
        # The unmodified V3 reducer returns early on the queued first row.
        legacy = evaluate_window(
            records, source_sha=SHA, current_main=SHA,
            first_state_parent=PARENT, started_at=stamp(BEGIN),
            deadline_at=stamp(BEGIN + timedelta(hours=8)),
            now=stamp(BEGIN + timedelta(hours=1.2)),
        )
        self.assertEqual(legacy.status, "WAITING")
        self.assertEqual(legacy.reason, "CORE_EXECUTION_INCOMPLETE")
        strict = inspect(records, inventory=provider, now=1.2)
        self.assertEqual(strict.status, "FAIL")
        self.assertEqual(strict.reason, "CORE_EXECUTION_FAILED")
        self.assertEqual(strict.automatic_run_ids, ())

    def test_later_mandatory_step_failure_overrides_earlier_incomplete(self):
        records = first_incomplete(fixtures([0, .5, 1]))
        records[-1]["steps"]["Evidence-bound deterministic experiment"] = "failure"
        legacy = evaluate_window(
            records, source_sha=SHA, current_main=SHA,
            first_state_parent=PARENT, started_at=stamp(BEGIN),
            deadline_at=stamp(BEGIN + timedelta(hours=8)),
            now=stamp(BEGIN + timedelta(hours=1.2)),
        )
        self.assertEqual(legacy.reason, "CORE_EXECUTION_INCOMPLETE")
        strict = inspect(records, inventory=census(records), now=1.2)
        self.assertEqual(strict.status, "FAIL")
        self.assertEqual(strict.reason, "MANDATORY_STEP_FAILED_OR_MISSING")

    def test_artifact_unverified_after_pending_is_blocked_not_waiting(self):
        records = first_incomplete(fixtures([0, .5, 1]))
        records[-1]["artifact"]["status"] = "UNVERIFIED"
        legacy = evaluate_window(
            records, source_sha=SHA, current_main=SHA,
            first_state_parent=PARENT, started_at=stamp(BEGIN),
            deadline_at=stamp(BEGIN + timedelta(hours=8)),
            now=stamp(BEGIN + timedelta(hours=1.2)),
        )
        self.assertEqual(legacy.reason, "CORE_EXECUTION_INCOMPLETE")
        strict = inspect(records, inventory=census(records), now=1.2)
        self.assertEqual(strict.status, "BLOCKED")
        self.assertEqual(strict.reason, "ARTIFACT_NOT_VERIFIED")

    def test_unverified_remote_state_after_pending_is_blocked(self):
        records = first_incomplete(fixtures([0, .5, 1]))
        records[-1]["state"]["status"] = "UNVERIFIED"
        strict = inspect(records, inventory=census(records), now=1.2)
        self.assertEqual(strict.status, "BLOCKED")
        self.assertEqual(strict.reason, "REMOTE_STATE_NOT_VERIFIED")

    def test_terminal_failure_precedes_other_uncertainties_in_any_order(self):
        records = first_incomplete(fixtures([0, .5, 1, 1.5]))
        records[1]["artifact"]["status"] = "UNVERIFIED"
        records[2]["steps"]["Read-only public project monitoring"] = "failure"
        records[3]["conclusion"] = "cancelled"
        inventory = census(records)
        for ordered in (records, list(reversed(records))):
            with self.subTest(reverse=ordered is not records):
                result = inspect(ordered, inventory=inventory, now=2)
                self.assertEqual(result.status, "FAIL")
                self.assertEqual(result.reason, "CORE_EXECUTION_FAILED")

    def test_no_confirmed_failure_preserves_waiting_and_main_drift(self):
        records = first_incomplete(fixtures([0, .5, 1]))
        provider = census(records)
        waiting = inspect(records, inventory=provider, now=1.2)
        self.assertEqual(waiting.status, "WAITING")
        self.assertEqual(waiting.reason, "CORE_EXECUTION_INCOMPLETE")
        records[-1]["conclusion"] = "failure"
        drift = inspect(records, inventory=census(records), now=1.2,
                        main="e" * 40)
        self.assertEqual(drift.status, "FAIL")
        self.assertEqual(drift.reason, "MAIN_DRIFT")

    def test_failure_inside_provider_census_fails_full_window(self):
        records=fixtures()
        records[3]["conclusion"]="failure"
        result=inspect(records)
        self.assertEqual(result.status,"FAIL")
        self.assertEqual(result.reason,"CORE_EXECUTION_FAILED")

    def test_subsecond_gap_over_ninety_minutes_is_a_real_v5_failure(self):
        # int(5400.5) == 5400, so the historical V3 reducer permits this
        # fractional violation; V5 must enforce the full provider timestamp.
        records = fixtures([0, 1.5 + 0.5 / 3600, 3, 4.5, 6])
        common = dict(
            source_sha=SHA, current_main=SHA, first_state_parent=PARENT,
            started_at=stamp(BEGIN),
            deadline_at=stamp(BEGIN + timedelta(hours=8)),
            now=stamp(BEGIN + timedelta(hours=6.1)),
        )
        self.assertEqual(
            evaluate_window(records, **common).status, "PRE_POSTVALIDATION"
        )
        outcome = inspect(records)
        self.assertEqual(outcome.status, "FAIL")
        self.assertEqual(outcome.reason, "AUTOMATIC_DELIVERY_GAP_EXCEEDED")
        self.assertEqual(outcome.maximum_gap_observed, 5401)

    def test_exact_ninety_minute_completion_gap_is_still_allowed(self):
        records = fixtures([0, 1.5, 3, 4.5, 6])
        outcome = inspect(records)
        self.assertEqual(outcome.status, "PRE_POSTVALIDATION")
        self.assertEqual(outcome.maximum_gap_observed, 5400)
        self.assertEqual(outcome.span_seconds, V5_MIN_SPAN_SECONDS)

    def test_successful_rerun_cannot_extend_six_hour_automatic_clock(self):
        records = fixtures()
        records[-1]["attempt"] = 2
        self.assertEqual(
            evaluate_window(
                records, source_sha=SHA, current_main=SHA,
                first_state_parent=PARENT, started_at=stamp(BEGIN),
                deadline_at=stamp(BEGIN + timedelta(hours=8)),
                now=stamp(BEGIN + timedelta(hours=6.1)),
            ).status, "PRE_POSTVALIDATION",
        )
        result = inspect(records, inventory=census(records))
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason,
                         "V5_RERUN_NOT_NEW_SCHEDULED_CYCLE")
        self.assertEqual(result.automatic_run_ids, ())

    def test_second_successful_attempt_of_same_run_cannot_double_count(self):
        records = fixtures()
        replay = deepcopy(records[-1])
        replay["attempt"] = 2
        replay["started_at"] = stamp(
            BEGIN + timedelta(hours=6, minutes=10)
        )
        replay["completed_at"] = stamp(
            BEGIN + timedelta(hours=6, minutes=10, seconds=45)
        )
        replay["state"]["parent"] = records[-1]["state"]["commit"]
        replay["state"]["commit"] = "f" * 40
        replay["state"]["sequence"] += 1
        replay["artifact"]["state_sequence"] += 1
        replay["state"]["canonical_hash"] = "e" * 64
        replay["artifact"]["canonical_hash"] = "e" * 64
        records.append(replay)
        inventory = census(records)
        # Every run attempt must have its own real job identity.
        inventory["core_runs"][-1]["job"]["id"] = 340001
        result = inspect(records, inventory=inventory, now=6.5)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason,
                         "V5_RERUN_NOT_NEW_SCHEDULED_CYCLE")

    def test_failed_or_unfinished_rerun_keeps_original_classification(self):
        records = fixtures()
        records[6]["attempt"] = 2
        records[6]["conclusion"] = "failure"
        failure = inspect(records, inventory=census(records))
        self.assertEqual(failure.status, "FAIL")
        self.assertEqual(failure.reason, "CORE_EXECUTION_FAILED")
        records[6]["status"] = "in_progress"
        records[6]["conclusion"] = None
        records[6]["completed_at"] = None
        unfinished = inspect(records, inventory=census(records))
        self.assertEqual(unfinished.status, "WAITING")
        self.assertEqual(unfinished.reason, "CORE_EXECUTION_INCOMPLETE")

    def test_manual_push_rerun_never_earns_automatic_cycle_credit(self):
        records = fixtures()
        records[6]["attempt"] = 2
        records[6]["event"] = "push"
        del records[6]["external_clock"]
        result = inspect(records, inventory=census(records))
        self.assertEqual(result.status, "PRE_POSTVALIDATION")
        self.assertNotIn(records[6]["run_id"], result.automatic_run_ids)

    def test_oversized_gap_is_terminal_not_rounded_to_success(self):
        records=fixtures([0,.5,1,3,3.5,4,4.5,5,5.5,6])
        result=inspect(records)
        self.assertEqual(result.status,"FAIL")
        self.assertEqual(result.reason,"AUTOMATIC_DELIVERY_GAP_EXCEEDED")
        self.assertGreater(result.maximum_gap_observed,5400)

    def test_state_parent_discontinuity_fails_closed(self):
        records=fixtures()
        records[6]["state"]["parent"]="f"*40
        result=inspect(records)
        self.assertEqual(result.status,"FAIL")
        self.assertEqual(result.reason,"STATE_PARENT_CHAIN_BROKEN")

    def test_missing_zip_evidence_never_proceeds(self):
        records=fixtures()
        records[6]["artifact"]["status"]="UNVERIFIED"
        result=inspect(records)
        self.assertEqual(result.status,"BLOCKED")
        self.assertEqual(result.reason,"ARTIFACT_NOT_VERIFIED")

    def test_source_drift_and_insufficient_declared_deadline_block(self):
        records=fixtures()
        self.assertEqual(inspect(records,main="c"*40).reason,"MAIN_DRIFT")
        with self.assertRaisesRegex(EvidenceError,
                                    "V5_WINDOW_SHORTER_THAN_SIX_HOURS"):
            inspect(records,hours=5)

    def test_cli_v5_mode_cannot_return_authoritative_pass(self):
        records=fixtures()
        manifest={
            "runs":records,"inventory":census(records),
            "source_sha":SHA,"current_main":SHA,
            "first_state_parent":PARENT,"started_at":stamp(BEGIN),
            "deadline_at":stamp(BEGIN+timedelta(hours=8)),
            "now":stamp(BEGIN+timedelta(hours=6,minutes=5)),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"evidence.json"
            path.write_text(json.dumps(manifest),encoding="utf-8")
            completed=subprocess.run(
                [sys.executable,"-m","soak_v3","window-v5","--manifest",
                 str(path)],capture_output=True,text=True,check=False,timeout=10
            )
        self.assertEqual(completed.returncode,0,completed.stderr)
        output=json.loads(completed.stdout)
        self.assertEqual(output["scope"],"NONAUTHORITATIVE_EVIDENCE_INSPECTION")
        self.assertEqual(output["result"]["status"],"PRE_POSTVALIDATION")
        self.assertNotIn('"status": "PASS"',completed.stdout)


if __name__=="__main__":
    unittest.main()
