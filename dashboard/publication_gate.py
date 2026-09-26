#!/usr/bin/env python3
"""Suppress command-center publication when the material snapshot is unchanged."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any

VOLATILE={"snapshot_hash","generated_at","age_minutes","artifact_id","source_run_id","source_head_sha","artifact_created_at","artifact_expires_at"}

def material(value:Any)->Any:
    if isinstance(value,dict):
        return {k:material(v) for k,v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value,list):return [material(x) for x in value]
    return value

def fingerprint(value:dict[str,Any])->str:
    raw=json.dumps(material(value),sort_keys=True,separators=(",",":")).encode()
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def should_publish(current:dict[str,Any],previous:dict[str,Any]|None)->bool:
    return previous is None or fingerprint(current)!=fingerprint(previous)

def main()->None:
    ap=argparse.ArgumentParser();ap.add_argument("--current",required=True);ap.add_argument("--previous")
    a=ap.parse_args();current=json.loads(Path(a.current).read_text())
    previous=None
    if a.previous and Path(a.previous).exists():
        try:previous=json.loads(Path(a.previous).read_text())
        except Exception:previous=None
    print("true" if should_publish(current,previous) else "false")

if __name__=="__main__":main()
