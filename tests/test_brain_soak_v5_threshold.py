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
                "status": item["status"],
                "conclusion": item["conclusion"],
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
                    EvidenceError, "V5_PROVIDER_.*MISMATCH"
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

    def test_failure_inside_provider_census_fails_full_window(self):
        records=fixtures()
        records[3]["conclusion"]="failure"
        result=inspect(records)
        self.assertEqual(result.status,"FAIL")
        self.assertEqual(result.reason,"CORE_EXECUTION_FAILED")

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
