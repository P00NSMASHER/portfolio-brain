"""Adversarial tests for *offline only* actual artifact ZIP-byte verification.

Only synthetic ZIP fixtures. They do NOT authenticate the GitHub artifacts
provider, Cloudflare's Cron schedule, live SQLite bytes or terminal V5 soak.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from soak_v3.audit import EvidenceError
from soak_v3.original_zip_bundle import inspect_original_zip_bundle

SHA = "a"*40
PARENT = "b"*40
START = datetime(2026, 10, 10, 1, 50, 19, tzinfo=timezone.utc)


def utc(t):
    return t.isoformat(timespec="seconds").replace("+00:00","Z")


def make_zip(path, *, run_id, parent, state_commit, index,
             doctor_status="PASS", research_status="PASS",
             origin_signed=True, report_sha=SHA, clock_kind="cloudflare_cron_v1"):
    dt=START+timedelta(minutes=30*index)
    artifacts={
        "delivery.json":{
            "schema_version":2, "run_id":str(run_id), "run_attempt":"1",
            "source_sha":report_sha, "state_parent":parent,
            "state_commit":state_commit,"publication_verified":True,
            "soak_completed":False,
        },
        "preflight/report.json":{
            "source_sha":report_sha,"status":"PASS","live_sources":"NOT_TESTED"
        },
        "doctor/report.json":{
            "status":doctor_status,"source_sha":report_sha,
            "pending_events":0,"state_sequence":600+7*index,
            "canonical_hash":format(index+1,"064x"),
            "checked_at":utc(dt+timedelta(seconds=35)),
            "mandatory_workloads":{
                "monitor":"PASS","research":"PASS","experiment":"PASS",
            },
            "verified_canonical_state":True,
            "production_accepted":False,
            "workflow_delivery":"NOT_TESTED_BY_LOCAL_DOCTOR",
        },
        "report/report.json":{"status":"PASS","source_sha":report_sha},
        "research/report.json":{"status":research_status,"source_sha":report_sha},
        "experiment/report.json":{"status":"PASS","source_sha":report_sha},
        "cloudflare-origin.json":{
            "kind":clock_kind,"status":"CLOUDFLARE_SIGNED_ORIGIN_VERIFIED",
            "signed_origin":origin_signed,"soak_pass":False,
            "source_sha":report_sha,"scheduled_at":utc(dt),
        },
    }
    with ZipFile(path,"w",compression=ZIP_DEFLATED) as z:
        for name,obj in artifacts.items():
            z.writestr(name,json.dumps(obj,sort_keys=True))
    return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()


class OriginalZIPBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def manifest(self,n=3,**opts):
        rows=[]
        parent=PARENT
        for index in range(n):
            run_id=9000+index
            state_commit=format(index+1,"040x")
            path=self.root/f"{run_id}.zip"
            digest=make_zip(path,run_id=run_id,parent=parent,
                            state_commit=state_commit,index=index,**opts)
            rows.append({
                "run_id":run_id, "path":str(path),
                "provider_digest":digest,"state_commit":state_commit,
            })
            parent=state_commit
        return {
            "source_sha":SHA,"first_state_parent":PARENT,
            "expected_last_state_commit":parent,"artifacts":rows,
        }

    def test_real_local_zip_bytes_verified_never_become_final_acceptance(self):
        data=self.manifest()
        before={f["path"]:Path(f["path"]).read_bytes() for f in data["artifacts"]}
        proof=inspect_original_zip_bundle(data)
        self.assertEqual(proof["status"],"EVIDENCE_INSPECTED_NOT_ACCEPTED")
        self.assertEqual(proof["run_count"],3)
        self.assertEqual([x["state_sequence"] for x in proof["records"]],[600,607,614])
        self.assertEqual(proof["doctor_timestamp_span_seconds"],3600)
        self.assertFalse(proof["independent_github_digest_provenance_verified"])
        self.assertFalse(proof["independent_cloudflare_cron_provenance_verified"])
        self.assertFalse(proof["original_remote_state_bytes_replayed"])
        self.assertFalse(proof["soak_pass"])
        self.assertEqual(proof["terminal_v5_acceptance"],"NOT_ESTABLISHED")
        for path,contents in before.items():
            self.assertEqual(Path(path).read_bytes(),contents)

    def test_digest_mismatch_is_fatal_even_if_embedded_reports_look_green(self):
        doc=self.manifest()
        doc["artifacts"][1]["provider_digest"]="sha256:"+"0"*64
        with self.assertRaisesRegex(EvidenceError,"ARTIFACT_SHA256_MISMATCH"):
            inspect_original_zip_bundle(doc)

    def test_missing_or_duplicate_run_id_is_rejected(self):
        doc=self.manifest()
        doc["artifacts"][1]["run_id"]=doc["artifacts"][0]["run_id"]
        with self.assertRaisesRegex(EvidenceError,"ORIGINAL_RUN_ORDER_OR_ID_INVALID"):
            inspect_original_zip_bundle(doc)
        doc=self.manifest()
        doc["artifacts"].reverse()
        with self.assertRaisesRegex(EvidenceError,"ORIGINAL_RUN_ORDER_OR_ID_INVALID"):
            inspect_original_zip_bundle(doc)

    def test_missing_state_parent_never_launders_a_completed_core(self):
        doc=self.manifest()
        doc["first_state_parent"]="c"*40
        with self.assertRaisesRegex(EvidenceError,"DELIVERY_STATE_LINEAGE_INVALID"):
            inspect_original_zip_bundle(doc)

    def test_modified_zip_bad_doctor_still_rejected_with_matching_digest(self):
        doc=self.manifest(doctor_status="FAIL")
        with self.assertRaisesRegex(EvidenceError,"DOCTOR_NOT_PASS"):
            inspect_original_zip_bundle(doc)

    def test_mandatory_research_failure_fatal(self):
        doc=self.manifest(research_status="FAIL")
        with self.assertRaisesRegex(EvidenceError,"ORIGINAL_MANDATORY_REPORT_FAILED"):
            inspect_original_zip_bundle(doc)

    def test_fake_or_missing_signer_claim_is_rejected(self):
        doc=self.manifest(origin_signed=False)
        with self.assertRaisesRegex(EvidenceError,"ORIGINAL_EMBEDDED_CLOCK_NOT_VALIDATED"):
            inspect_original_zip_bundle(doc)
        doc=self.manifest(clock_kind="manually_dispatched")
        with self.assertRaisesRegex(EvidenceError,"ORIGINAL_EMBEDDED_CLOCK_NOT_VALIDATED"):
            inspect_original_zip_bundle(doc)

    def test_wrong_source_is_never_accepted(self):
        doc=self.manifest(report_sha="c"*40)
        with self.assertRaisesRegex(EvidenceError,"DELIVERY_SOURCE_OR_RUN_MISMATCH"):
            inspect_original_zip_bundle(doc)

    def test_last_tip_mismatch_is_fatal(self):
        doc=self.manifest()
        doc["expected_last_state_commit"]="f"*40
        with self.assertRaisesRegex(EvidenceError,"ORIGINAL_FINAL_STATE_TIP_MISMATCH"):
            inspect_original_zip_bundle(doc)

    def test_missing_or_unbounded_list_fails_closed(self):
        doc=self.manifest()
        doc["artifacts"]=[]
        with self.assertRaisesRegex(EvidenceError,"ORIGINAL_ARTIFACT_LIST_INVALID"):
            inspect_original_zip_bundle(doc)
        doc["artifacts"]="do not trust strings"
        with self.assertRaisesRegex(EvidenceError,"ORIGINAL_ARTIFACT_LIST_INVALID"):
            inspect_original_zip_bundle(doc)

    def test_cli_is_non_authoritative_and_does_not_modify_input(self):
        doc=self.manifest()
        manifest=self.root/"manifest.json"
        manifest.write_text(json.dumps(doc),encoding="utf-8")
        before=manifest.read_bytes()
        done=subprocess.run(
            [sys.executable,"-m","soak_v3.original_zip_bundle",
             "--manifest",str(manifest)],
            capture_output=True,text=True,check=False,timeout=15,
        )
        self.assertEqual(done.returncode,0,done.stderr)
        proof=json.loads(done.stdout)
        self.assertFalse(proof["soak_pass"])
        self.assertEqual(proof["terminal_v5_acceptance"],"NOT_ESTABLISHED")
        self.assertEqual(manifest.read_bytes(),before)

    def test_cli_failure_never_leaks_private_file_path(self):
        doc=self.manifest()
        secret="do-not-emit-private-directory-007"
        doc["artifacts"][0]["path"]=str(self.root/secret/"nonexistent.zip")
        manifest=self.root/"manifest.json"
        manifest.write_text(json.dumps(doc),encoding="utf-8")
        done=subprocess.run(
            [sys.executable,"-m","soak_v3.original_zip_bundle",
             "--manifest",str(manifest)],
            capture_output=True,text=True,check=False,timeout=15,
        )
        self.assertEqual(done.returncode,1)
        self.assertEqual(json.loads(done.stdout)["status"],"BLOCKED")
        self.assertNotIn(secret,done.stdout)
        self.assertNotIn(str(self.root),done.stdout)


if __name__=="__main__":
    unittest.main()
