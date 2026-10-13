"""Synthetic regression tests for bounded private read-only operator review."""
import copy
import importlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from brain.review import review_lines, review_packet

SHA = "a" * 40
REV = "b" * 40
NOW = "2026-10-13T13:00:00Z"
REPOS = ("P00NSMASHER/portfolio-brain", "P00NSMASHER/abvmschoolstarworld",
         "P00NSMASHER/trading-platform")


def check(name="validate", outcome="STILL_ADVERSE", original="INITIAL_ADVERSE_TRANSITION",
          *, include_original=True, historical=None):
    data = {"name": name, "outcome": outcome,
            "source_ref": "https://github.com/P00NSMASHER/portfolio-brain/actions/runs/123/job/1"}
    if include_original:
        data["original_evidence_class"] = original
    if historical is not None:
        data["historical_observations"] = historical
    return data


def observation(*checks, repo=REPOS[0], outcome="OBSERVED_CHECK_STATUS_NOT_ROOT_CAUSE",
                include_classes=True):
    revision_ref = f"https://github.com/{repo}/commit/{REV}"
    ret = {"repository": repo, "expected_revision": REV,
           "source_refs": [revision_ref],
           "outcome": outcome, "check_names": [c["name"] for c in checks],
           "checks": list(checks), "queue_id": "1" * 20,
           "original_observed_at": "2026-10-13T12:00:00Z"}
    if include_classes:
        ret["check_evidence_classes"] = {
            c["name"]: c.get("original_evidence_class", "INITIAL_ADVERSE_TRANSITION")
            for c in checks
        }
    return ret


def receipt(*rows, status="READ_ONLY_REVALIDATION_COMPLETE", deferred=0):
    return {"schema_version": 1,
            "scope": "READ_ONLY_AUTONOMOUS_CHECK_REVALIDATION",
            "source_sha": SHA, "state_sequence": 12, "checked_at": NOW,
            "status": status, "investigations": list(rows),
            "eligible_count": len(rows) + deferred, "deferred_count": deferred,
            "requests_used": len(rows)*4, "max_investigations": 3,
            "execution_authority": False, "root_cause_verified": False,
            "github_mutations": 0, "events_written": 0, "paid_calls": 0}


class HumanReviewTests(unittest.TestCase):
    def test_new_adverse_routes_review_without_executing(self):
        packet = review_packet(receipt(observation(check())))
        self.assertEqual(packet["status"], "REVIEW_PROPOSALS_NOT_EXECUTED")
        self.assertEqual(packet["scope"], "PRIVATE_HUMAN_CHECK_REVIEW_ONLY")
        self.assertEqual(packet["get_requests_added"], 0)
        self.assertEqual(packet["external_state_writes"], 0)
        self.assertIs(packet["execution_authority"], False)
        self.assertIs(packet["root_cause_verified"], False)
        self.assertIs(packet["incident_closed"], False)
        self.assertEqual(packet["items"][0]["category"], "NEW_ADVERSE_CHECK")
        self.assertEqual(packet["items"][0]["review_order_not_impact_rank"], 1)
        self.assertIn("CI logs", packet["items"][0]["proposed_human_review"])

    def test_urgent_gap_before_persistent_and_success(self):
        source_changed = observation(repo=REPOS[0], outcome="SOURCE_CHANGED_REQUIRES_NEW_COMPARISON")
        gap = observation(check("pending", "CHECK_NOT_COMPLETED",
                                "EVIDENCE_GAP_REVALIDATION"), repo=REPOS[1])
        good = observation(check("green", "SUCCESS_OBSERVED_NOT_RESOLUTION",
                                 "RECOVERY_OBSERVED_NOT_RESOLUTION"), repo=REPOS[2])
        packet = review_packet(receipt(good, gap, source_changed))
        self.assertEqual([x["category"] for x in packet["items"]],
                         ["SOURCE_COMPARABILITY_LOST", "MISSING_OR_PENDING_CHECK",
                          "RECOVERY_OBSERVED_NOT_CONFIRMED"])
        self.assertEqual(packet["get_requests_added"], 0)

    def test_provisional_recovery_cannot_close_incident(self):
        packet = review_packet(receipt(observation(check(
            outcome="SUCCESS_OBSERVED_NOT_RESOLUTION",
            original="RECOVERY_OBSERVED_NOT_RESOLUTION"))))
        self.assertEqual(packet["items"][0]["category"], "RECOVERY_OBSERVED_NOT_CONFIRMED")
        self.assertIs(packet["incident_closed"], False)
        self.assertIs(packet["items"][0]["independent_resolution_verified"], False)

    def test_provider_failure_manual_retry_only(self):
        row = observation(outcome="UNVERIFIED_READ_FAILED")
        packet = review_packet(receipt(row, status="INCOMPLETE_READ_ONLY_REVALIDATION"))
        self.assertEqual(packet["items"][0]["category"], "PROVIDER_EVIDENCE_UNAVAILABLE")
        self.assertIsNone(packet["items"][0]["check_name"])
        self.assertEqual(packet["items"][0]["evidence_ref"],
                         f"https://github.com/{REPOS[0]}/commit/{REV}")
        self.assertEqual(packet["external_state_writes"], 0)

    def test_repeated_adverse_is_not_downtime(self):
        history = {"terminal_samples": 4, "adverse_streak_samples": 3,
                   "adverse_success_flips_observed": 1,
                   "capped_at_12_samples": False}
        packet = review_packet(receipt(observation(check(original="PERSISTENT_ADVERSE_OBSERVED",
                                                        historical=history))))
        item = packet["items"][0]
        self.assertEqual(item["category"], "PERSISTENT_ADVERSE_CHECK")
        self.assertEqual(item["historical_sample_summary"], {
            "sampled_terminal_observations": 4, "sampled_adverse_streak": 3,
            "sampled_terminal_state_flips": 1,
            "history_sample_cap_reached": False})
        self.assertNotIn("downtime_minutes", str(item))
        lines = "\n".join(review_lines(receipt(observation(check(
            original="PERSISTENT_ADVERSE_OBSERVED", historical=history)))))
        self.assertIn("NOT elapsed downtime", lines)
        self.assertIn("NOT repairs", lines)

    def test_12_cap_four_per_repo_and_omission_not_hidden(self):
        rows = []
        for repo in REPOS:
            rows.append(observation(*[
                check(f"check-{i}", original="PERSISTENT_ADVERSE_OBSERVED")
                for i in range(10)
            ], repo=repo))
        packet = review_packet(receipt(*rows, deferred=1,
                                       status="BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED"))
        self.assertEqual(packet["candidates_considered"], 30)
        self.assertEqual(len(packet["items"]), 12)
        self.assertEqual(packet["omitted_due_to_review_bounds"], 18)
        self.assertEqual(packet["deferred_repositories_not_inspected"], 1)
        self.assertEqual({r: sum(x["repository"]==r for x in packet["items"])
                          for r in REPOS}, {r:4 for r in REPOS})

    def test_order_independence_and_stable_identifiers(self):
        rows = [observation(check("x"), check("y"), repo=REPOS[0]),
                observation(check("q"), repo=REPOS[1])]
        one = review_packet(receipt(*rows))
        two = review_packet(receipt(*reversed(rows)))
        self.assertEqual(one, two)
        self.assertEqual(len({i["id"] for i in one["items"]}), 3)

    def test_escaping_untrusted_markdown_check_name(self):
        malicious = "<script> [click](https://evil.tld) *urgent*"
        packet = review_packet(receipt(observation(check(malicious))))
        self.assertEqual(packet["items"][0]["check_name"], malicious)
        text = "\n".join(review_lines(receipt(observation(check(malicious)))))
        self.assertNotIn("<script>", text)
        self.assertNotIn("[click]", text)
        self.assertNotIn("*urgent*", text)
        self.assertIn("\\<script\\>", text)
        self.assertNotIn("href", text)

    def test_source_ref_evil_host_replaced_with_canonical_commit(self):
        checkrow = check()
        checkrow["source_ref"] = "https://evil.example.invalid/click"
        packet = review_packet(receipt(observation(checkrow)))
        self.assertEqual(packet["items"][0]["evidence_ref"],
                         f"https://github.com/{REPOS[0]}/commit/{REV}")

    def test_no_items_retains_deferred_visibility(self):
        packet = review_packet(receipt(status="NO_ELIGIBLE_FAILURES"))
        self.assertEqual(packet["status"], "NO_ELIGIBLE_REVIEW")
        self.assertEqual(packet["items"], [])
        self.assertEqual(packet["get_requests_added"], 0)
        self.assertEqual(packet["candidates_considered"], 0)

    def test_valid_source_ref_and_legacy_no_per_check_class(self):
        row = observation(check(include_original=False), include_classes=False)
        packet = review_packet(receipt(row))
        self.assertEqual(packet["items"][0]["original_evidence_class"],
                         "INITIAL_ADVERSE_TRANSITION")

    def test_canonical_origin_and_duplicate_repos_required(self):
        row = observation(check())
        for damaged in (
            {**receipt(row), "scope":"TRADE_EXECUTION_AUTHORIZED"},
            {**receipt(row), "source_sha":"broken"},
            {**receipt(row), "state_sequence":True},
            {**receipt(row), "execution_authority":True},
            {**receipt(row), "events_written":False},
            receipt(row,row),
        ):
            with self.subTest(damaged=damaged), self.assertRaises(ValueError):
                review_packet(damaged)

    def test_mismatched_check_names_and_classes_fail_closed(self):
        row = observation(check("x"))
        examples = []
        for value in (None, 23, ["x","x"], ["y"]):
            o=copy.deepcopy(row)
            o["check_names"]=value
            examples.append(o)
        for value in ("FUND_TRANSFER", None, True):
            o=copy.deepcopy(row)
            o["check_evidence_classes"]["x"] = value
            examples.append(o)
        for item in examples:
            with self.subTest(item=item), self.assertRaises(ValueError):
                review_packet(receipt(item))

    def test_provider_reason_unknown_does_not_make_manual_instruction(self):
        row = observation(check(outcome="PAYOUT_VERIFIED"))
        with self.assertRaises(ValueError):
            review_packet(receipt(row))

    def test_untrusted_history_bounds_and_types_rejected(self):
        good = {"terminal_samples":3,"adverse_streak_samples":2,
                "adverse_success_flips_observed":1,"capped_at_12_samples":False}
        for key, value in (("terminal_samples",13),
                           ("terminal_samples",True),
                           ("adverse_streak_samples",4),
                           ("adverse_success_flips_observed",3),
                           ("capped_at_12_samples",1)):
            invalid = good.copy()
            invalid[key] = value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                review_packet(receipt(observation(check(historical=invalid))))

    def test_same_names_different_order_are_deterministic(self):
        a,b = check("z"),check("a")
        x=review_packet(receipt(observation(a,b)))
        y=review_packet(receipt(observation(b,a)))
        self.assertEqual(x,y)

    def test_no_duplicate_actions_when_one_repository_has_many_signals(self):
        checks=[check(f"item-{i}", original="PERSISTENT_ADVERSE_OBSERVED")
                for i in range(8)]
        summary=review_packet(receipt(observation(*checks)))
        self.assertEqual(len(summary["items"]),4)
        self.assertEqual(summary["candidates_considered"],8)
        self.assertEqual(summary["omitted_due_to_review_bounds"],4)


if __name__ == "__main__":
    unittest.main()
