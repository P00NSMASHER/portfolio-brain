"""Source-pinned, read-only rollback decision helper for protected releases.

Never writes GitHub refs, changes secrets, force-pushes, touches SQLite,
schedules work, or declares a revert accepted. Inputs are observation shapes
that MUST be independently authenticated before a governed code-review PR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

REPO = "P00NSMASHER/portfolio-brain"
RULESET_ID = 24182301
CHECKS = frozenset({("validate", 15368), ("portfolio-phase1-gate", 5121826)})
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_JSON = 131072
ADVERSE = frozenset(("failure", "cancelled", "timed_out"))
AUTOMATIC_EVENTS = frozenset(("schedule", "workflow_dispatch"))
ALLOWED_ROLLBACK_PATHS = frozenset((
    ".github/workflows/v9-guarded-native-automerge.yml",
    "brain/v9/guarded_merge.py",
    "brain/v9/guarded_merge_runner.py",
    "brain/validate.py",
    "docs/genesis/GUARDED_NATIVE_AUTOMERGE.md",
    "tests/test_brain_v9_guarded_merge.py",
))


class RevertReviewHold(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise RevertReviewHold(reason)


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _pairs(rows):
    output = {}
    for k, v in rows:
        require(k not in output, "DUPLICATE_EVIDENCE_KEY")
        output[k] = v
    return output


def read_input(path):
    p = Path(path)
    require(p.is_file() and p.stat().st_size <= MAX_JSON,
            "EVIDENCE_FILE_MISSING_OR_OVERSIZED")
    try:
        return json.loads(p.read_bytes(), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise RevertReviewHold("EVIDENCE_JSON_INVALID") from exc


def inspect(snapshot, incident):
    """Prepare or hold a non-executable rollback review request.

    Never infer incident authenticity from the mere presence of a user field:
    a separate provider-authorized reviewer must authenticate each original
    run/job/artifact and current protection at execution time. No output
    authorizes any mutation. Any unknown provider write blocks even planning.
    """
    require(type(snapshot) is dict and type(incident) is dict,
            "EVIDENCE_OBJECTS_REQUIRED")
    require(snapshot.get("repository") == REPO
            and snapshot.get("ruleset_id") == RULESET_ID
            and snapshot.get("protected_main") is True
            and snapshot.get("ruleset_enforcement") == "active"
            and type(snapshot.get("bypass_actors")) is list
            and snapshot["bypass_actors"] == [],
            "PROTECTED_REPOSITORY_OR_RULESET_MISMATCH")
    live = snapshot.get("main_sha")
    parent = snapshot.get("main_first_parent_sha")
    state = snapshot.get("state_branch_sha")
    require(_sha(live) and _sha(parent) and _sha(state)
            and parent != live, "IMMUTABLE_PARENT_OR_STATE_UNKNOWN")
    checks = snapshot.get("required_checks")
    require(type(checks) is list and len(checks) <= 12
            and all(type(x) is dict and
                    type(x.get("name")) is str and type(x.get("app_id")) is int
                    for x in checks),
            "INDEPENDENT_REQUIRED_CHECK_ISSUERS_UNKNOWN")
    issuers = {(x["name"], x["app_id"]) for x in checks}
    require(CHECKS <= issuers, "REQUIRED_CHECKS_NOT_AUTHENTICATED")
    changed = snapshot.get("release_changed_files")
    require(type(changed) is list and 0 < len(changed) <= 12
            and all(type(path) is str and path in ALLOWED_ROLLBACK_PATHS
                    for path in changed) and len(set(changed)) == len(changed),
            "REVERT_SCOPE_NOT_REVIEWED")
    require(incident.get("source_sha") == live
            and incident.get("workflow") == "brain-cycle-v2"
            and incident.get("event") in AUTOMATIC_EVENTS
            and type(incident.get("run_id")) is int
            and 0 < incident["run_id"] < 10**16
            and type(incident.get("attempt")) is int
            and incident["attempt"] == 1,
            "ORIGINAL_SOURCE_OR_RUN_NOT_VERIFIED")

    conclusion = incident.get("conclusion")
    require(conclusion in ADVERSE | {"success"},
            "UNKNOWN_ORIGINAL_RUN_CONCLUSION")
    job_conclusion = incident.get("monitor_conclusion")
    require(job_conclusion == conclusion,
            "ORIGINAL_RUN_JOB_CONCLUSION_MISMATCH")
    origin = incident.get("origin")
    require(origin in ("GITHUB_NATIVE_SCHEDULE", "CLOUDFLARE_SIGNED"),
            "ORIGINAL_AUTOMATIC_ORIGIN_UNKNOWN")
    require((incident["event"] == "schedule" and origin == "GITHUB_NATIVE_SCHEDULE")
            or (incident["event"] == "workflow_dispatch"
                and origin == "CLOUDFLARE_SIGNED"),
            "AUTOMATIC_ORIGIN_EVENT_CONFLICT")
    require(incident.get("provider_write_uncertain") is False,
            "EXTERNAL_WRITE_UNCERTAIN_STOP")

    if conclusion == "success":
        decision = "HOLD_NO_CONFIRMED_ADVERSE_AUTOMATIC_CORE"
        candidate = False
    else:
        decision = "PREPARE_PROTECTED_REVERT_PR_FOR_INDEPENDENT_REVIEW_ONLY"
        candidate = True

    payload = {
        "schema_version": 1,
        "kind": "ADVISORY_UNAUTHENTICATED_PROVIDER_SHAPES_NO_WRITE_AUTHORITY",
        "repository": REPO,
        "observed_main": live,
        "previous_first_parent_source": parent,
        "state_branch_must_remain": state,
        "incident_run_id": incident["run_id"],
        "incident_original_conclusion": conclusion,
        "decision": decision,
        "candidate_for_independent_original_provider_recheck": candidate,
        "revert_requires_new_checked_commit": candidate,
        "prepare_separate_draft_revert_pr": candidate,
        "reviewed_source_paths": sorted(changed),
        "strict_next_gates": [
            "AUTHENTICATE_ORIGINAL_GITHUB_RUN_JOB_AND_ARTIFACT_INDEPENDENTLY",
            "RECHECK_PROTECTED_MAIN_AND_FIRST_PARENT_AT_GITHUB",
            "DO_NOT_TOUCH_OR_RESET_BRAIN_STATE_BRANCH",
            "CREATE_REVERT_ON_REVIEW_BRANCH_ONLY",
            "VALIDATE_NEGATIVE_AND_POSITIVE_REGRESSIONS",
            "REQUIRE_INDEPENDENT_CHECK_APP_15368_AND_APP_5121826",
            "REQUIRE_SEPARATE_GOVERNED_SOURCE_SPECIFIC_RELEASE",
            "MERGE_THROUGH_ACTIVE_PROTECTION_ONLY_IF_APPROVED",
            "PROVE_NEW_SOURCE_AUTOMATIC_RECOVERY_IN_PRODUCTION",
        ],
        "git_revert_executed": False,
        "force_push_allowed": False,
        "state_reset_allowed": False,
        "provider_write_attempted": False,
        "protected_main_modified": False,
        "rollback_approved": False,
        "production_release_authorized": False,
    }
    payload["observation_fingerprint"] = hashlib.sha256(
        json.dumps({"snapshot": snapshot, "incident": incident},
                   sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode("utf-8")
    ).hexdigest()
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--incident", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    record = inspect(read_input(args.snapshot), read_input(args.incident))
    args.output.write_text(json.dumps(record, sort_keys=True, indent=2)+"\n")
    print(json.dumps({"decision": record["decision"],
                      "production_release_authorized": False,
                      "provider_write_attempted": False}))


if __name__ == "__main__":
    main()
