#!/usr/bin/env python3
"""Strict sanitized commercial-evidence observation contract.

This package accepts count/hash/scope evidence only. It is deliberately unable
to store raw recipient, sender, subject, body, message/thread, checkout, payment,
or customer identifiers.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
POLICY_PATH=ROOT/"commercial_evidence"/"COMMERCIAL_EVIDENCE_POLICY.json"
CURRENT_PATH=ROOT/"commercial_evidence"/"CURRENT_SANITIZED_OBSERVATION.json"


class CommercialEvidenceError(ValueError):
    pass


def req(ok:bool,msg:str)->None:
    if not ok:
        raise CommercialEvidenceError(msg)


def canon(value:Any)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)


def hashv(value:Any)->str:
    return "sha256:"+hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def policy()->dict[str,Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _time(value:str,name:str)->datetime:
    req(isinstance(value,str) and value.endswith("Z"),f"{name} must be UTC ISO-8601")
    try:
        return datetime.fromisoformat(value[:-1]+"+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise CommercialEvidenceError(f"{name} invalid") from exc


OBSERVATION_FIELDS={
    "schema_version","observation_id","captured_at","window_start","window_end",
    "source_kind","query_contract_id","coverage_scope","threads_observed",
    "threads_truncated","outbound_messages_observed","inbound_messages_observed",
    "threads_with_auto_response","threads_with_human_reply","authority_class",
    "evidence_state","private_payloads_persisted","raw_message_ids_persisted",
    "raw_thread_ids_persisted","recipient_identifiers_persisted","observation_hash",
}


def validate_observation(observation:dict[str,Any])->None:
    p=policy()
    req(isinstance(observation,dict) and set(observation)==OBSERVATION_FIELDS,"commercial observation fields changed")
    req(observation["schema_version"]=="1.0.0","commercial observation schema mismatch")
    req(observation["authority_class"]=="OBSERVE","commercial observation authority widened")
    req(observation["source_kind"] in p["allowed_source_kinds"],"commercial observation source kind invalid")
    req(observation["evidence_state"] in p["allowed_evidence_states"],"commercial observation evidence state invalid")
    req(
        isinstance(observation["query_contract_id"],str)
        and 1<=len(observation["query_contract_id"])<=160,
        "commercial query contract id invalid",
    )
    req(
        isinstance(observation["coverage_scope"],str)
        and 1<=len(observation["coverage_scope"])<=200,
        "commercial coverage scope invalid",
    )
    start=_time(observation["window_start"],"window_start")
    end=_time(observation["window_end"],"window_end")
    captured=_time(observation["captured_at"],"captured_at")
    req(start<=end<=captured,"commercial observation time window invalid")

    for key in (
        "threads_observed","threads_truncated","outbound_messages_observed",
        "inbound_messages_observed","threads_with_auto_response","threads_with_human_reply",
    ):
        req(type(observation[key]) is int and observation[key]>=0,f"{key} invalid")
    req(observation["threads_truncated"]<=observation["threads_observed"],"truncated thread count exceeds observed threads")
    req(observation["threads_with_auto_response"]<=observation["threads_observed"],"auto-response thread count exceeds observed threads")
    req(observation["threads_with_human_reply"]<=observation["threads_observed"],"human-reply thread count exceeds observed threads")

    for key in (
        "private_payloads_persisted","raw_message_ids_persisted",
        "raw_thread_ids_persisted","recipient_identifiers_persisted",
    ):
        req(observation[key] is False,f"commercial privacy boundary violated: {key}")

    # No private-looking mailbox or URL material belongs in this public contract.
    serialized=canon(observation).lower()
    req("@" not in serialized,"commercial observation contains mailbox-like data")
    req("http://" not in serialized and "https://" not in serialized,"commercial observation contains URL-like private source data")

    body={key:value for key,value in observation.items() if key not in {"observation_id","observation_hash"}}
    expected_hash=hashv(body)
    req(observation["observation_hash"]==expected_hash,"commercial observation hash mismatch")
    expected_id="CEOBS-"+expected_hash.split(":",1)[1][:20].upper()
    req(observation["observation_id"]==expected_id,"commercial observation id mismatch")


def load_current(path:Path|None=None)->dict[str,Any]:
    target=path or CURRENT_PATH
    observation=json.loads(target.read_text(encoding="utf-8"))
    validate_observation(observation)
    return observation


def project_current(observation:dict[str,Any],*,at:str)->dict[str,Any]:
    validate_observation(observation)
    now=_time(at,"projection at")
    captured=_time(observation["captured_at"],"captured_at")
    age_minutes=round(max(0.0,(now-captured).total_seconds()/60),1)
    max_age=float(policy()["max_observation_age_minutes"])
    fresh=age_minutes<=max_age

    if fresh and observation["source_kind"]=="CHATGPT_GMAIL_CONNECTOR_SANITIZED_OBSERVATION":
        reply_state=(
            "OBSERVED_HUMAN_REPLY_IN_SCOPE"
            if observation["threads_with_human_reply"]>0
            else "OBSERVED_NO_HUMAN_REPLY_IN_SCOPE"
        )
        auto_state=(
            "OBSERVED_AUTO_RESPONSE_IN_SCOPE"
            if observation["threads_with_auto_response"]>0
            else "OBSERVED_NO_AUTO_RESPONSE_IN_SCOPE"
        )
        evidence_status="CURRENT_SCOPE_OBSERVED"
    else:
        reply_state="UNKNOWN"
        auto_state="UNKNOWN"
        evidence_status="STALE_OR_UNAVAILABLE"

    return {
        "evidence_status":evidence_status,
        "live_external_evidence_feed":False,
        "observation_id":observation["observation_id"],
        "captured_at":observation["captured_at"],
        "observation_age_minutes":age_minutes,
        "max_observation_age_minutes":max_age,
        "fresh":fresh,
        "source_kind":observation["source_kind"],
        "query_contract_id":observation["query_contract_id"],
        "coverage_scope":observation["coverage_scope"],
        "evidence_state":observation["evidence_state"],
        "threads_observed":observation["threads_observed"],
        "threads_truncated":observation["threads_truncated"],
        "outbound_messages_observed":observation["outbound_messages_observed"],
        "inbound_messages_observed":observation["inbound_messages_observed"],
        "threads_with_human_reply":observation["threads_with_human_reply"],
        "threads_with_auto_response":observation["threads_with_auto_response"],
        "current_reply_state":reply_state,
        "current_auto_response_state":auto_state,
        "current_payment_state":"UNKNOWN",
        "scope_note":(
            "Reply observations apply only to the explicit Gmail query contract and observation window. "
            "They do not establish the state of historical outreach outside that scope."
        ),
        "authority_granted":False,
        "definitive_outcome_recorded":False,
    }


def main()->None:
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",default=str(CURRENT_PATH))
    ap.add_argument("--at",required=True)
    args=ap.parse_args()
    print(json.dumps(project_current(load_current(Path(args.input)),at=args.at),sort_keys=True))


if __name__=="__main__":
    main()
