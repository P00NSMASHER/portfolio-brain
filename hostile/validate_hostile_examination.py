#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class HostileValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise HostileValidationError(msg)
def validate_hostile():
    matrix=json.loads((ROOT/"hostile/ATTACK_MATRIX.json").read_text())
    req(matrix["schema_version"]=="1.0.0","attack matrix schema mismatch")
    rows=matrix["scenarios"];req(len(rows)==17,"hostile scenario coverage changed")
    req(len({r["scenario_id"] for r in rows})==17,"duplicate hostile scenario id")
    allowed={"BLOCKED_EXISTING","FIXED_STEP23"}
    req(all(r["status"] in allowed for r in rows),"unresolved hostile finding remains")
    fixed=[r for r in rows if r["status"]=="FIXED_STEP23"]
    req({r["scenario_id"] for r in fixed}=={"HST-003","HST-004","HST-005","HST-006"},"Step 23 fix set changed")
    notif=json.loads((ROOT/"notifications/NOTIFICATION_POLICY.json").read_text())
    req(notif["authority_class"]=="NONE","notification authority widened")
    agents=json.loads((ROOT/"agents/AGENT_POLICY.json").read_text())
    req("LIVE_MARKET_TRADING" in agents["global_prohibitions"],"trading prohibition missing")
    req("CUSTOMER_COMMUNICATION" not in agents["global_prohibitions"],"obsolete customer communication prohibition remains")
    experiments=json.loads((ROOT/"experiments/EXPERIMENT_POLICY.json").read_text())
    req(experiments["automatic_external_act"] is True,"bounded external ACT path is not enabled")
    actions=json.loads((ROOT/"action_engine/ACTION_POLICY.json").read_text())
    req(actions["mode"]=="CHATGPT_GMAIL_CONNECTOR_GATEWAY" and actions["execution_provider"]=="CHATGPT_GMAIL_CONNECTOR","Gmail gateway mode/provider mismatch")
    req(actions["gmail_account_ref"]=="PRIMARY_GMAIL_CONNECTOR","Gmail gateway account drifted")
    req(set(actions["allowed_actions"])=={"CUSTOMER_EMAIL"},"action gateway widened beyond approved channel")
    req(set(actions["allowed_project_ids"])=={"PRJ-001","PRJ-002","PRJ-003","PRJ-004","PRJ-005","PRJ-006"},"action project allowlist drifted")
    req({"MOVE_MONEY","PAYMENT_OR_PURCHASE","LIVE_MARKET_TRADING","BROKERAGE_ORDER","PRIVATE_INFORMATION_DISCLOSURE","CONSEQUENTIAL_CHILD_FACING_CHANGE"}<=set(actions["prohibited_action_types"]),"high-risk action boundary missing")
    education=json.loads((ROOT/"action_engine/EDUCATION_VALIDATION_POLICY.json").read_text())
    req(set(education["allowed_project_ids"])=={"PRJ-005","PRJ-006"},"education validation project scope drifted")
    req(education["required_target_classification"]=="VERIFIED_ADULT_STAKEHOLDER","education adult target gate missing")
    req(education["direct_minor_contact_allowed"] is False and education["child_data_collection_allowed"] is False and education["consequential_child_facing_change_allowed"] is False,"education child-safety boundary weakened")
    executor=(ROOT/"action_engine/action_executor.py").read_text()
    req("DUPLICATE_SUPPRESSED" in executor and "RECIPIENT_DAILY_LIMIT" in executor and "GMAIL_GATEWAY_LEDGER" in executor,"Gmail idempotency/rate/ledger defense missing")
    req("smtplib" not in executor and "SMTP_" not in executor,"obsolete SMTP transport remains")
    req(not (ROOT/".github/workflows/portfolio-action-worker.yml").exists(),"obsolete GitHub SMTP action worker remains")
    factory=json.loads((ROOT/"software_factory/FACTORY_POLICY.json").read_text())
    req("MERGE_PR" in factory["absent_operations"] and "DEPLOY" in factory["absent_operations"],"factory deployment/merge surface widened")
    hunter=(ROOT/"hunting/autonomous_hunter.py").read_text()
    uncertainty=(ROOT/"uncertainty/highest_value_uncertainty.py").read_text()
    req('edge["verification_state"]!="VERIFIED"' in hunter,"Hunter unverified-capability defense missing")
    req('e["verification_state"]=="VERIFIED"' in uncertainty,"uncertainty unverified-capability defense missing")
    graph=(ROOT/"graph/universal_graph.py").read_text()
    req("_has_verification_anchor" in graph,"graph verification-anchor defense missing")
    sink=(ROOT/"notifications/github_sink.py").read_text()
    req("_command_data" in sink and "_safe" in sink,"workflow-command injection defense missing")
    cost=(ROOT/"cost_governor/cost_governor.py").read_text()
    req("retry group must bind" in cost,"retry identity binding defense missing")
    return {"scenarios":17,"blocked_existing":13,"fixed_step23":4,"unresolved":0,"authority_change":"NONE"}
if __name__=="__main__":print("portfolio-brain Step 23 hostile examination: PASS",json.dumps(validate_hostile(),sort_keys=True))
