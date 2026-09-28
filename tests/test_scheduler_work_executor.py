import json
import unittest

from runtime.state import bootstrap_state
from scheduler.autonomous_scheduler import _work_packet, build_context, generate_candidates, load_state, schedule_cycle
from scheduler.work_executor import execute_cycle


AT = "2026-09-26T20:40:00Z"


def proposal_state():
    proposal={
      "schema_version":"1.0.0","proposal_id":"HEXP-TEST-INBOX","finding_id":"HFD-TEST-INBOX",
      "gap_id":"HGAP-TEST","project_ids":["PRJ-002"],"candidate_rank_score":8,
      "candidate_rank_band":"HIGH","candidate_soft_signals":[],
      "hypothesis":"bounded","baseline":"none","success_condition":"verify","failure_condition":"reject",
      "evidence_requirements":["Exact source revision","License/rights verification"],
      "cost_boundary":"read only","rollback":"none","candidate_rank_order":1
    }
    finding={
      "finding_id":"HFD-TEST-INBOX","proposal_id":"HEXP-TEST-INBOX","gap_id":"HGAP-TEST",
      "capability_key":"capability-coverage:freight-audit","project_ids":["PRJ-002"],
      "strategy_id":"STRAT:capability-conjunction-search-claim-tracing",
      "candidate_fingerprint":"sha256:"+"1"*64,
      "repository_full_name":"public/freight-audit","repository_id":123,"revision":"a"*40,
      "public":True,"rank_score":8,"rank_band":"HIGH","soft_signals":[],
      "inspection":{"tree_sha":"b"*40,"tree_truncated":False,"path_count":3,"source_path_count":1,"test_path_count":1,"docs_path_count":1,"keyword_hit_count":2,"source_keyword_hit_count":1,"test_keyword_hit_count":1,"docs_keyword_hit_count":0,"sample_paths":["src/freight_audit.py","tests/test_freight_audit.py"]},
      "provenance_refs":["github:public/freight-audit@"+"a"*40]
    }
    return {
      "schema_version":"1.0.0","state_id":"portfolio-hunter-proposal-state","sequence":8,
      "updated_at":"2026-09-27T06:30:00Z","cycle_id":"hunt-test","cycle_receipt_hash":"sha256:"+"2"*64,
      "authority_class":"OBSERVE","rights_state":"OPERATOR_ASSUMED",
      "proposals":[proposal],"findings":[finding]
    }


class ProposalProvider:
    def __init__(self,tree_sha="b"*40):
        self.tree_sha=tree_sha
        self.requests=0
    def repository_metadata(self,full_name):
        self.requests+=1
        return {
          "id":123,"full_name":full_name,"private":False,"default_branch":"main",
          "license":{"spdx_id":"MIT","name":"MIT License"}
        }
    def inspect_revision(self,candidate,revision):
        self.requests+=1
        return {
          "revision":revision,"tree_sha":self.tree_sha,
          "paths":["src/freight_audit.py","tests/test_freight_audit.py","README.md"],
          "truncated":False,
        }


class SchedulerWorkExecutorTests(unittest.TestCase):
    def _proposal_work(self):
        pstate=proposal_state()
        ctx=build_context(hunter_proposal_state=pstate)
        candidates,_=generate_candidates(ctx)
        candidate=next(c for c in candidates if c["source_ref"]=="HEXP-TEST-INBOX")
        state=load_state()
        work=_work_packet(candidate,AT)
        state["work_items"]=[work]
        return state,work,pstate

    def test_hunter_proposal_research_review_revalidates_exact_revision_and_rights_metadata(self):
        state,work,pstate=self._proposal_work()
        updated,receipts,executed,_=execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            max_items=1,
            at=AT,
            context_overrides={"hunter_proposal_state":pstate,"hunter_provider":ProposalProvider()},
        )
        self.assertEqual(updated["work_items"][0]["state"],"COMPLETE")
        self.assertEqual(receipts[0]["status"],"SUCCESS")
        self.assertEqual(receipts[0]["result_kind"],"HUNTER_PROPOSAL_PUBLIC_EVIDENCE_REVIEW")
        result=receipts[0]["result"]
        self.assertEqual(result["revision"],"a"*40)
        self.assertEqual(result["tree_sha"],"b"*40)
        self.assertEqual(result["license_spdx_id"],"MIT")
        self.assertEqual(result["capability_key"],"capability-coverage:freight-audit")
        self.assertEqual(result["rights_state"],"OPERATOR_ASSUMED")
        self.assertFalse(result["reuse_authorized"])
        self.assertFalse(result["implementation_authorized"])
        self.assertFalse(result["code_execution_performed"])
        self.assertFalse(result["downstream_mutation_performed"])
        self.assertEqual(len(executed),1)

    def test_hunter_proposal_tree_drift_defers_and_never_paints_green(self):
        state,work,pstate=self._proposal_work()
        updated,receipts,executed,_=execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            max_items=1,
            at=AT,
            context_overrides={"hunter_proposal_state":pstate,"hunter_provider":ProposalProvider(tree_sha="c"*40)},
        )
        self.assertEqual(updated["work_items"][0]["state"],"QUEUED")
        self.assertEqual(receipts[0]["status"],"DEFERRED")
        self.assertEqual(receipts[0]["result_kind"],"HUNTER_PROPOSAL_EXACT_REVISION_TREE_DRIFT")
        self.assertEqual(executed,[])

    def _single(self, work_type):
        state, receipt = schedule_cycle(load_state(), build_context(), at=AT)
        work = next(row for row in receipt["selected_work"] if row["work_type"] == work_type)
        state["work_items"] = [json.loads(json.dumps(work))]
        return state, work

    def test_success_is_only_path_to_complete(self):
        state, work = self._single("RESEARCH")
        def handler(row, ctx):
            return {
                "status": "SUCCESS",
                "result_kind": "TEST_PROOF",
                "evidence_refs": ["proof:test-success"],
                "result": {"source_ref": row["source_ref"]},
            }
        updated, receipts, executed, meta = execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            handlers={"RESEARCH": handler},
            max_items=1,
            at=AT,
        )
        row = updated["work_items"][0]
        self.assertEqual(row["state"], "COMPLETE")
        self.assertIn(work["fingerprint"], updated["completed_fingerprints"])
        self.assertEqual(receipts[0]["status"], "SUCCESS")
        self.assertEqual(len(executed), 1)
        self.assertEqual(meta["summary"]["completed_count"], 1)

    def test_handler_exception_requeues_and_never_paints_green(self):
        state, work = self._single("RESEARCH")
        def handler(row, ctx):
            raise RuntimeError("synthetic failure")
        updated, receipts, executed, meta = execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            handlers={"RESEARCH": handler},
            max_items=1,
            at=AT,
        )
        self.assertEqual(updated["work_items"][0]["state"], "QUEUED")
        self.assertNotIn(work["fingerprint"], updated["completed_fingerprints"])
        self.assertEqual(receipts[0]["status"], "DEFERRED")
        self.assertEqual(receipts[0]["result_kind"], "EXECUTION_ERROR")
        self.assertEqual(executed, [])
        self.assertEqual(meta["summary"]["completed_count"], 0)

    def test_explicit_defer_keeps_work_queued(self):
        state, work = self._single("INTEGRATION")
        def handler(row, ctx):
            return {
                "status": "DEFERRED",
                "result_kind": "WAITING_FOR_EVIDENCE",
                "evidence_refs": ["proof:not-ready"],
                "result": {},
            }
        updated, receipts, executed, _ = execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            handlers={"INTEGRATION": handler},
            max_items=1,
            at=AT,
        )
        self.assertEqual(updated["work_items"][0]["state"], "QUEUED")
        self.assertNotIn(work["fingerprint"], updated["completed_fingerprints"])
        self.assertEqual(receipts[0]["status"], "DEFERRED")
        self.assertEqual(executed, [])

    def test_unsupported_work_is_visible_and_not_completed(self):
        state, work = self._single("RESEARCH")
        updated, receipts, executed, _ = execute_cycle(
            state,
            runtime_state=bootstrap_state(now=AT),
            handlers={},
            max_items=1,
            at=AT,
        )
        self.assertEqual(updated["work_items"][0]["state"], "QUEUED")
        self.assertEqual(receipts[0]["result_kind"], "NO_EXECUTION_HANDLER")
        self.assertEqual(executed, [])


if __name__ == "__main__":
    unittest.main()
