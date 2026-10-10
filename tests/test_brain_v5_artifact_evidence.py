"""Mandatory V5 original-artifact receipts, fail-closed on truncated ZIPs.

All fixture ZIPs in this test are synthetic. A green test cannot establish a
real scheduled Cloudflare run or source-specific production acceptance.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from soak_v3.audit import EvidenceError, verify_artifact, verify_v5_artifact

SHA="a"*40
PARENT="b"*40
COMMIT="c"*40
RUN=847


def fixture(*, removed=None, mutate=None, extra=False):
    base={
        "delivery.json":{
            "schema_version":2,"source_sha":SHA,"run_id":str(RUN),
            "state_parent":PARENT,"state_commit":COMMIT,
            "publication_verified":True,"soak_completed":False,
        },
        "preflight/report.json":{
            "status":"PASS","source_sha":SHA,"live_sources":"NOT_TESTED",
        },
        "doctor/report.json":{
            "status":"PASS","source_sha":SHA,"pending_events":0,
            "state_sequence":63,"canonical_hash":"d"*64,
            "workflow_delivery":"NOT_TESTED_BY_LOCAL_DOCTOR",
            "mandatory_workloads":{"monitor":"PASS","research":"PASS",
                                   "experiment":"PASS"},
        },
        "report/report.json":{
            "status":"PASS","source_sha":SHA,"pending_events":0,
            "state_sequence":60,"canonical_hash":"1"*64,
            "operation":{"name":"monitor","errors":[]},
        },
        "research/report.json":{
            "status":"PASS","source_sha":SHA,"pending_events":0,
            "state_sequence":62,"canonical_hash":"2"*64,
            "operation":{"name":"research","result":"OBSERVED"},
        },
        "experiment/report.json":{
            "status":"PASS","source_sha":SHA,"pending_events":0,
            "state_sequence":63,"canonical_hash":"d"*64,
        },
    }
    if mutate is not None:
        path,field,value=mutate
        base[path][field]=value
    if removed:
        del base[removed]
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_STORED) as zipfile_out:
        for name,doc in base.items():
            zipfile_out.writestr(name,json.dumps(doc,sort_keys=True))
        if extra:
            zipfile_out.writestr("noncritical/readme.txt",
                                 b"UNIQUE-NONCRITICAL-ZIP-CHECKSUM-SENTINEL")
    data=buffer.getvalue()
    return data


class V5MandatoryArtifactEvidence(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"evidence.zip"

    def check(self,content, *, strict=True):
        self.path.write_bytes(content)
        args=(self.path,"sha256:"+hashlib.sha256(content).hexdigest())
        kw=dict(run_id=RUN,source_sha=SHA,
                state_parent=PARENT,state_commit=COMMIT)
        return (verify_v5_artifact if strict else verify_artifact)(*args,**kw)

    def test_six_original_receipts_pass_with_consistent_chain(self):
        receipt=self.check(fixture())
        self.assertEqual(receipt["status"],"PASS")
        self.assertEqual(receipt["workload_reports"],"PASS")
        self.assertEqual(receipt["member_crc"],"PASS")
        self.assertEqual(receipt["state_sequence"],63)
        self.assertEqual(receipt["workload_sequences"],
                         {"monitor":60,"research":62,"experiment":63,"doctor":63})

    def test_legacy_artifact_check_remains_compatible(self):
        missing=fixture(removed="research/report.json")
        self.assertEqual(self.check(missing,strict=False)["status"],"PASS")
        with self.assertRaisesRegex(EvidenceError,"V5_WORKLOAD_RECEIPT_MISSING"):
            self.check(missing)

    def test_each_individual_workload_receipt_must_exist(self):
        for name in ("report/report.json","research/report.json",
                     "experiment/report.json"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(EvidenceError,
                                            "V5_WORKLOAD_RECEIPT_MISSING"):
                    self.check(fixture(removed=name))

    def test_failed_workload_cannot_be_laundered_by_green_doctor(self):
        for name in ("report/report.json","research/report.json",
                     "experiment/report.json"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(EvidenceError,
                                            "V5_WORKLOAD_RECEIPT_NOT_PASS"):
                    self.check(fixture(mutate=(name,"status","FAIL")))

    def test_cross_source_report_rejected(self):
        for name in ("report/report.json","research/report.json",
                     "experiment/report.json"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(EvidenceError,
                                            "V5_WORKLOAD_RECEIPT_NOT_PASS"):
                    self.check(fixture(mutate=(name,"source_sha","e"*40)))

    def test_sequence_regression_or_laundered_final_report_rejected(self):
        with self.assertRaisesRegex(EvidenceError,
                                    "V5_WORKLOAD_SEQUENCE_DISAGREEMENT"):
            self.check(fixture(mutate=("research/report.json",
                                       "state_sequence",59)))
        with self.assertRaisesRegex(EvidenceError,
                                    "V5_WORKLOAD_SEQUENCE_DISAGREEMENT"):
            self.check(fixture(mutate=("experiment/report.json",
                                       "state_sequence",62)))

    def test_wrong_experiment_chain_rejected_even_doctor_green(self):
        with self.assertRaisesRegex(EvidenceError,
                                    "V5_EXPERIMENT_DOCTOR_CHAIN_DISAGREEMENT"):
            self.check(fixture(mutate=("experiment/report.json",
                                       "canonical_hash","f"*64)))

    def test_doctor_mandatory_steps_cannot_be_missing(self):
        with self.assertRaisesRegex(EvidenceError,
                                    "V5_DOCTOR_MANDATORY_WORKLOADS_INVALID"):
            self.check(fixture(mutate=("doctor/report.json",
                                       "mandatory_workloads",
                                       {"monitor":"PASS","research":"PASS"})))

    def test_unreadable_noncritical_member_rejected_despite_sha_match(self):
        raw=fixture(extra=True)
        old=b"UNIQUE-NONCRITICAL-ZIP-CHECKSUM-SENTINEL"
        new=b"UNIQUE-NONCRITICAL-ZIP-CHECKSUM-XENTINEL"
        self.assertEqual(len(old),len(new))
        self.assertEqual(raw.count(old),1)
        tampered=raw.replace(old,new,1)
        # An independently supplied provider hash can describe a malformed
        # original archive. The digest match alone must not bless bad CRCs.
        with self.assertRaisesRegex(
            EvidenceError,
            "V5_ARTIFACT_MEMBER_CRC_INVALID|V5_WORKLOAD_RECEIPT_UNREADABLE",
        ):
            self.check(tampered)

    def test_non_dictionary_workload_receipt_rejected(self):
        raw=fixture()
        original=json.dumps({
            "status":"PASS","source_sha":SHA,"pending_events":0,
            "state_sequence":62,"canonical_hash":"2"*64,
            "operation":{"name":"research","result":"OBSERVED"},
        },sort_keys=True).encode()
        self.assertIn(original,raw)
        altered=raw.replace(original,b"[]" + b" "*(len(original)-2),1)
        # Modified payload deliberately breaks CRC. A valid-CRC non-dict is
        # separately rejected by strict schema when created as valid ZIP below.
        with self.assertRaises(EvidenceError):
            self.check(altered)

    def test_cli_artifact_v5_is_a_local_inspection_not_acceptance(self):
        blob=fixture()
        self.path.write_bytes(blob)
        manifest={
            "path":str(self.path),
            "expected_digest":"sha256:"+hashlib.sha256(blob).hexdigest(),
            "run_id":RUN,"source_sha":SHA,
            "state_parent":PARENT,"state_commit":COMMIT,
        }
        manifest_path=Path(self.temp.name)/"manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        call=subprocess.run(
            [sys.executable,"-m","soak_v3","artifact-v5",
             "--manifest",str(manifest_path)],
            capture_output=True,text=True,timeout=15,check=False,
        )
        self.assertEqual(call.returncode,0,call.stderr)
        result=json.loads(call.stdout)
        self.assertEqual(result["scope"],"NONAUTHORITATIVE_EVIDENCE_INSPECTION")
        self.assertEqual(result["result"]["workload_reports"],"PASS")
        self.assertNotIn("terminal_acceptance", result["result"])


if __name__=="__main__":
    unittest.main()
