import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from events.validate_event import (
    EventValidationError,
    compute_evidence_hash,
    compute_event_hash,
    compute_idempotency_key,
    load_event_type_catalog,
    validate_bundle,
    validate_evidence,
    validate_event,
)

def content_hash(text):
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()

def evidence_record(
    evidence_id="EVD-TEST-00000001",
    state="VERIFIED",
    evidence_type="TEST_RECEIPT",
    actor_type="SYSTEM",
    actor_id="ci",
):
    record={
        "schema_version":"1.0.0",
        "evidence_id":evidence_id,
        "project_id":"PRJ-000",
        "evidence_type":evidence_type,
        "evidence_state":state,
        "subject_refs":["build:step3"],
        "source":{
            "source_kind":"GITHUB",
            "source_ref":"P00NSMASHER/portfolio-brain/actions/runs/1",
            "source_revision":"0123456789abcdef0123456789abcdef01234567",
            "retrieved_at":"2026-09-25T15:00:00Z",
            "content_hash":content_hash("pass"),
        },
        "actor":{"actor_type":actor_type,"actor_id":actor_id},
        "observed_at":"2026-09-25T15:00:00Z",
        "verification":{
            "method":"DETERMINISTIC_TEST" if state=="VERIFIED" else "NONE",
            "verifier_actor_id":"github-actions" if state=="VERIFIED" else None,
            "verified_at":"2026-09-25T15:00:01Z" if state=="VERIFIED" else None,
            "basis_evidence_ids":[],
            "reason":None,
        },
        "supports_refs":["step:3"],
        "contradicts_refs":[],
        "evidence_hash":"",
    }
    record["evidence_hash"]=compute_evidence_hash(record)
    return record

def event_record(evidence_id="EVD-TEST-00000001", status="VERIFIED"):
    record={
        "schema_version":"1.0.0",
        "event_id":"EVT-TEST-00000001",
        "event_type":"TEST_PASSED",
        "occurred_at":"2026-09-25T15:00:01Z",
        "recorded_at":"2026-09-25T15:00:02Z",
        "project_id":"PRJ-000",
        "source":{
            "system":"github-actions",
            "source_ref":"run:1",
            "source_revision":"0123456789abcdef0123456789abcdef01234567",
        },
        "actor":{"actor_type":"SYSTEM","actor_id":"github-actions"},
        "authority_class":"OBSERVE",
        "subject_refs":["step:3"],
        "evidence_ids":[evidence_id],
        "verification_status":status,
        "dependency_event_ids":[],
        "causal_event_ids":[],
        "metrics":[],
        "data_classification":"SANITIZED",
        "payload":{"result":"pass"},
        "idempotency_key":"",
        "event_hash":"",
    }
    record["idempotency_key"]=compute_idempotency_key(record)
    record["event_hash"]=compute_event_hash(record)
    return record

class EvidenceEventContractTests(unittest.TestCase):
    def test_json_schemas_are_closed_and_preserve_evidence_states(self):
        event_schema=json.loads((ROOT/"schemas"/"EVENT_SCHEMA.json").read_text())
        evidence_schema=json.loads((ROOT/"schemas"/"EVIDENCE_SCHEMA.json").read_text())
        self.assertFalse(event_schema["additionalProperties"])
        self.assertFalse(evidence_schema["additionalProperties"])
        self.assertEqual(
            set(evidence_schema["properties"]["evidence_state"]["enum"]),
            {"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"},
        )
        self.assertEqual(
            set(event_schema["properties"]["verification_status"]["enum"]),
            {"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"},
        )

    def test_required_event_catalog(self):
        catalog=load_event_type_catalog()
        required={
            "PROJECT_CREATED","BUILD_PASSED","BUILD_FAILED","TEST_PASSED","TEST_FAILED",
            "BUG_FOUND","BUG_FIXED","EXPERIMENT_STARTED","EXPERIMENT_PASSED","EXPERIMENT_FAILED",
            "MODEL_REGRESSED","MODEL_IMPROVED","CAPABILITY_DISCOVERED","CAPABILITY_REUSED",
            "CUSTOMER_ACQUIRED","CUSTOMER_LOST","REVENUE_COLLECTED","VALUE_REALIZED",
            "PR_CREATED","PR_REJECTED","PR_MERGED","RELEASE_CREATED","HUNTER_FINDING",
            "RESEARCH_REJECTED","POLICY_UPDATED","SKILL_PROMOTED"
        }
        self.assertTrue(required <= catalog)

    def test_verified_evidence_and_event(self):
        evd=evidence_record()
        evt=event_record()
        validate_evidence(evd)
        validate_event(evt,{evd["evidence_id"]:evd})
        self.assertEqual(validate_bundle([evt],[evd]),{"events":1,"evidence":1})

    def test_tampered_evidence_hash_rejected(self):
        evd=evidence_record()
        evd["source"]["source_ref"]="tampered"
        with self.assertRaises(EventValidationError):
            validate_evidence(evd)

    def test_tampered_event_hash_rejected(self):
        evd=evidence_record()
        evt=event_record()
        evt["payload"]["result"]="tampered"
        with self.assertRaises(EventValidationError):
            validate_event(evt,{evd["evidence_id"]:evd})

    def test_wrong_idempotency_key_rejected(self):
        evd=evidence_record()
        evt=event_record()
        evt["idempotency_key"]="sha256:"+"0"*64
        evt["event_hash"]=compute_event_hash(evt)
        with self.assertRaises(EventValidationError):
            validate_event(evt,{evd["evidence_id"]:evd})

    def test_duplicate_source_event_rejected(self):
        evd=evidence_record()
        first=event_record()
        second=copy.deepcopy(first)
        second["event_id"]="EVT-TEST-00000002"
        second["event_hash"]=compute_event_hash(second)
        with self.assertRaises(EventValidationError):
            validate_bundle([first,second],[evd])

    def test_model_output_cannot_self_verify(self):
        evd=evidence_record(evidence_type="MODEL_OUTPUT",actor_type="MODEL",actor_id="model-a")
        evd["verification"]["verifier_actor_id"]="model-a"
        evd["evidence_hash"]=compute_evidence_hash(evd)
        with self.assertRaises(EventValidationError):
            validate_evidence(evd)

    def test_inference_requires_basis_evidence(self):
        evd=evidence_record(state="INFERRED",evidence_type="MODEL_OUTPUT",actor_type="MODEL",actor_id="model-a")
        evd["verification"]["method"]="MODEL_INFERENCE"
        evd["evidence_hash"]=compute_evidence_hash(evd)
        with self.assertRaises(EventValidationError):
            validate_evidence(evd)

    def test_inferred_receipt_preserves_inferred_state(self):
        evd=evidence_record(state="INFERRED",evidence_type="MODEL_OUTPUT",actor_type="MODEL",actor_id="model-a")
        evd["verification"].update({
            "method":"MODEL_INFERENCE",
            "basis_evidence_ids":["EVD-BASIS-00000001"],
            "reason":"model synthesis"
        })
        evd["evidence_hash"]=compute_evidence_hash(evd)
        validate_evidence(evd)
        self.assertEqual(evd["evidence_state"],"INFERRED")

    def test_verified_event_requires_verified_evidence(self):
        evd=evidence_record(state="OBSERVED",evidence_type="SYSTEM_OBSERVATION")
        evt=event_record(status="VERIFIED")
        with self.assertRaises(EventValidationError):
            validate_event(evt,{evd["evidence_id"]:evd})

    def test_cross_project_evidence_rejected(self):
        evd=evidence_record()
        evd["project_id"]="PRJ-001"
        evd["evidence_hash"]=compute_evidence_hash(evd)
        evt=event_record()
        with self.assertRaises(EventValidationError):
            validate_event(evt,{evd["evidence_id"]:evd})

    def test_recorded_at_cannot_precede_occurrence(self):
        evd=evidence_record()
        evt=event_record()
        evt["recorded_at"]="2026-09-25T14:59:00Z"
        evt["event_hash"]=compute_event_hash(evt)
        with self.assertRaises(EventValidationError):
            validate_event(evt,{evd["evidence_id"]:evd})

    def test_private_reference_payload_cannot_hold_raw_fields(self):
        evd=evidence_record()
        evt=event_record()
        evt["data_classification"]="PRIVATE_REFERENCE_ONLY"
        evt["payload"]={"reference":"vault:item-1","redacted":True,"customer_name":"secret"}
        evt["event_hash"]=compute_event_hash(evt)
        with self.assertRaises(EventValidationError):
            validate_event(evt,{evd["evidence_id"]:evd})

    def test_private_reference_payload_is_allowed_when_redacted(self):
        evd=evidence_record()
        evt=event_record()
        evt["data_classification"]="PRIVATE_REFERENCE_ONLY"
        evt["payload"]={"reference":"vault:item-1","summary":"redacted evidence reference","redacted":True}
        evt["event_hash"]=compute_event_hash(evt)
        validate_event(evt,{evd["evidence_id"]:evd})

    def test_unknown_evidence_requires_reason(self):
        evd=evidence_record(state="UNKNOWN",evidence_type="SYSTEM_OBSERVATION")
        with self.assertRaises(EventValidationError):
            validate_evidence(evd)

    def test_missing_dependency_fails_bundle(self):
        evd=evidence_record()
        evt=event_record()
        evt["dependency_event_ids"]=["EVT-MISSING-00000001"]
        evt["event_hash"]=compute_event_hash(evt)
        with self.assertRaises(EventValidationError):
            validate_bundle([evt],[evd])

    def test_missing_inference_basis_fails_bundle(self):
        evd=evidence_record(state="INFERRED",evidence_type="MODEL_OUTPUT",actor_type="MODEL",actor_id="model-a")
        evd["verification"].update({
            "method":"MODEL_INFERENCE",
            "basis_evidence_ids":["EVD-MISSING-00000001"],
            "reason":"model synthesis"
        })
        evd["evidence_hash"]=compute_evidence_hash(evd)
        evt=event_record(evidence_id=evd["evidence_id"],status="INFERRED")
        evt["event_hash"]=compute_event_hash(evt)
        with self.assertRaises(EventValidationError):
            validate_bundle([evt],[evd])

if __name__=="__main__":
    unittest.main()
