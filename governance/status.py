#!/usr/bin/env python3
"""Compatibility entrypoint for the single config-derived architecture status.

The authoritative builder/validator lives in operations.validate_architecture_status.
Keeping this module as a delegating wrapper prevents a second status schema from
silently drifting away from the checked-in operations/ARCHITECTURE_STATUS.json.
"""
from __future__ import annotations
import argparse, json
from operations.validate_architecture_status import build_status, validate_status

def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    status=validate_status() if args.check else build_status()
    print(json.dumps(status,sort_keys=True))

if __name__=="__main__":
    main()
