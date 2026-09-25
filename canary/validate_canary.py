#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,tempfile
from pathlib import Path
from canary.autonomous_learning_canary import execute_canary

class CanaryValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise CanaryValidationError(msg)

def validate_canary(output_dir=None):
    if output_dir is None:
        td=tempfile.TemporaryDirectory();out=Path(td.name)/"out"
    else:
        td=None;out=Path(output_dir)
    try:
        r=execute_canary(out)
        req(r["status"]=="PASS","canary did not pass")
        req(r["no_interactive_chatgpt_dependency"] is True,"interactive ChatGPT dependency present")
        req(r["network_mode"]=="LOCAL_CURSOR_MIRROR_ONLY","canary network mode widened")
        first=r["first_cycle"];cont=r["continuation"]
        req(first["runtime_status"]=="PASS" and first["runtime_api_reads"]<=8,"runtime canary boundary failed")
        req(first["scheduler_selected_count"]==3 and first["scheduler_selected_work_types"]==["HUNT","INTEGRATION","RESEARCH"],"first scheduler selection drifted")
        req(first["scheduler_blocked_approval_count"]==6,"human approval queue drifted")
        req(first["paid_cost_usd"]==0.0 and first["model_calls"]==0 and r["paid_model_api_used"] is False,"paid/model usage occurred")
        req(first["learning_eligible_records"]==0,"unverified learning promotion occurred")
        req(cont["scheduler_selected_count"]==0 and cont["scheduler_suppressed_duplicates"]>=3,"duplicate scheduler work was not suppressed")
        req(cont["cost_status"]=="DUPLICATE_SUPPRESSED","cost continuation was not idempotent")
        req(cont["notifications_emitted"]==0 and cont["notification_suppressed"]>=2,"notification continuation was not suppressed")
        req(cont["learning_state_hash_unchanged"] is True,"learning rebuild changed without new evidence")
        req(r["authority_violations"]==0 and r["forbidden_actions_attempted"]==0,"canary authority boundary violated")
        req(all(r["state_restoration"].values()),"durable state restoration incomplete")
        return {
          "status":"PASS","runtime_reads":first["runtime_api_reads"],
          "first_selected_work":first["scheduler_selected_count"],
          "continuation_selected_work":cont["scheduler_selected_count"],
          "suppressed_duplicates":cont["scheduler_suppressed_duplicates"],
          "paid_cost_usd":first["paid_cost_usd"],"model_calls":first["model_calls"],
          "authority_violations":r["authority_violations"],"learning_promotions":first["learning_eligible_records"],
          "receipt_hash":r["receipt_hash"]
        }
    finally:
        if td is not None:td.cleanup()

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output-dir",default=None);a=ap.parse_args()
    print("portfolio-brain Step 24 autonomous learning canary: PASS",json.dumps(validate_canary(a.output_dir),sort_keys=True))
if __name__=="__main__":main()
