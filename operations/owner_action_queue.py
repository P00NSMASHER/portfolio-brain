#!/usr/bin/env python3
"""Render the current owner-action checkpoint queue from external-value evidence."""
from __future__ import annotations
import json
from operations.value_loop import build_value_loop_snapshot, digest


def build_owner_action_queue() -> dict:
    snapshot=build_value_loop_snapshot()
    actions=snapshot["owner_action_queue"]
    body={
        "schema_version":"1.0.0",
        "queue_id":"portfolio-owner-action-queue-v1",
        "status":"ACTION_REQUIRED" if actions else "CLEAR",
        "actions":actions,
        "resume_rule":"Recompute from source evidence; an action clears only when its resume evidence is present.",
        "authority_granted":False,
    }
    return {**body,"queue_hash":digest(body)}


if __name__=="__main__":
    print(json.dumps(build_owner_action_queue(),sort_keys=True))
