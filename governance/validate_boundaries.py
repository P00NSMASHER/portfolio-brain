#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from governance.authority import action_boundary,validate_boundaries
ROOT=Path(__file__).resolve().parents[1]
class GovernanceValidationError(ValueError):pass
def req(ok,msg):
 if not ok:raise GovernanceValidationError(msg)
def validate():
 c=validate_boundaries();action=json.loads((ROOT/"action_engine"/"ACTION_POLICY.json").read_text());op=json.loads((ROOT/"operations"/"OPERATING_MODE_POLICY.json").read_text());n=json.loads((ROOT/"notifications"/"NOTIFICATION_POLICY.json").read_text())
 req(action_boundary("customer_email_gmail")["decision"]=="HUMAN_APPROVAL_REQUIRED","Gmail boundary weakened")
 req(action.get("human_approval_required") is True and action.get("autonomous_execution_allowed") is False,"action policy still permits autonomous communication")
 req(op["interactive_chatgpt_runtime_dependency"] is False,"interactive ChatGPT became runtime dependency")
 d=op.get("core_autonomy_dependencies",{});req(d.get("gmail") is False and d.get("interactive_chatgpt") is False,"core autonomy connector dependency widened")
 req(n.get("evidence_semantics")=="ALERT_ONLY_NO_VERIFICATION_CREDIT" and n.get("verification_credit")==[],"notification semantics missing")
 return c|{"gmail_human_gated":1,"notification_alert_only":1}
if __name__=="__main__":print("portfolio-brain governance boundaries: PASS",json.dumps(validate(),sort_keys=True))
