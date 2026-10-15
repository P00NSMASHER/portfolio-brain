"""Learn from independently verified repair results, not imagined customers.

Original source bytes, exact PR checks and independent gate identities are
replayed through the real delivery validator. Only technical source repair
results affect a narrow recipe priority. No revenue or human hours inferred.
"""
from __future__ import annotations

from brain.core import require
from brain.repair_delivery import evaluate_delivery
from brain.repair_patch_executor import REPOSITORIES, SHA

MIN_RESOLVED = 3
MAX_EPISODES = 24
RECIPE = "READONLY_CI_CHECKOUT_HARDENING"
THEMES = {
    "P00NSMASHER/github-value-hunt-ledger": "SECURITY_CONTINUITY",
    "P00NSMASHER/x402-product-factory": "AUTOMATION_RELIABILITY",
}


def _episode(row):
    require(type(row) is dict and set(row) == {
        "patch", "original_source", "pr", "file_hashes",
        "candidate_checks", "main_sha", "main_checks",
    } and type(row["patch"]) is dict
            and type(row["original_source"]) is str
            and type(row["pr"]) is dict
            and type(row["file_hashes"]) is dict
            and type(row["candidate_checks"]) is dict,
            "REPAIR_LEARNING_SOURCE_EVIDENCE_INVALID")
    patch = row["patch"]
    require(patch.get("repository") in THEMES
            and type(patch.get("source_head_sha")) is str
            and SHA.fullmatch(patch["source_head_sha"])
            and type(patch.get("original_sha256")) is str
            and type(row["pr"].get("number")) is int,
            "REPAIR_LEARNING_SCOPE_OR_IDENTITY_INVALID")
    decision = evaluate_delivery(
        patch, row["pr"], row["file_hashes"],
        row["candidate_checks"],
        original_source_bytes=row["original_source"].encode("utf-8"),
        current_main_sha=row["main_sha"],
        main_checks=row["main_checks"],
    )
    state = "UNRESOLVED"
    if decision["technical_main_verified"]:
        state = "TECHNICAL_MAIN_PASS"
    elif (row["pr"]["state"] == "closed"
          and row["pr"]["merged"] is False
          and decision["source_ci_status"] ==
              "ADVERSE_EXACT_HEAD_CHECKS_NEED_REPAIR"):
        state = "VERIFIED_REPAIR_CI_FAILED"
    # Closed unmerged because a PR was duplicated, held, or superseded is
    # not a proved technical failure; unknown remains censored/unresolved.
    return {
        "repository": patch["repository"],
        "pr_number": row["pr"]["number"],
        "candidate_sha": row["pr"]["head"]["sha"],
        "original_source_sha256": patch["original_sha256"],
        "repair_kind": RECIPE,
        "state": state,
        "independent_gate": decision["independent_gate_verified"],
        "customer_value": None,
    }


def learn_from_repairs(episodes):
    require(type(episodes) is list and len(episodes) <= MAX_EPISODES,
            "REPAIR_LEARNING_SAMPLE_LIMIT")
    seen, rows = set(), []
    for episode in episodes:
        row = _episode(episode)
        key = (row["repository"], row["pr_number"])
        require(key not in seen, "REPAIR_LEARNING_DUPLICATE_PR_OUTCOME")
        seen.add(key)
        rows.append(row)
    result = {}
    for repo, theme in THEMES.items():
        group = [r for r in rows if r["repository"] == repo]
        passed = sum(r["state"] == "TECHNICAL_MAIN_PASS" for r in group)
        failed = sum(r["state"] == "VERIFIED_REPAIR_CI_FAILED" for r in group)
        pending = len(group) - passed - failed
        resolved = passed + failed
        distinct_source = len({
            r["original_source_sha256"] for r in group
            if r["state"] != "UNRESOLVED"
        })
        eligible = resolved >= MIN_RESOLVED and distinct_source >= MIN_RESOLVED
        if eligible:
            # Descriptive routing heuristic, NOT a causal probability model.
            delta = round(12 * (passed / resolved - 0.55))
            delta = max(-8, min(5, delta))
        else:
            delta = 0
        result[repo] = {
            "recipe": RECIPE, "relevant_theme": theme,
            "observed": len(group),
            "resolved_independent_technical_samples": resolved,
            "distinct_resolved_source_revisions": distinct_source,
            "technical_main_passes": passed,
            "failed_actual_ci_attempts": failed,
            "unresolved_not_treated_as_failures": pending,
            "priority_adjustment": delta,
            "priority_adjustment_enabled": eligible,
            "actual_customer_value": None,
            "human_hours_saved": None,
            "verified_revenue": None,
        }
    return {
        "schema_version": 1,
        "scope": "SOURCE_REPLAYED_TECHNICAL_REPAIR_OUTCOMES_ONLY",
        "total_original_episodes": len(rows),
        "projects": result,
        "source_replay_passed": True,
        "independent_gate_not_self_certified": True,
        "business_effect_measured": False,
        "verified_revenue": None,
        "authority_to_contact_pay_merge_or_deploy": False,
        "synthetic_success_credit": 0,
    }



def main(argv=None):
    """Consume independent technical outcomes in private, never trade/send."""
    import argparse
    import json
    from pathlib import Path
    from brain.repair_followthrough_cli import _safe_json
    from brain.render import write_report
    parser = argparse.ArgumentParser(description="Source-verified technical repair learning")
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--project-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = _safe_json(args.episodes)
    knowledge = learn_from_repairs(rows)
    document = {"learning": knowledge}
    if args.project_report:
        from brain.repair_autonomy import repair_batch
        project = _safe_json(args.project_report)
        rotation = (project.get("operation") or {}).get("ci_rotation_sequence", 0)
        action_plan = repair_batch(
            project, cycle_index=rotation, outcome_episodes=rows,
        )
        document["prioritized_owner_repair_actions"] = action_plan
    document["production_release_authority"] = False
    document["verified_business_revenue"] = None
    write_report(document, args.output)
    print(json.dumps({
        "verified_technical_source_samples": sum(
            row["resolved_independent_technical_samples"]
            for row in knowledge["projects"].values()
        ),
        "real_customer_value": None,
        "authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
