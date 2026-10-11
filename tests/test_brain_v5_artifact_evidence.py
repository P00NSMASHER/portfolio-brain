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
from unittest.mock import patch
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


def replace_zip_member(source_bytes, name, replacement):
    """Construct a new ZIP with valid member CRCs, not an accidental corruption."""
    with zipfile.ZipFile(io.BytesIO(source_bytes), "r") as archive:
        original = [(item.filename, archive.read(item))
                    for item in archive.infolist()]
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, body in original:
            archive.writestr(path, replacement if path == name else body)
    return result.getvalue()


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

    def test_duplicate_keys_are_rejected_in_every_required_v5_receipt(self):
        original = fixture()
        required = (
            "delivery.json", "preflight/report.json", "report/report.json",
            "research/report.json", "experiment/report.json",
            "doctor/report.json",
        )
        with zipfile.ZipFile(io.BytesIO(original), "r") as archive:
            documents = {name: json.loads(archive.read(name)) for name in required}
        for name in required:
            with self.subTest(member=name):
                # Last-key-wins would silently accept the original legitimate
                # source even though the same JSON object also claims another.
                duplicate = ('{"source_sha":"' + "e" * 40 + '",'
                             + json.dumps(documents[name], sort_keys=True)[1:])
                payload = replace_zip_member(original, name, duplicate.encode())
                self.assertEqual(self.check(payload, strict=False)["status"], "PASS")
                with self.assertRaisesRegex(EvidenceError,
                                            "V5_JSON_DUPLICATE_KEY"):
                    self.check(payload)

    def test_nested_duplicate_doctor_workload_key_is_rejected(self):
        original = fixture()
        with zipfile.ZipFile(io.BytesIO(original), "r") as archive:
            text = archive.read("doctor/report.json").decode()
        token = '"monitor": "PASS"'
        self.assertEqual(text.count(token), 1)
        altered = text.replace(token, '"monitor": "FAIL", "monitor": "PASS"')
        payload = replace_zip_member(
            original, "doctor/report.json", altered.encode()
        )
        self.assertEqual(self.check(payload, strict=False)["status"], "PASS")
        with self.assertRaisesRegex(EvidenceError, "V5_JSON_DUPLICATE_KEY"):
            self.check(payload)

    def test_nonfinite_numbers_rejected_even_in_ignored_receipt_fields(self):
        original = fixture()
        with zipfile.ZipFile(io.BytesIO(original), "r") as archive:
            research = archive.read("research/report.json").decode()
        for number in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(number=number):
                malformed = '{"ignored_metric": ' + number + ',' + research[1:]
                payload = replace_zip_member(
                    original, "research/report.json", malformed.encode()
                )
                self.assertEqual(self.check(payload, strict=False)["status"],
                                 "PASS")
                with self.assertRaisesRegex(EvidenceError,
                                            "V5_JSON_NONFINITE_NUMBER"):
                    self.check(payload)

    def test_boolean_pending_events_never_counts_as_integer_zero(self):
        for name in (
            "doctor/report.json", "report/report.json",
            "research/report.json", "experiment/report.json",
        ):
            with self.subTest(member=name):
                payload = fixture(mutate=(name, "pending_events", False))
                self.assertEqual(self.check(payload, strict=False)["status"],
                                 "PASS")
                error = ("V5_ARTIFACT_PENDING_EVENTS_TYPE_INVALID"
                         if name == "doctor/report.json" else
                         "V5_WORKLOAD_PENDING_EVENTS_TYPE_INVALID")
                with self.assertRaisesRegex(EvidenceError, error):
                    self.check(payload)

    def test_nonobject_root_receipts_fail_closed_in_v5(self):
        original = fixture()
        for name, error in (
            ("delivery.json", "V5_ARTIFACT_RECEIPT_NOT_OBJECT"),
            ("preflight/report.json", "V5_ARTIFACT_RECEIPT_NOT_OBJECT"),
            ("doctor/report.json", "V5_ARTIFACT_RECEIPT_NOT_OBJECT"),
            ("research/report.json", "V5_WORKLOAD_RECEIPT_NOT_OBJECT"),
        ):
            with self.subTest(member=name):
                payload = replace_zip_member(original, name, b"[]")
                with self.assertRaisesRegex(EvidenceError, error):
                    self.check(payload)

    def test_six_original_receipts_pass_with_consistent_chain(self):
        receipt=self.check(fixture())
        self.assertEqual(receipt["status"],"PASS")
        self.assertEqual(receipt["workload_reports"],"PASS")
        self.assertEqual(receipt["member_crc"],"PASS")
        self.assertEqual(receipt["state_sequence"],63)
        self.assertEqual(receipt["workload_sequences"],
                         {"monitor":60,"research":62,"experiment":63,"doctor":63})

    def test_v5_same_size_path_swap_after_sha_never_changes_inspected_zip(self):
        original = fixture()
        substituted = fixture(mutate=("doctor/report.json", "pending_events", 1))
        self.assertEqual(len(original), len(substituted))
        self.assertNotEqual(hashlib.sha256(original).digest(),
                            hashlib.sha256(substituted).digest())
        self.path.write_bytes(original)
        observed = []
        zip_constructor = zipfile.ZipFile

        def swap_at_zip_open(source, *args, **kwargs):
            observed.append(source)
            if len(observed) == 1:
                # Replace original ZIP with a completely valid same-length ZIP
                # whose doctor is not PASS, *after* original SHA verification.
                self.path.write_bytes(substituted)
            self.assertIsInstance(source, io.BytesIO)
            self.assertEqual(source.getvalue(), original)
            return zip_constructor(source, *args, **kwargs)

        with patch("soak_v3.audit.zipfile.ZipFile",
                   side_effect=swap_at_zip_open):
            result = self.check_original_zip(original, strict=True)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["workload_reports"], "PASS")
        self.assertEqual(result["artifact_sha256"],
                         hashlib.sha256(original).hexdigest())
        self.assertGreaterEqual(len(observed), 2)
        self.assertEqual(self.path.read_bytes(), substituted)

    def test_v5_path_swap_between_delivery_and_crc_uses_same_hashed_bytes(self):
        original = fixture()
        # Valid new ZIP deliberately omits the research report; V5 must not
        # inspect it after checking the first ZIP's original delivery receipt.
        substituted = fixture(removed="research/report.json")
        self.path.write_bytes(original)
        zip_constructor = zipfile.ZipFile
        inspected = []

        def swap_second_parse(source, *args, **kwargs):
            inspected.append(source)
            self.assertIsInstance(source, io.BytesIO)
            self.assertEqual(source.getvalue(), original)
            if len(inspected) == 2:
                self.path.write_bytes(substituted)
            return zip_constructor(source, *args, **kwargs)

        with patch("soak_v3.audit.zipfile.ZipFile",
                   side_effect=swap_second_parse):
            receipt = self.check_original_zip(original, strict=True)
        self.assertEqual(receipt["workload_reports"], "PASS")
        self.assertGreaterEqual(len(inspected), 2)
        self.assertEqual(self.path.read_bytes(), substituted)

    def test_legacy_artifact_still_parses_only_original_verified_bytes(self):
        original = fixture(removed="research/report.json")
        substituted = fixture(
            removed="research/report.json",
            mutate=("doctor/report.json", "pending_events", 1),
        )
        self.assertEqual(len(original), len(substituted))
        self.path.write_bytes(original)
        constructor = zipfile.ZipFile
        opened = []

        def swap_before_legacy_zip(source, *args, **kwargs):
            opened.append(source)
            self.path.write_bytes(substituted)
            self.assertIsInstance(source, io.BytesIO)
            self.assertEqual(source.getvalue(), original)
            return constructor(source, *args, **kwargs)

        with patch("soak_v3.audit.zipfile.ZipFile",
                   side_effect=swap_before_legacy_zip):
            result = self.check_original_zip(original, strict=False)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["artifact_sha256"],
                         hashlib.sha256(original).hexdigest())
        self.assertEqual(len(opened), 1)
        self.assertEqual(self.path.read_bytes(), substituted)

    def test_oversized_zip_fails_before_open_or_allocate(self):
        with self.path.open("wb") as stream:
            stream.truncate(20_000_000)
        with patch.object(Path, "open",
                          side_effect=AssertionError("oversized artifact opened")):
            for strict in (False, True):
                with self.subTest(strict=strict):
                    with self.assertRaisesRegex(EvidenceError,
                                                "ARTIFACT_SIZE_INVALID"):
                        self.check_original_zip(b"", strict=strict)

    def test_short_read_fails_before_any_zip_parse(self):
        original = fixture()
        self.path.write_bytes(original)
        with patch.object(Path, "open", return_value=io.BytesIO(b"short")):
            with patch("soak_v3.audit.zipfile.ZipFile",
                       side_effect=AssertionError("short ZIP was parsed")):
                with self.assertRaisesRegex(
                    EvidenceError, "ARTIFACT_SIZE_CHANGED_DURING_READ"
                ):
                    self.check_original_zip(original, strict=True)

    def check_original_zip(self, original, *, strict):
        kwargs = dict(
            run_id=RUN, source_sha=SHA, state_parent=PARENT, state_commit=COMMIT,
        )
        verifier = verify_v5_artifact if strict else verify_artifact
        return verifier(
            self.path, "sha256:" + hashlib.sha256(original).hexdigest(),
            **kwargs,
        )

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
