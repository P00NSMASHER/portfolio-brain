"""V7 new adverse check with missing baseline: never invent a regression.

Synthetic original immutable SQLite events and fake provider GETs only.
"""
import copy
import unittest

from brain.adapters import GitHub
from brain.core import BrainError
from brain.investigate import investigate
from brain.sidecar import summarize
from brain.review import review_packet, review_lines
from test_brain_evidence_gaps import check, observe, verified, T0, T1, FOURTH
from test_brain_investigate import (
    REPO, OTHER, THIRD, REV, SOURCE, NOW, Transport,
)

REPOS = (REPO, OTHER, THIRD, FOURTH)
CLASS = "UNBASELINED_ADVERSE_OBSERVED"


def sample(repo, when, checks, *, kind="ACTUAL", revision=REV):
    return observe(repo, when, [{**item, "head_sha": revision} for item in checks], kind=kind, sha=revision)


def c(repo, name, conclusion="failure", *, status="completed"):
    return check(repo, name=name, conclusion=conclusion, status=status)


def provider(name="deploy", *, conclusion="failure"):
    transport = Transport(conclusion="success")
    transport.extra_checks = [{
        "id": 91, "name": name, "status": "completed",
        "conclusion": conclusion, "head_sha": REV,
        "html_url": f"https://github.com/{REPO}/actions/runs/41/job/91",
    }]
    return transport


def run_case(*events, fake=None, moment=NOW):
    report, history = verified(*events)
    original = copy.deepcopy((report, history))
    fake = fake or provider()
    result = investigate(report, history=history,
                         api=GitHub(transport=fake), now=moment)
    assert original == (report, history)
    return result, fake, report


class UnbaselinedAdverseTests(unittest.TestCase):
    def test_failed_new_check_on_existing_commit_is_investigated_not_called_regression(self):
        before = sample(REPO, T0, [c(REPO, "validate", "success")])
        after = sample(REPO, T1, [
            c(REPO, "validate", "success"), c(REPO, "deploy", "failure")
        ])
        result, transport, report = run_case(before, after)
        self.assertEqual(report["repository_changes"][0]["check_deteriorations"], [])
        self.assertEqual(result["status"], "READ_ONLY_REVALIDATION_COMPLETE")
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["requests_used"], 4)
        self.assertEqual(len(transport.calls), 4)
        row = result["investigations"][0]
        self.assertEqual(row["follow_up_kind"], CLASS)
        self.assertEqual(row["check_names"], ["deploy"])
        self.assertEqual(row["check_evidence_classes"], {"deploy": CLASS})
        self.assertEqual(row["checks"][0]["outcome"], "STILL_ADVERSE")
        self.assertEqual(row["checks"][0]["original_evidence_class"], CLASS)
        self.assertEqual(row["checks"][0]["historical_observations"]["terminal_samples"], 1)
        self.assertEqual(result["github_mutations"], 0)
        self.assertFalse(result["root_cause_verified"])
        public = summarize(result, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(public["observed_check_evidence_classes"], {CLASS: 1})
        self.assertNotIn(REPO, str(public))
        self.assertNotIn("deploy", str(public))
        review = review_packet(result)
        self.assertEqual(review["items"][0]["category"],
                         "UNBASELINED_ADVERSE_CHECK")
        self.assertFalse(review["execution_authority"])
        self.assertIn("no baseline", review["items"][0]["proposed_human_review"].lower())

    def test_no_shared_names_still_follows_first_observed_failed_check(self):
        result, fake, report = run_case(
            sample(REPO, T0, []),
            sample(REPO, T1, [c(REPO, "deploy")]),
        )
        self.assertEqual(report["repository_changes"][0]["check_comparison"],
                         "NO_SHARED_CHECK_NAMES")
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["investigations"][0]["follow_up_kind"], CLASS)
        self.assertEqual(len(fake.calls), 4)
        self.assertEqual(summarize(result, SOURCE, *["success"]*4)["status"],
                         "PARTIAL_READ_ONLY")

    def test_new_success_neutral_and_pending_checks_are_not_adverse(self):
        for outcome, status in (
            ("success", "completed"), ("skipped", "completed"),
            ("neutral", "completed"), (None, "in_progress"),
        ):
            with self.subTest(outcome=outcome):
                result, fake, _ = run_case(
                    sample(REPO, T0, [c(REPO, "validate", "success")]),
                    sample(REPO, T1, [
                        c(REPO, "validate", "success"),
                        c(REPO, "deploy", outcome, status=status),
                    ]),
                )
                self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
                self.assertEqual(fake.calls, [])

    def test_previously_ambiguous_old_name_is_not_a_new_check(self):
        result, fake, _ = run_case(
            sample(REPO, T0, [c(REPO,"deploy"),c(REPO,"deploy")]),
            sample(REPO, T1, [c(REPO,"deploy")]),
        )
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(fake.calls, [])

    def test_newly_ambiguous_current_name_is_quarantined(self):
        result, fake, _ = run_case(
            sample(REPO, T0, [c(REPO,"validate","success")]),
            sample(REPO, T1, [
                c(REPO,"validate","success"),
                c(REPO,"deploy"), c(REPO,"deploy"),
            ]),
        )
        self.assertEqual(result["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(fake.calls, [])

    def test_first_adverse_check_does_not_skip_persistent_and_recovery(self):
        transport = provider("deploy")
        transport.extra_checks.extend([
            {"id":92,"name":"persist","status":"completed",
             "conclusion":"failure","head_sha":REV,
             "html_url":f"https://github.com/{REPO}/actions/runs/42/job/92"},
            {"id":93,"name":"audit","status":"completed",
             "conclusion":"success","head_sha":REV,
             "html_url":f"https://github.com/{REPO}/actions/runs/43/job/93"},
        ])
        result, fake, _ = run_case(
            sample(REPO, T0, [c(REPO,"validate","success"),
                              c(REPO,"persist"),c(REPO,"audit")]),
            sample(REPO, T1, [c(REPO,"validate","success"),
                              c(REPO,"persist"),c(REPO,"audit","success"),
                              c(REPO,"deploy")]),
            fake=transport,
        )
        row=result["investigations"][0]
        self.assertEqual(row["follow_up_kind"],CLASS)
        self.assertEqual(set(row["check_names"]), {"deploy","persist","audit"})
        self.assertEqual(row["check_evidence_classes"], {
            "deploy": CLASS,"persist":"PERSISTENT_ADVERSE_OBSERVED",
            "audit":"RECOVERY_OBSERVED_NOT_RESOLUTION",
        })
        self.assertEqual(len(fake.calls),4)
        self.assertEqual(result["eligible_count"],1)
        self.assertFalse(result["root_cause_verified"])

    def test_new_proven_regression_out_ranks_unbaselined_and_shares_one_read(self):
        fake=provider("deploy")
        fake.conclusion="failure"
        result, fake, _=run_case(
            sample(REPO,T0,[c(REPO,"validate","success")]),
            sample(REPO,T1,[c(REPO,"validate"),c(REPO,"deploy")]),
            fake=fake,
        )
        row=result["investigations"][0]
        self.assertNotIn("follow_up_kind",row)
        self.assertEqual(row["check_names"],["deploy","validate"])
        self.assertEqual(row["check_evidence_classes"],{
            "validate":"INITIAL_ADVERSE_TRANSITION","deploy":CLASS,
        })
        self.assertEqual(len(fake.calls),4)
        public=summarize(result,SOURCE,*["success"]*4)
        self.assertEqual(public["status"],"PARTIAL_READ_ONLY")
        self.assertEqual(public["observed_followup_kinds"],
                         {"INITIAL_ADVERSE_TRANSITION":1})
        self.assertEqual(public["observed_check_evidence_classes"],
                         {"INITIAL_ADVERSE_TRANSITION":1,CLASS:1})

    def test_four_new_failed_checks_rotate_under_unchanged_provider_budget(self):
        events=[]
        for repo in REPOS:
            events.extend([
                sample(repo,T0,[c(repo,"validate","success")]),
                sample(repo,T1,[c(repo,"validate","success"),c(repo,"deploy")]),
            ])
        report,history=verified(*events)
        omitted=set()
        for hour in range(16,20):
            fake=Transport()
            receipt=investigate(
                report,history=history,api=GitHub(transport=fake),
                now=f"2026-10-12T{hour:02d}:00:00Z")
            self.assertEqual(receipt["eligible_count"],4)
            self.assertEqual(receipt["deferred_count"],1)
            self.assertEqual(receipt["requests_used"],12)
            self.assertEqual(len(fake.calls),12)
            self.assertEqual(len(receipt["investigations"]),3)
            omitted.update(set(REPOS)-{
                item["repository"] for item in receipt["investigations"]
            })
        self.assertEqual(omitted,set(REPOS))

    def test_nonactual_stale_and_changed_revision_do_not_trigger_reads(self):
        candidates=[
            [sample(REPO,T0,[]),sample(REPO,T1,[c(REPO,"deploy")],
                                       kind="SIMULATED")],
            [sample(REPO,"2026-10-08T13:00:00Z",[]),
             sample(REPO,T1,[c(REPO,"deploy")])],
            [sample(REPO,T0,[]),
             sample(REPO,T1,[c(REPO,"deploy")],revision="c"*40)],
        ]
        for event_pair in candidates:
            with self.subTest(pair=event_pair[-1]["observed_at"]):
                result,fake,_=run_case(*event_pair)
                self.assertEqual(result["status"],"NO_ELIGIBLE_FAILURES")
                self.assertEqual(fake.calls,[])

    def test_forged_ledger_blocks_before_any_provider_read(self):
        old=sample(REPO,T0,[])
        new=sample(REPO,T1,[c(REPO,"deploy")])
        report,history=verified(old,new)
        tampered=copy.deepcopy(history)
        tampered[-1]["payload"]["open_issues"]+=1
        fake=provider()
        with self.assertRaises(BrainError):
            investigate(report,history=tampered,api=GitHub(transport=fake),
                        now=NOW)
        self.assertEqual(fake.calls,[])

    def test_provider_outcome_success_does_not_create_historical_regression(self):
        result,_,_=run_case(
            sample(REPO,T0,[c(REPO,"validate","success")]),
            sample(REPO,T1,[c(REPO,"validate","success"),c(REPO,"deploy")]),
            fake=provider("deploy",conclusion="success"),
        )
        row=result["investigations"][0]["checks"][0]
        self.assertEqual(row["outcome"],"SUCCESS_OBSERVED_NOT_RESOLUTION")
        self.assertEqual(row["original_evidence_class"],CLASS)
        self.assertFalse(result["root_cause_verified"])
        self.assertEqual(summarize(result,SOURCE,*["success"]*4)["status"],
                         "PARTIAL_READ_ONLY")


if __name__=="__main__":
    unittest.main()
