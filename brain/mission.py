"""Evidence-first priorities for every registered project; no new authority."""
from brain.core import require

MISSION = {
    "objective": "AUTONOMOUS_RESEARCH_UPGRADES_AND_REPAIRS",
    "primary_outcomes": ["verified_repairs", "useful_upgrades_delivered",
                         "failure_recurrence", "quality", "user_intervention"],
    "revenue_role": "OPTIONAL_PROJECT_CONTEXT_NOT_GLOBAL_PRIORITY",
    "completion_rule": "INDEPENDENT_CHECKS_AND_ACTUAL_DELIVERY_VERIFICATION",
    "authority": "EXISTING_PROJECT_OWNERS_AND_RELEASE_GATES_ONLY",
}


def mission_priorities(projects, *, cycle=0):
    """Rank observed failures first, uncertainty next, then scoped upgrades.

    Fair rotation breaks equal-evidence ties; it never outranks an incident.
    This is a work plan, not proof of a defect, delivered fix or runtime access.
    """
    require(type(cycle) is int and 0 <= cycle < 2**63, "MISSION_CYCLE_INVALID")
    require(type(projects) is list and 0 < len(projects) <= 16,
            "MISSION_PROJECT_BOUND")
    require(len({p["id"] for p in projects}) == len(projects),
            "MISSION_DUPLICATE_PROJECT")
    ordered = sorted(projects, key=lambda p: p["id"])
    offset = cycle % len(ordered)
    fairness = {p["id"]: i for i, p in enumerate(ordered[offset:] + ordered[:offset])}
    ranked = []
    for project in projects:
        state = project["source_check_state"]
        if state == "ADVERSE_CHECKS_OBSERVED":
            tier, action = 0, "DIAGNOSE_REPRODUCE_AND_REPAIR"
        elif state != "NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL":
            tier, action = 1, "VERIFY_CURRENT_SOURCE_AND_RUNTIME"
        else:
            tier, action = 2, "RESEARCH_AND_TEST_USEFUL_UPGRADE"
        ranked.append({
            "project_id": project["id"], "repository": project["repository"],
            "observed_source_sha": project["repository_revision"],
            "source_check_state": state, "priority_tier": tier,
            "next_operation": action, "improvement_focus": project["improvement_focus"],
            "success_metric": project["success_metric"],
            "baseline_value": project["baseline_value"],
            "measured_result": project["measured_result"],
            "delivered_improvement_verified": False,
            "merge_or_deployment_authority": False,
        })
    ranked.sort(key=lambda p: (p["priority_tier"], fairness[p["project_id"]]))
    return ranked
