#!/usr/bin/env python3
"""Static + machine-readable conformance validator for Step 8 runtime."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class RuntimeValidationError(ValueError): pass
def req(ok,msg):
    if not ok: raise RuntimeValidationError(msg)
def load(p): return json.loads((ROOT/p).read_text())

def validate_runtime()->dict:
    p=load("runtime/RUNTIME_POLICY.json"); k=load("runtime/KILL_SWITCH.json")
    req(p["schema_version"]=="1.0.0" and p["authority_class"]=="OBSERVE","runtime authority invalid")
    req(p["model_calls_allowed"]==0 and p["downstream_writes_allowed"]==0 and p["external_actions_allowed"]==0,"runtime authority widened")
    b=p["budgets"]
    req(0<b["max_repositories_per_cycle"]<=8,"repo budget invalid")
    req(0<b["max_api_requests_per_cycle"]<=40,"API budget invalid")
    req(0<b["max_runtime_seconds"]<=240,"time budget invalid")
    req(0<=b["retry_limit"]<=2,"retry budget invalid")
    req(p["state_persistence"]["mode"]=="GITHUB_ACTIONS_ARTIFACT","state persistence changed")
    req(p["state_persistence"]["sanitized_only"] is True,"runtime state must remain sanitized")
    req(k["disabled"] is False,"checked-in runtime kill switch unexpectedly active")

    names=[
      ".github/workflows/runtime-worker.yml",
      ".github/workflows/runtime-event-observe.yml",
      ".github/workflows/runtime-hourly-sync.yml",
      ".github/workflows/runtime-daily-learning.yml",
      ".github/workflows/runtime-weekly-synthesis.yml",
    ]
    texts={n:(ROOT/n).read_text() for n in names}
    worker=texts[names[0]]
    for required in ["contents: read","actions: read","timeout-minutes: 5","PORTFOLIO_RUNTIME_DISABLED",
                     "actions/upload-artifact@v4","retention-days: 30","cancel-in-progress: false"]:
        req(required in worker,f"runtime worker missing {required}")
    forbidden=["contents: write","pull-requests: write","issues: write","deployments: write",
               "id-token: write","git push","gh pr","openai","anthropic"]
    combined="\n".join(texts.values()).lower()
    for value in forbidden: req(value.lower() not in combined,f"forbidden workflow capability: {value}")
    req("17 * * * *" in texts[names[2]],"hourly schedule missing")
    req("37 9 * * *" in texts[names[3]],"daily schedule missing")
    req("17 10 * * 1" in texts[names[4]],"weekly schedule missing")
    req("repository_dispatch:" in texts[names[1]] and "push:" in texts[names[1]],"event triggers missing")
    return {"workflows":5,"model_calls":0,"downstream_writes":0,"external_actions":0,
            "max_api_requests":b["max_api_requests_per_cycle"],"max_runtime_seconds":b["max_runtime_seconds"]}

if __name__=="__main__":
    print("portfolio-brain Step 8 runtime: PASS",json.dumps(validate_runtime(),sort_keys=True))
