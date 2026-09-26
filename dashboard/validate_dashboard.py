#!/usr/bin/env python3
import json
from pathlib import Path
from dashboard.executive_dashboard import build_dashboard_snapshot,render_markdown
ROOT=Path(__file__).resolve().parents[1]
class DashboardValidationError(ValueError):pass
def req(x,m):
    if not x:raise DashboardValidationError(m)
def validate_dashboard():
    s=build_dashboard_snapshot();md=render_markdown(s)
    req(s["authority_class"]=="OBSERVE","dashboard authority widened")
    req(s["project_count"]==12 and len(s["projects"])==12,"dashboard project coverage incomplete")
    req(3<=s["portfolio"]["pending_autonomous_work_count"]<=8,"current autonomous queue outside optimized bounds")
    req(s["portfolio"]["blocked_action_count"]==0,"adult-only education validation remains blocked")
    req(s["portfolio"]["learning_observation_count"]==0,"dashboard invented learning observations")
    req(s["portfolio"]["verified_transfer_outcome_count"]==0,"dashboard invented transfer outcomes")
    req(s["portfolio"]["checked_in_measured_model_cost_usd"]==0.0,"dashboard invented model cost")
    req(s["portfolio"]["estimated_value_presented_as_measured"] is False,"estimate/measurement boundary weakened")
    req(all(p["measured_outcome_status"]=="NONE_IN_CHECKED_IN_VERIFIED_LEDGER" for p in s["projects"]),"dashboard invented measured project outcome")
    req(all(p["health_basis"]=="EVIDENCE_COVERAGE_NOT_SUBJECTIVE_SCORE" for p in s["projects"]),"subjective health scoring introduced")
    req("MEASURED RESULT is distinct from ESTIMATED VALUE" in md,"measurement labeling missing")
    req("No dashboard field grants authority or executes work." in md,"authority disclaimer missing")
    return {"projects":12,"pending_work":s["portfolio"]["pending_autonomous_work_count"],"blocked_actions":0,"measured_outcomes":0,"measured_model_cost_usd":0.0,"authority":"OBSERVE"}
if __name__=="__main__":print("portfolio-brain Step 21 executive dashboard: PASS",json.dumps(validate_dashboard(),sort_keys=True))
