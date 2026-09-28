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
    req(p["model_calls_allowed"]==0 and p["downstream_writes_allowed"]==0 and p["external_actions_allowed"]==0,"deterministic runtime authority widened")
    ma=p["governed_model_analysis"]
    req(ma["enabled"] is True and ma["deterministic_core_remains_authoritative"] is True,"governed model analysis disabled/misconfigured")
    req(ma["modes"]==["daily","weekly"],"model analysis modes changed")
    req(ma["daily"]["max_calls"]==1 and ma["daily"]["task_kind"]=="CROSS_PROJECT_SYNTHESIS" and ma["daily"]["expected_tier"]==2,"daily model analysis contract drifted")
    req(ma["weekly"]["max_calls"]==1 and ma["weekly"]["task_kind"]=="HIGH_IMPACT_AUDIT" and ma["weekly"]["expected_tier"]==3,"weekly model analysis contract drifted")
    req(ma["weekly"]["requires_independent_adversarial"] is True and ma["weekly"]["builder_independence_group"]=="openai-terra","weekly independent review boundary missing")
    b=p["budgets"]
    req(0<b["max_repositories_per_cycle"]<=8,"repo budget invalid")
    req(0<b["max_api_requests_per_cycle"]<=40,"API budget invalid")
    req(0<b["max_runtime_seconds"]<=240,"time budget invalid")
    req(0<b["max_state_restore_seconds"]<=45,"state restore time budget invalid")
    req(b["max_state_restore_seconds"]<b["max_runtime_seconds"],"state restore must not consume the runtime budget")
    req(0<=b["retry_limit"]<=2,"retry budget invalid")
    req(p["state_persistence"]["mode"]=="GITHUB_ACTIONS_ARTIFACT","state persistence changed")
    req(p["state_persistence"]["sanitized_only"] is True,"runtime state must remain sanitized")
    integrity=p["state_integrity"]
    req(integrity["max_recent_cycles"]==20,"runtime history bound drifted")
    req(integrity["require_canonical_cycle_receipt_hash"] is True,"runtime receipt hashing disabled")
    req(integrity["require_cycle_id_state_binding"] is True,"runtime cycle identity no longer bound to state")
    req(integrity["reject_cycle_replay"] is True,"runtime cycle replay protection disabled")
    req(integrity["require_monotonic_history"] is True,"runtime history chronology protection disabled")
    req(integrity["artifact_requires_companion_cycle_receipt"] is True,"runtime artifact companion receipt no longer required")
    req(integrity["artifact_state_receipt_binding"] is True,"runtime artifact state/receipt binding disabled")
    state_code=(ROOT/"runtime/state.py").read_text()
    for token in ["validate_cycle_receipt","cycle_id_for","cycle receipt replay detected","runtime freshness does not match retained history"]:
        req(token in state_code,f"runtime state integrity implementation missing {token}")
    artifact_code=(ROOT/"runtime/artifact_state.py").read_text()
    for token in ["validate_runtime_artifact_bundle","cycle_receipt.json","state/receipt binding mismatch"]:
        req(token in artifact_code,f"runtime artifact integrity implementation missing {token}")
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
                     "PORTFOLIO_MODEL_API_KEY","runtime.model_analysis","actions/upload-artifact@v4","retention-days: 30",
                     "(inputs.mode == 'observe' || inputs.mode == 'sync') && 'portfolio-runtime-nonpaid-state-writer'",
                     "cancel-in-progress: false",
                     "workload_control.workload_gate preflight","format('portfolio-runtime-{0}', inputs.mode)",
                     "--provider-health-output runtime/out/provider_health.json",
                     '--job-id "runtime-${RUNTIME_MODE}"',
                     "Report governed no-work outcome","steps.admission.outputs.decision_status","GITHUB_STEP_SUMMARY"]:
        req(required in worker,f"runtime worker missing {required}")
    req("Fail closed when cost gate blocks" not in worker and "run: exit 3" not in worker,
        "expected cost denial still creates a false runtime failure")
    forbidden=["contents: write","pull-requests: write","issues: write","deployments: write",
               "id-token: write","git push","gh pr","openai","anthropic"]
    combined="\n".join(texts.values()).lower()
    for value in forbidden: req(value.lower() not in combined,f"forbidden workflow capability: {value}")
    req("17 * * * *" in texts[names[2]],"hourly schedule missing")
    req("37 9 * * *" in texts[names[3]],"daily schedule missing")
    req("runtime/TRIGGER_DAILY_REASONING" in texts[names[3]] and "push:" in texts[names[3]],"daily manual kick path missing")
    req("17 10 * * 1" in texts[names[4]],"weekly schedule missing")
    req("PORTFOLIO_MODEL_API_KEY" in texts[names[3]] and "portfolio_model_api_key" in texts[names[3]],"daily model secret handoff missing")
    req("PORTFOLIO_MODEL_API_KEY" in texts[names[4]] and "portfolio_model_api_key" in texts[names[4]],"weekly model secret handoff missing")
    req("repository_dispatch:" in texts[names[1]] and "push:" in texts[names[1]],"event triggers missing")
    req("paths-ignore:" in texts[names[1]] and "runtime/TRIGGER_DAILY_REASONING" in texts[names[1]],
        "daily reasoning trigger must not also launch event-observe")
    req("group: runtime-event-observe-${{ github.event_name }}-${{ github.ref }}" in texts[names[1]],"runtime event-observe push coalescing group missing")
    req("cancel-in-progress: ${{ github.event_name == 'push' }}" in texts[names[1]],"runtime event-observe push coalescing policy missing")
    for isolated in [
      "value_proof/TRIGGER_END_TO_END_PROOF",
      "value_proof/TRIGGER_VERIFIED_FEEDBACK_BOOTSTRAP",
      "learning/TRIGGER_VERIFIED_OUTCOME_BOOTSTRAP",
      ".github/workflows/model-value-proof.yml",
      ".github/workflows/verified-feedback-bootstrap.yml",
      ".github/workflows/continuous-learning-bootstrap.yml",
      "operations/TRIGGER_WORKFLOW_LIVENESS",
      ".github/workflows/portfolio-cost-watchdog.yml",
    ]:
        req(isolated in texts[names[1]],f"one-shot governed trigger/workflow is not isolated from event-observe: {isolated}")
    return {"workflows":5,"model_calls":0,"governed_daily_model_calls":1,"governed_weekly_model_calls":1,
            "downstream_writes":0,"external_actions":0,
            "runtime_receipt_integrity":True,"runtime_artifact_companion_binding":True,
            "push_observation_coalescing":True,"mode_isolated_cost_budgets":True,
            "max_api_requests":b["max_api_requests_per_cycle"],"max_runtime_seconds":b["max_runtime_seconds"]}

if __name__=="__main__":
    print("portfolio-brain Step 8 runtime: PASS",json.dumps(validate_runtime(),sort_keys=True))
