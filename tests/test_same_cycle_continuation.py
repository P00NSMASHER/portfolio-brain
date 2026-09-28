import json
import unittest

from hunting.autonomous_hunter import load_seed_state as hunter_seed_state
from operations.workflow_liveness import load_policy as load_liveness_policy, verify_work_proof
from runtime.state import bootstrap_state
from scheduler.autonomous_scheduler import (
    build_context,
    is_hunter_proposal_continuation,
    load_state,
    schedule_cycle,
)
from scheduler.same_cycle_continuation import run_same_cycle_continuation
from scheduler.work_executor import hashv


AT="2026-09-27T20:30:00Z"


def proposal_state(count=1):
    proposals=[]
    findings=[]
    origins={}
    for index in range(count):
        suffix="" if index==0 else f"-{index+1}"
        proposal_id="HEXP-SAME-CYCLE"+suffix
        finding_id="HFD-SAME-CYCLE"+suffix
        repository_full_name="public/freight-audit"+suffix
        repository_id=123+index
        revision=(hex(index+10)[2:]*40)[:40]
        candidate_fingerprint="sha256:"+str((index%9)+1)*64
        proposal={
          "schema_version":"1.0.0","proposal_id":proposal_id,"finding_id":finding_id,
          "gap_id":"HGAP-SAME-CYCLE","project_ids":["PRJ-002"],"candidate_rank_score":9,
          "candidate_rank_band":"HIGH","candidate_soft_signals":[],
          "hypothesis":"bounded","baseline":"none","success_condition":"verify","failure_condition":"reject",
          "evidence_requirements":["Exact source revision","License/rights verification"],
          "cost_boundary":"read only","rollback":"none","candidate_rank_order":index+1
        }
        finding={
          "finding_id":finding_id,"proposal_id":proposal_id,"gap_id":"HGAP-SAME-CYCLE",
          "capability_key":"capability-coverage:freight-audit","project_ids":["PRJ-002"],
          "strategy_id":"STRAT:capability-conjunction-search-claim-tracing",
          "candidate_fingerprint":candidate_fingerprint,
          "repository_full_name":repository_full_name,"repository_id":repository_id,"revision":revision,
          "public":True,"rank_score":9,"rank_band":"HIGH","soft_signals":[],
          "inspection":{
            "tree_sha":"b"*40,"tree_truncated":False,"path_count":3,
            "source_path_count":1,"test_path_count":1,"docs_path_count":1,
            "keyword_hit_count":2,"source_keyword_hit_count":1,
            "test_keyword_hit_count":1,"docs_keyword_hit_count":0,
            "sample_paths":["src/freight_audit.py","tests/test_freight_audit.py"]
          },
          "provenance_refs":[f"github:{repository_full_name}@{revision}"]
        }
        proposals.append(proposal)
        findings.append(finding)
        origins[proposal_id]={
          "first_cycle_id":"hunt-origin",
          "first_cycle_receipt_hash":"sha256:"+str((index%7)+2)*64,
          "first_seen_at":"2026-09-27T20:10:00Z",
          "first_hunter_sequence":7,
          "last_cycle_id":"hunt-same-cycle",
          "last_cycle_receipt_hash":"sha256:"+str((index%7)+3)*64,
          "last_seen_at":"2026-09-27T20:20:00Z",
          "last_hunter_sequence":8
        }
    return {
      "schema_version":"1.0.0","state_id":"portfolio-hunter-proposal-state","sequence":8,
      "updated_at":"2026-09-27T20:20:00Z","cycle_id":"hunt-same-cycle",
      "cycle_receipt_hash":"sha256:"+"2"*64,
      "authority_class":"OBSERVE","rights_state":"NOT_GRANTED_BY_DISCOVERY",
      "proposals":proposals,"findings":findings,"origins":origins
    }


class ProposalProvider:
    def __init__(self,state=None):
        self.repository_ids={
            row["repository_full_name"]:row["repository_id"]
            for row in (state or proposal_state())["findings"]
        }

    def repository_metadata(self,full_name):
        return {
          "id":self.repository_ids[full_name],"full_name":full_name,"private":False,"default_branch":"main",
          "license":{"spdx_id":"MIT","name":"MIT License"}
        }

    def inspect_revision(self,candidate,revision):
        return {
          "revision":revision,"tree_sha":"b"*40,
          "paths":["src/freight_audit.py","tests/test_freight_audit.py","README.md"],
          "truncated":False,
        }

class DriftProvider(ProposalProvider):
    def inspect_revision(self,candidate,revision):
        result=super().inspect_revision(candidate,revision)
        result["tree_sha"]="c"*40
        return result


def primary_summary(state,receipts=None,executed=None):
    receipts=list(receipts or [])
    executed=list(executed or [])
    body={
      "schema_version":"1.0.0",
      "cycle_id":"wexec-primary",
      "finished_at":AT,
      "attempted_count":len(receipts),
      "completed_count":len(executed),
      "deferred_count":len(receipts)-len(executed),
      "remaining_queued_count":sum(1 for row in state["work_items"] if row["state"]=="QUEUED"),
      "authority_granted":False,
    }
    return {**body,"receipt_hash":hashv(body)}


class SameCycleContinuationTests(unittest.TestCase):
    def test_spare_capacity_executes_proposal_review_and_preserves_liveness_proof(self):
        state=load_state()
        pstate=proposal_state()
        updated,receipts,executed,summary,report,selected=run_same_cycle_continuation(
            state,
            runtime_state=bootstrap_state(now=AT),
            hunter_state=hunter_seed_state(),
            hunter_proposal_state=pstate,
            primary_receipts=[],
            primary_executed=[],
            primary_summary=primary_summary(state),
            max_items=2,
            at=AT,
            context_overrides={"hunter_provider":ProposalProvider()},
        )
        self.assertEqual(report["status"],"EXECUTED")
        self.assertEqual(report["selected_count"],1)
        self.assertEqual(report["attempted_count"],1)
        self.assertEqual(report["completed_count"],1)
        self.assertEqual(len(selected),1)
        self.assertTrue(is_hunter_proposal_continuation(selected[0]))
        self.assertEqual(receipts[0]["result_kind"],"HUNTER_PROPOSAL_PUBLIC_EVIDENCE_REVIEW")
        self.assertEqual(receipts[0]["status"],"SUCCESS")
        self.assertEqual(len(executed),1)
        self.assertEqual(summary["attempted_count"],1)
        self.assertEqual(summary["primary_attempted_count"],0)
        self.assertEqual(summary["continuation_attempted_count"],1)
        self.assertFalse(summary["authority_granted"])
        self.assertEqual(sum(1 for row in updated["work_items"] if row["state"]=="COMPLETE"),1)

        target=next(
            row for row in load_liveness_policy()["targets"]
            if row["workflow_name"]=="portfolio-autonomous-scheduler"
        )
        proof=verify_work_proof(target,summary,run_id=123)
        self.assertEqual(proof["status"],"VERIFIED_WORK")

    def test_second_serial_wave_uses_live_pattern_residual_capacity_without_widening_limits(self):
        state=load_state()
        pstate=proposal_state(count=3)
        primary_receipts=[
            {"execution_id":f"WEXEC-PRIMARY-{index}","status":"SUCCESS","receipt_hash":"sha256:"+str(index+1)*64}
            for index in range(5)
        ]
        primary_executed=[{"execution_id":row["execution_id"]} for row in primary_receipts]
        summary=primary_summary(state,primary_receipts,primary_executed)
        updated,receipts,executed,combined,report,selected=run_same_cycle_continuation(
            state,
            runtime_state=bootstrap_state(now=AT),
            hunter_state=hunter_seed_state(),
            hunter_proposal_state=pstate,
            primary_receipts=primary_receipts,
            primary_executed=primary_executed,
            primary_summary=summary,
            max_items=8,
            at=AT,
            context_overrides={"hunter_provider":ProposalProvider(pstate)},
        )

        self.assertEqual(report["status"],"EXECUTED")
        self.assertEqual(report["pass_count"],2)
        self.assertEqual(report["selected_count"],3)
        self.assertEqual(report["attempted_count"],3)
        self.assertEqual(report["completed_count"],3)
        self.assertEqual(report["deferred_count"],0)
        self.assertEqual(report["unused_capacity"],0)
        self.assertEqual([row["selected_count"] for row in report["passes"]],[2,1])
        self.assertTrue(all(row["selected_count"]<=2 for row in report["passes"]))
        self.assertEqual(len(set(report["proposal_ids"])),3)
        self.assertEqual(len(receipts),8)
        self.assertEqual(len(executed),8)
        self.assertEqual(combined["attempted_count"],8)
        self.assertEqual(combined["completed_count"],8)
        self.assertEqual(combined["deferred_count"],0)
        self.assertEqual(combined["continuation_attempted_count"],3)
        self.assertEqual(combined["continuation_pass_count"],2)
        self.assertEqual(combined["remaining_queued_count"],0)
        self.assertFalse(combined["authority_granted"])
        continuation_receipts=receipts[5:]
        self.assertTrue(all(row["result_kind"]=="HUNTER_PROPOSAL_PUBLIC_EVIDENCE_REVIEW" for row in continuation_receipts))
        self.assertTrue(all(row["result"]["rights_state"]=="UNKNOWN_REQUIRES_REVIEW" for row in continuation_receipts))
        self.assertTrue(all(row["result"]["reuse_authorized"] is False for row in continuation_receipts))
        self.assertTrue(all(row["result"]["implementation_authorized"] is False for row in continuation_receipts))
        self.assertTrue(all(row["result"]["code_execution_performed"] is False for row in continuation_receipts))
        self.assertTrue(all(row["result"]["downstream_mutation_performed"] is False for row in continuation_receipts))
        self.assertEqual(sum(1 for row in updated["work_items"] if row["state"]=="COMPLETE"),3)

        target=next(
            row for row in load_liveness_policy()["targets"]
            if row["workflow_name"]=="portfolio-autonomous-scheduler"
        )
        proof=verify_work_proof(target,combined,run_id=456)
        self.assertEqual(proof["status"],"VERIFIED_WORK")
        self.assertEqual(proof["metrics"]["attempted"],8)
        self.assertEqual(proof["metrics"]["completed"],8)
        self.assertEqual(proof["metrics"]["deferred"],0)

    def test_deferred_first_wave_stops_second_wave_and_does_not_retry(self):
        state=load_state()
        pstate=proposal_state(count=3)
        primary_receipts=[
            {"execution_id":f"WEXEC-PRIMARY-{index}","status":"SUCCESS","receipt_hash":"sha256:"+str(index+1)*64}
            for index in range(5)
        ]
        primary_executed=[{"execution_id":row["execution_id"]} for row in primary_receipts]
        summary=primary_summary(state,primary_receipts,primary_executed)
        updated,receipts,executed,combined,report,selected=run_same_cycle_continuation(
            state,
            runtime_state=bootstrap_state(now=AT),
            hunter_state=hunter_seed_state(),
            hunter_proposal_state=pstate,
            primary_receipts=primary_receipts,
            primary_executed=primary_executed,
            primary_summary=summary,
            max_items=8,
            at=AT,
            context_overrides={"hunter_provider":DriftProvider(pstate)},
        )
        self.assertEqual(report["status"],"EXECUTED")
        self.assertEqual(report["pass_count"],1)
        self.assertEqual(report["selected_count"],2)
        self.assertEqual(report["attempted_count"],2)
        self.assertEqual(report["completed_count"],0)
        self.assertEqual(report["deferred_count"],2)
        self.assertEqual(report["unused_capacity"],1)
        self.assertEqual(report["stop_reason"],"DEFERRED_CONTINUATION_STOPS_FURTHER_PASSES")
        self.assertEqual(len(receipts),7)
        self.assertEqual(len(executed),5)
        self.assertEqual(combined["attempted_count"],7)
        self.assertEqual(combined["completed_count"],5)
        self.assertEqual(combined["deferred_count"],2)
        self.assertEqual(combined["continuation_pass_count"],1)
        self.assertEqual(combined["remaining_queued_count"],2)
        self.assertEqual(len(selected),2)
        self.assertTrue(all(row["state"]=="QUEUED" for row in updated["work_items"] if row["source_ref"] in report["proposal_ids"]))

    def test_existing_primary_queued_work_prevents_same_cycle_retry(self):
        pstate=proposal_state()
        scheduled,receipt=schedule_cycle(
            load_state(),
            build_context(hunter_proposal_state=pstate),
            at=AT,
            candidate_filter=is_hunter_proposal_continuation,
            max_new_items=1,
        )
        self.assertEqual(len(receipt["selected_work"]),1)
        summary=primary_summary(scheduled)
        updated,receipts,executed,combined,report,selected=run_same_cycle_continuation(
            scheduled,
            runtime_state=bootstrap_state(now=AT),
            hunter_state=hunter_seed_state(),
            hunter_proposal_state=pstate,
            primary_receipts=[],
            primary_executed=[],
            primary_summary=summary,
            max_items=8,
            at=AT,
            context_overrides={"hunter_provider":ProposalProvider()},
        )
        self.assertEqual(report["status"],"SKIPPED_PRIMARY_QUEUE_NOT_DRAINED")
        self.assertEqual(receipts,[])
        self.assertEqual(executed,[])
        self.assertEqual(selected,[])
        self.assertEqual(combined,summary)
        self.assertEqual(updated,scheduled)

    def test_total_attempt_bound_cannot_be_widened(self):
        state=load_state()
        with self.assertRaises(Exception):
            run_same_cycle_continuation(
                state,
                runtime_state=bootstrap_state(now=AT),
                hunter_state=hunter_seed_state(),
                hunter_proposal_state=proposal_state(),
                primary_receipts=[],
                primary_executed=[],
                primary_summary=primary_summary(state),
                max_items=9,
                at=AT,
                context_overrides={"hunter_provider":ProposalProvider()},
            )


if __name__=="__main__":
    unittest.main()
