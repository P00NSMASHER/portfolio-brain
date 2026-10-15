"""Adversarial GET-only GitHub source evidence for owner repairs."""
import copy
import json
import unittest

from brain.core import BrainError
from brain.repair_autonomy import repair_batch
from brain.repair_followthrough import follow_through
from brain.repair_provider import (
    collect_original_proofs, github_transport, MAX_REQUESTS, _work_inputs,
    _unique_json_pairs, apply_original_ci_to_owner_queue,
)
from test_brain_repair_autonomy import fixture, A, B, RET, FAC


MAIN = "c" * 40


def pr_for(repo, number, sha=A, merged=False, merge=None, state=None):
    return {
        "number": number, "state": state or ("closed" if merged else "open"),
        "merged": merged,
        "merge_commit_sha": merge if merged else None,
        "head": {"sha": sha, "repo": {"full_name": repo}},
        "base": {"ref": "main", "repo": {"full_name": repo}},
    }


def original_checks(repo, sha, *, wrong_app=False):
    labels = ("release-gate", "freight") if repo == RET else (
        "test", "browser", "manufacturing", "pilot", "candidate-build"
    )
    return {"total_count": len(labels), "check_runs": [
        {"id": i+1, "name": label, "head_sha": sha,
         "app": {"id": 1 if wrong_app else 15368},
         "status": "completed", "conclusion": "success"}
        for i, label in enumerate(labels)
    ]}


class MockOriginalGitHub:
    def __init__(self):
        self.calls = []
        self.payloads = {}
        self.fail = set()

    def put(self, repo, path, data):
        self.payloads[(repo, path)] = data

    def __call__(self, repo, path):
        self.calls.append((repo, path))
        if (repo, path) in self.fail:
            raise OSError("provider unavailable")
        if (repo, path) not in self.payloads:
            raise AssertionError(f"unregistered provider request {repo} {path}")
        return copy.deepcopy(self.payloads[(repo, path)])


def queue():
    return repair_batch(fixture())


def rig():
    api = MockOriginalGitHub()
    plan = queue()
    for task in plan["actions"]:
        repo = task["repository"]
        number = task["candidate_pr_number"]
        api.put(repo, f"/pulls/{number}", pr_for(repo, number))
        api.put(repo, "/branches/main", {"commit": {"sha": MAIN}})
        api.put(repo, f"/commits/{A}/check-runs?per_page=100",
                original_checks(repo, A))
    return plan, api


class OriginalProviderEvidenceTests(unittest.TestCase):
    def test_open_prs_are_never_reported_as_merged(self):
        current, api = rig()
        result = collect_original_proofs(current, transport=api)
        self.assertEqual(result["observed_pr_count"], 5)
        self.assertEqual(result["requests_used"], 12)
        self.assertEqual(len(result["gaps"]), 0)
        self.assertFalse(result["automatic_merge_or_deployment_authority"])
        self.assertFalse(result["customer_or_external_action_authority"])
        self.assertTrue(all(p["merged"] is False and
                            p["main_checks"] == [] for p in result["proofs"]))
        self.assertEqual(len([p for p in api.calls if p[1]=="/branches/main"]),2)

    def test_exact_original_merged_source_and_checks_remain_technical_only(self):
        current, api = rig()
        task = current["actions"][0]
        repo, number = task["repository"], task["candidate_pr_number"]
        api.put(repo, f"/pulls/{number}",
                pr_for(repo, number, merged=True, merge=MAIN))
        api.put(repo, f"/commits/{MAIN}/check-runs?per_page=100",
                original_checks(repo, MAIN))
        result = collect_original_proofs(current, transport=api)
        self.assertEqual(result["observed_pr_count"],5)
        verified = follow_through(current, cycle=15,
                                  provider_receipts=result["proofs"])
        selected = next(x for x in verified["actions"]
                        if x["source_pr"] == number and x["repository"] == repo)
        self.assertTrue(selected["technical_main_source_verified"])
        self.assertFalse(selected["live_deployment_verified"])
        self.assertFalse(verified["merge_or_deployment_authority"])

    def test_advanced_main_does_not_reuse_merged_checks_as_latest(self):
        current, api = rig()
        task = current["actions"][0]
        repo, number = task["repository"], task["candidate_pr_number"]
        api.put(repo, f"/pulls/{number}",
                pr_for(repo, number, merged=True, merge="d"*40))
        result = collect_original_proofs(current, transport=api)
        self.assertEqual(result["observed_pr_count"],5)
        self.assertIn("MERGE_IS_NOT_LATEST_MAIN_REQUIRE_ANCESTRY",
                      [row["status"] for row in result["gaps"]])
        actual = next(x for x in result["proofs"]
                      if x["repository"] == repo and x["pr_number"] == number)
        self.assertEqual(actual["main_checks"],[])
        self.assertEqual(actual["merge_commit_sha"],"d"*40)
        self.assertFalse(follow_through(
            current,cycle=3,provider_receipts=result["proofs"]
        )["actions"][0]["technical_main_source_verified"])

    def test_changed_candidate_head_rejected_but_other_work_survives(self):
        current, api = rig()
        task=current["actions"][0]
        repo, number = task["repository"], task["candidate_pr_number"]
        api.put(repo, f"/pulls/{number}", pr_for(repo, number, sha=B))
        res=collect_original_proofs(current, transport=api)
        self.assertEqual(res["observed_pr_count"],4)
        self.assertEqual(len(res["gaps"]),1)
        self.assertEqual(res["gaps"][0]["status"],
                         "EXACT_HEAD_CHANGED_RESCAN_BEFORE_REPAIR")

    def test_closed_without_merge_is_not_completed(self):
        current, api = rig()
        task=current["actions"][0]
        repo, number=task["repository"],task["candidate_pr_number"]
        api.put(repo,f"/pulls/{number}",
                pr_for(repo,number,state="closed",merged=False))
        res=collect_original_proofs(current,transport=api)
        self.assertEqual(len(res["gaps"]),1)
        self.assertEqual(res["gaps"][0]["status"],
                         "CLOSED_WITHOUT_MERGE_NOT_FIXED")
        self.assertFalse(any(x["pr_number"]==number and x["repository"]==repo
                             for x in res["proofs"]))

    def test_unavailable_single_provider_does_not_claim_success(self):
        current, api = rig()
        task=current["actions"][0]
        api.fail.add((task["repository"],f'/pulls/{task["candidate_pr_number"]}'))
        res=collect_original_proofs(current,transport=api)
        self.assertEqual(res["observed_pr_count"],4)
        self.assertEqual(res["gaps"][0]["status"],
                         "PR_PROVIDER_UNAVAILABLE_NOT_RESOLVED")

    def test_provider_wrong_base_fork_or_schema_fails_closed(self):
        for field in ("base", "fork", "wrong_number", "bogus"):
            current, api=rig()
            task=current["actions"][0]
            repo, number=task["repository"],task["candidate_pr_number"]
            p=pr_for(repo,number)
            if field=="base":p["base"]["ref"]="staging"
            if field=="fork":p["head"]["repo"]["full_name"]="attacker/fork"
            if field=="wrong_number":p["number"]=number+1
            if field=="bogus":p["merged"]="yes"
            api.put(repo,f"/pulls/{number}",p)
            with self.subTest(field=field),self.assertRaises(BrainError):
                collect_original_proofs(current,transport=api)

    def test_check_pagination_and_wrong_original_check_rows_fail_closed(self):
        for issue in ("partial","duplicate","wrong_sha"):
            current, api=rig()
            task=current["actions"][0]
            repo, number=task["repository"],task["candidate_pr_number"]
            api.put(repo,f"/pulls/{number}",
                    pr_for(repo,number,merged=True,merge=MAIN))
            checks=original_checks(repo,MAIN)
            if issue=="partial":checks["total_count"]=101
            if issue=="duplicate":checks["check_runs"][1]["id"]=1
            if issue=="wrong_sha":checks["check_runs"][0]["head_sha"]=B
            api.put(repo,f"/commits/{MAIN}/check-runs?per_page=100",checks)
            with self.subTest(issue=issue),self.assertRaises(BrainError):
                collect_original_proofs(current,transport=api)

    def test_untrusted_provider_app_cannot_claim_original_main_ci(self):
        current, api=rig()
        task=current["actions"][0]
        repo, number=task["repository"],task["candidate_pr_number"]
        api.put(repo,f"/pulls/{number}",
                pr_for(repo,number,merged=True,merge=MAIN))
        api.put(repo,f"/commits/{MAIN}/check-runs?per_page=100",
                original_checks(repo,MAIN,wrong_app=True))
        result=collect_original_proofs(current,transport=api)
        proof=follow_through(current,cycle=10,
                             provider_receipts=result["proofs"])
        selected=next(x for x in proof["actions"] if x["source_pr"]==number
                      and x["repository"]==repo)
        self.assertFalse(selected["technical_main_source_verified"])

    def test_history_reintroduces_unsampled_unfinished_pr(self):
        current, api=rig()
        task=current["actions"][0]
        missing={
            "dedupe_key": "0"*64, "exact_evidence_key": "1"*64,
            "repository":FAC,"owner_task":"Autonomous App Factory",
            "pr_number":999,"head_sha":B,"state":"CI_RED",
            "last_progress_cycle":1,"source_revision_attempts":1
        }
        api.put(FAC,"/pulls/999",pr_for(FAC,999,sha=B))
        api.put(FAC,f"/commits/{B}/check-runs?per_page=100",
                original_checks(FAC,B))
        res=collect_original_proofs(current,prior=[missing],
                                    transport=api,max_jobs=6)
        self.assertEqual(res["observed_pr_count"],6)
        self.assertEqual(res["requests_used"],14)
        self.assertEqual(api.calls[0],(FAC,"/pulls/999"))

    def test_read_limit_is_bounded_and_unseen_jobs_not_marked_done(self):
        current, api=rig()
        res=collect_original_proofs(current,transport=api,max_jobs=3)
        self.assertEqual(res["observed_pr_count"],3)
        self.assertEqual(res["unsampled_due_to_job_limit"],2)
        self.assertLessEqual(res["requests_used"],MAX_REQUESTS)
        for invalid in (0,9,True,"3"):
            with self.subTest(invalid=invalid),self.assertRaises(BrainError):
                collect_original_proofs(current,transport=api,max_jobs=invalid)

    def test_no_arbitrary_repository_paths_or_redirects_in_runtime_helper(self):
        with self.assertRaises(BrainError):
            github_transport("")
        get=github_transport("fake-local-unit-test-token")
        with self.assertRaises(BrainError):
            get("attacker/repository","/pulls/8")
        with self.assertRaises(BrainError):
            get(RET,"/settings/branches")
        with self.assertRaises(BrainError):
            get(RET,"/pulls/8/merge")

    def test_untrusted_current_queue_rejected_before_any_network_calls(self):
        current, api=rig()
        current["authority_to_merge_or_deploy"]=True
        with self.assertRaises(BrainError):
            collect_original_proofs(current,transport=api)
        self.assertEqual(api.calls,[])

    def test_original_check_not_signed_and_no_contact_authority(self):
        current, api=rig()
        out=collect_original_proofs(current,transport=api)
        self.assertTrue(out["original_api_response_not_signed"])
        self.assertEqual(out["source_credential_boundary"],
                         "EXISTING_GITHUB_READ_ONLY_TOKEN")
        self.assertFalse(out["customer_or_external_action_authority"])

    def test_duplicate_original_provider_json_keys_are_rejected(self):
        with self.assertRaises(BrainError):
            json.loads('{"merged":false,"merged":true}',
                       object_pairs_hook=_unique_json_pairs)

    def test_adverse_original_ci_is_source_pinned_action_not_approval(self):
        current, api = rig()
        task=current["actions"][0]
        repo=task["repository"]
        page=original_checks(repo,A)
        page["check_runs"][0]["conclusion"]="failure"
        api.put(repo,f"/commits/{A}/check-runs?per_page=100",page)
        outcome=collect_original_proofs(current,transport=api)
        found=next(x for x in outcome["source_checks"]
                   if x["repository"]==repo)
        self.assertEqual(found["status"],
                         "ADVERSE_EXACT_HEAD_CHECKS_NEED_REPAIR")
        self.assertEqual(found["adverse_count"],1)
        self.assertTrue(found["technical_only_not_release"])
        self.assertFalse(found["external_contact_or_financial_authority"])
        self.assertTrue(all(x["merged"] is False for x in outcome["proofs"]))

    def test_incomplete_or_wrong_app_ci_is_never_green(self):
        for issue in ("queued","wrong_app","missing"):
            current, api=rig()
            repo=current["actions"][0]["repository"]
            page=original_checks(repo,A)
            if issue=="queued":
                page["check_runs"][0]["status"]="queued"
                page["check_runs"][0]["conclusion"]=None
            if issue=="wrong_app":
                page["check_runs"][0]["app"]["id"]=123
            if issue=="missing":
                page["check_runs"].pop()
                page["total_count"]-=1
            api.put(repo,f"/commits/{A}/check-runs?per_page=100",page)
            result=collect_original_proofs(current,transport=api)
            evidence=next(x for x in result["source_checks"]
                          if x["repository"]==repo)
            with self.subTest(issue=issue):
                self.assertNotEqual(evidence["status"],
                                    "EXACT_HEAD_TECHNICAL_CHECKS_GREEN_NOT_RELEASE")

    def test_duplicate_or_cross_commit_head_ci_fails_closed(self):
        for issue in ("duplicate","cross_source","truncated"):
            current, api=rig()
            repo=current["actions"][0]["repository"]
            page=original_checks(repo,A)
            if issue=="duplicate":
                page["check_runs"][1]["id"]=page["check_runs"][0]["id"]
            if issue=="cross_source":
                page["check_runs"][0]["head_sha"]=B
            if issue=="truncated":
                page["total_count"]=101
            api.put(repo,f"/commits/{A}/check-runs?per_page=100",page)
            with self.subTest(issue=issue),self.assertRaises(BrainError):
                collect_original_proofs(current,transport=api)

    def test_native_single_pr_correction_needs_only_three_gets(self):
        current, api=rig()
        result=collect_original_proofs(
            current,transport=api,max_jobs=1,max_requests=3,
            selection_sequence=100,
        )
        self.assertEqual(result["observed_pr_count"],1)
        self.assertEqual(result["requests_used"],3)
        self.assertEqual(len(result["source_checks"]),1)
        self.assertEqual(result["source_checks"][0]["status"],
                         "EXACT_HEAD_TECHNICAL_CHECKS_GREEN_NOT_RELEASE")
        self.assertEqual(result["selection_sequence"],100)

    def test_fair_rotation_checks_all_distinct_original_heads_over_cycles(self):
        keys=set()
        for cycle in range(5):
            current, api=rig()
            result=collect_original_proofs(
                current,transport=api,max_jobs=1,max_requests=3,
                selection_sequence=cycle,
            )
            self.assertEqual(result["observed_pr_count"],1)
            keys.add((result["proofs"][0]["repository"],
                      result["proofs"][0]["pr_number"]))
        self.assertEqual(len(keys),5)

    def test_real_check_receipt_drives_next_owner_action_without_merge(self):
        work, api = rig()
        source = collect_original_proofs(work,transport=api)
        baseline=follow_through(work,cycle=20,
                                provider_receipts=source["proofs"])
        result=apply_original_ci_to_owner_queue(
            baseline,source["source_checks"]
        )
        self.assertEqual(result["original_ci_bound_actions"],5)
        self.assertTrue(all(x["next_operation"] ==
            "GET_INDEPENDENT_QA_AND_VERIFY_RELEASE_HOLDS"
            for x in result["actions"]))
        self.assertTrue(all(x["state"] == "CI_GREEN"
                            for x in result["next_history"]))
        self.assertFalse(result["merge_or_deployment_authority"])
        self.assertFalse(result["real_buyer_or_revenue_verified"])

    def test_failed_original_check_is_routed_to_code_repair(self):
        work, api = rig()
        task=work["actions"][0]
        repo=task["repository"]
        page=original_checks(repo,A)
        page["check_runs"][0]["conclusion"]="failure"
        api.put(repo,f"/commits/{A}/check-runs?per_page=100",page)
        packet=collect_original_proofs(work,transport=api)
        result=apply_original_ci_to_owner_queue(
            follow_through(work,cycle=24),packet["source_checks"]
        )
        case=next(x for x in result["actions"]
                  if x["repository"]==repo)
        self.assertEqual(case["next_operation"],
                         "REPRODUCE_AND_FIX_REAL_FAILED_HEAD_CI")
        history=next(x for x in result["next_history"]
                     if x["repository"]==repo)
        self.assertEqual(history["state"],"CI_RED")
        self.assertFalse(case["live_deployment_verified"])

    def test_external_hold_and_exhausted_retry_survive_ci_updates(self):
        work, api = rig()
        task=work["actions"][0]
        page=original_checks(task["repository"],A)
        page["check_runs"][0]["conclusion"]="failure"
        api.put(task["repository"],f"/commits/{A}/check-runs?per_page=100",page)
        packet=collect_original_proofs(work,transport=api)
        original=follow_through(work,cycle=30)
        external=copy.deepcopy(original)
        held=next(x for x in external["next_history"]
                  if x["repository"]==task["repository"])
        held["state"]="BLOCKED_EXTERNAL"
        result=apply_original_ci_to_owner_queue(
            external,packet["source_checks"]
        )
        case=next(x for x in result["actions"]
                  if x["repository"]==task["repository"])
        self.assertEqual(case["next_operation"],
                         "PRESERVE_EXTERNAL_HOLD_FIX_NEXT")
        self.assertEqual(held["state"],"BLOCKED_EXTERNAL")
        attempts=copy.deepcopy(original)
        old=next(x for x in attempts["next_history"]
                 if x["repository"]==task["repository"])
        old["state"]="CI_RED"
        old["source_revision_attempts"]=2
        blocked=apply_original_ci_to_owner_queue(
            attempts,packet["source_checks"]
        )
        chosen=next(x for x in blocked["actions"]
                    if x["repository"]==task["repository"])
        self.assertEqual(chosen["next_operation"],
                         "ESCALATE_REPRODUCIBLE_FAILURE_WITH_LOGS")

    def test_wrong_app_or_forged_status_never_gains_reviewer_authority(self):
        work, api=rig()
        packet=collect_original_proofs(work,transport=api)
        bad=copy.deepcopy(packet["source_checks"])
        bad[0]["trusted_app_id"]=999
        with self.assertRaises(BrainError):
            apply_original_ci_to_owner_queue(follow_through(work,cycle=5),bad)
        bad=copy.deepcopy(packet["source_checks"])
        bad[0]["status"]="PAID_CUSTOMER_VALIDATED"
        with self.assertRaises(BrainError):
            apply_original_ci_to_owner_queue(follow_through(work,cycle=5),bad)

if __name__=="__main__":
    unittest.main()
