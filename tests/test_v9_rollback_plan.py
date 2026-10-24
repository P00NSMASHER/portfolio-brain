"""Fail-closed tests for strictly non-executing rollback planning."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from verification import v9_rollback_plan as guard


MAIN = "a" * 40
PARENT = "b" * 40
STATE = "c" * 40


def snapshot():
    return {
        "repository": guard.REPO,
        "ruleset_id": guard.RULESET_ID,
        "protected_main": True,
        "ruleset_enforcement": "active",
        "bypass_actors": [],
        "main_sha": MAIN,
        "main_first_parent_sha": PARENT,
        "state_branch_sha": STATE,
        "required_checks": [
            {"name": "validate", "app_id": 15368},
            {"name": "portfolio-phase1-gate", "app_id": 5121826},
        ],
        "release_changed_files": [
            "brain/v9/guarded_merge.py",
            "tests/test_brain_v9_guarded_merge.py",
        ],
    }


def incident():
    return {
        "source_sha": MAIN,
        "workflow": "brain-cycle-v2",
        "event": "workflow_dispatch",
        "run_id": 39353850712,
        "attempt": 1,
        "conclusion": "failure",
        "monitor_conclusion": "failure",
        "origin": "CLOUDFLARE_SIGNED",
        "provider_write_uncertain": False,
    }


class RecoveryPolicy(unittest.TestCase):
    def test_real_adverse_stages_only_a_protected_review(self):
        result = guard.inspect(snapshot(), incident())
        self.assertEqual(result["decision"],
                         "PREPARE_PROTECTED_REVERT_PR_FOR_INDEPENDENT_REVIEW_ONLY")
        self.assertTrue(result["prepare_separate_draft_revert_pr"])
        for key in ("force_push_allowed", "state_reset_allowed",
                    "provider_write_attempted", "git_revert_executed",
                    "rollback_approved", "production_release_authorized",
                    "protected_main_modified"):
            self.assertIs(result[key], False)
        self.assertEqual(result["state_branch_must_remain"], STATE)

    def test_successful_original_core_cannot_trigger_rollback(self):
        x = incident()
        x["conclusion"] = x["monitor_conclusion"] = "success"
        found = guard.inspect(snapshot(), x)
        self.assertEqual(found["decision"],
                         "HOLD_NO_CONFIRMED_ADVERSE_AUTOMATIC_CORE")
        self.assertFalse(found["prepare_separate_draft_revert_pr"])

    def test_wrong_owner_and_protected_ruleset_mismatch_fail(self):
        cases = [
            ("repository", "attacker/portfolio-brain"),
            ("ruleset_id", True),
            ("protected_main", False),
            ("ruleset_enforcement", "disabled"),
            ("bypass_actors", [{"actor_id": 1}]),
            ("bypass_actors", None),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                v = snapshot()
                v[key] = value
                with self.assertRaises(guard.RevertReviewHold):
                    guard.inspect(v, incident())

    def test_untrusted_git_revert_parent_or_state_is_never_accepted(self):
        for key, value in (
            ("main_sha", "unknown"), ("main_first_parent_sha", MAIN),
            ("state_branch_sha", "z" * 40), ("state_branch_sha", None),
        ):
            with self.subTest(key=key):
                v = snapshot()
                v[key] = value
                with self.assertRaises(guard.RevertReviewHold):
                    guard.inspect(v, incident())

    def test_foreign_or_unverified_original_run_rejected(self):
        for key, value in (
            ("source_sha", PARENT), ("workflow", "untrusted-workflow"),
            ("event", "push"), ("run_id", True),
            ("attempt", 2), ("conclusion", "in_progress"),
            ("monitor_conclusion", "success"),
        ):
            with self.subTest(key=key):
                i = incident()
                i[key] = value
                with self.assertRaises(guard.RevertReviewHold):
                    guard.inspect(snapshot(), i)

    def test_mismatched_cron_origin_and_clock_fail(self):
        for event, origin in (
            ("schedule", "CLOUDFLARE_SIGNED"),
            ("workflow_dispatch", "GITHUB_NATIVE_SCHEDULE"),
        ):
            i = incident()
            i.update(event=event, origin=origin)
            with self.assertRaisesRegex(guard.RevertReviewHold,
                                        "AUTOMATIC_ORIGIN_EVENT_CONFLICT"):
                guard.inspect(snapshot(), i)

    def test_uncertain_provider_write_is_a_hard_stop(self):
        for unknown in (True, "false", None):
            i = incident()
            i["provider_write_uncertain"] = unknown
            with self.assertRaisesRegex(guard.RevertReviewHold,
                                        "EXTERNAL_WRITE_UNCERTAIN_STOP"):
                guard.inspect(snapshot(), i)

    def test_unreviewed_executable_and_state_paths_disallowed(self):
        for path in (
            ".github/workflows/brain-cycle.yml",
            "brain-state-v2/state.sqlite",
            "brain/v9/../../.github/secrets",
            "README.md",
            ".github/workflows/untrusted.yml",
        ):
            v = snapshot()
            v["release_changed_files"] = ["brain/v9/guarded_merge.py", path]
            with self.subTest(path=path):
                with self.assertRaisesRegex(guard.RevertReviewHold,
                                            "REVERT_SCOPE_NOT_REVIEWED"):
                    guard.inspect(v, incident())

    def test_missing_or_swapped_independent_issuer_denied(self):
        for key in ("validate", "portfolio-phase1-gate"):
            v = snapshot()
            for item in v["required_checks"]:
                if item["name"] == key:
                    item["app_id"] = 1
            with self.assertRaisesRegex(guard.RevertReviewHold,
                                        "REQUIRED_CHECKS_NOT_AUTHENTICATED"):
                guard.inspect(v, incident())

    def test_duplicate_bypass_and_status_changes_cannot_override_policy(self):
        v = snapshot()
        v["bypass_actors"] = [{"actor_id": 1}]
        with self.assertRaises(guard.RevertReviewHold):
            guard.inspect(v, incident())
        v = snapshot()
        v["release_changed_files"] = ["brain/v9/guarded_merge.py"]*2
        with self.assertRaisesRegex(guard.RevertReviewHold,
                                    "REVERT_SCOPE_NOT_REVIEWED"):
            guard.inspect(v, incident())

    def test_duplicate_json_nan_and_too_large_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"incident.json"
            for payload in ('{"a":1,"a":2}', '{"risk":NaN}', '{"'):
                p.write_text(payload)
                with self.assertRaises(guard.RevertReviewHold):
                    guard.read_input(p)
            p.write_bytes(b" "*(guard.MAX_JSON+1))
            with self.assertRaisesRegex(guard.RevertReviewHold, "OVERSIZED"):
                guard.read_input(p)

    def test_review_plan_is_deterministic_and_always_non_authoritative(self):
        result = guard.inspect(snapshot(), incident())
        repeated = guard.inspect(copy.deepcopy(snapshot()), copy.deepcopy(incident()))
        self.assertEqual(json.dumps(result, sort_keys=True),
                         json.dumps(repeated, sort_keys=True))
        self.assertEqual(len(result["observation_fingerprint"]), 64)
        self.assertFalse(result["production_release_authorized"])


if __name__ == "__main__":
    unittest.main()
