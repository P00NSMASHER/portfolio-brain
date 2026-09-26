import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from cost_governor.cost_governor import load_state
from model_router.openai_executor import OpenAIExecutorError,execute_openai
from runtime.model_analysis import build_packet,run_model_analysis

ROOT=Path(__file__).resolve().parents[1]

def fake_transport(url,headers,payload,timeout):
    body=json.loads(payload.decode())
    model=body["model"]
    return {
      "id":"resp_"+model.replace(".","_").replace("-","_"),
      "output":[{"content":[{"type":"output_text","text":json.dumps({
        "summary":"synthetic","top_bottleneck":"test","next_actions":["a","b","c"],
        "experiment_improvement":"x","reuse_opportunity":"y","risks":["z"]
      })}]}],
      "usage":{"input_tokens":120,"output_tokens":40}
    }

def executor(request,text,state,**kwargs):
    return execute_openai(request,text,state,transport=fake_transport,**kwargs)

class ModelAnalysisTests(unittest.TestCase):
    def _runtime_out(self,root,mode):
        out=Path(root)/"runtime-out";out.mkdir()
        if mode=="daily":
            (out/"daily_learning_state.json").write_text(json.dumps({
              "repository_status_counts":{"CHANGED":0,"UNCHANGED":7,"INITIALIZED":0,"BLOCKED":1},
              "verified_memory_outcomes":0,"verified_graph_nodes":1,
              "transfer_assessment_ready_count":1,"verified_transfer_success_edge_candidates":0,
              "repair_task_count":0,"active_allocation_resource_count":4,
              "selected_experiment_id":"PEXP-X","selected_uncertainty_id":"UNC-X",
              "portfolio_learning_state_hash":"sha256:"+"a"*64,"snapshot_hash":"sha256:"+"b"*64
            }))
        else:
            (out/"weekly_portfolio_synthesis.json").write_text(json.dumps({
              "registered_projects":12,"active_or_declared_repository_cursors":7,"blocked_repository_cursors":1,
              "graph_nodes":25,"graph_edges":16,"verified_memory_outcomes":0,
              "changed_repositories_this_cycle":0,"snapshot_hash":"sha256:"+"c"*64
            }))
        return out

    def _cost_state(self,root):
        path=Path(root)/"cost.json"
        path.write_text(json.dumps(load_state()))
        return path

    def test_packet_contains_only_sanitized_operational_summary(self):
        with tempfile.TemporaryDirectory() as td:
            packet=build_packet("daily",self._runtime_out(td,"daily"))
        raw=json.dumps(packet)
        self.assertIn("selected_uncertainty",packet)
        self.assertNotIn("@",raw)
        self.assertNotIn("gmail_message_hash",raw)

    def test_missing_secret_blocks_without_changing_cost_state(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{},clear=True):
            cost=self._cost_state(td);before=cost.read_text()
            r=run_model_analysis("daily",runtime_out=self._runtime_out(td,"daily"),cost_state_path=cost,output_dir=Path(td)/"out",at="2026-09-26T15:00:00Z",executor=executor)
            self.assertEqual(r["status"],"BLOCKED_MISSING_CREDENTIAL")
            self.assertEqual(cost.read_text(),before)

    def test_daily_routes_terra_and_commits_usage(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"},clear=True):
            cost=self._cost_state(td)
            r=run_model_analysis("daily",runtime_out=self._runtime_out(td,"daily"),cost_state_path=cost,output_dir=Path(td)/"out",at="2026-09-26T15:00:00Z",executor=executor)
            self.assertEqual(r["status"],"SUCCESS")
            self.assertEqual((r["route"]["tier"],r["route"]["model_id"]),(2,"gpt-5.6-terra"))
            self.assertFalse(r["authority_granted"]);self.assertFalse(r["evidence_upgraded"])
            state=json.loads(cost.read_text())
            self.assertTrue(any(x["resource_kind"]=="MODEL_CALL" and x["status"]=="COMMITTED" for x in state["reservations"]))

    def test_weekly_routes_independent_sol(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"},clear=True):
            r=run_model_analysis("weekly",runtime_out=self._runtime_out(td,"weekly"),cost_state_path=self._cost_state(td),output_dir=Path(td)/"out",at="2026-09-26T15:00:00Z",executor=executor)
            self.assertEqual((r["route"]["tier"],r["route"]["model_id"]),(3,"gpt-5.6-sol"))
            self.assertNotEqual(r["route"]["model_id"],"gpt-5.6-terra")


    def test_transient_provider_throttle_is_deferred_not_fatal(self):
        def throttled(*args,**kwargs):
            raise OpenAIExecutorError("provider retry deferred",status_code=429,provider_code="slow_down",provider_type="rate_limit_error",retryable=True,retry_after=45.0)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"},clear=True):
            out=Path(td)/"out"
            r=run_model_analysis("daily",runtime_out=self._runtime_out(td,"daily"),cost_state_path=self._cost_state(td),output_dir=out,at="2026-09-26T15:00:00Z",executor=throttled)
            self.assertEqual(r["status"],"DEFERRED_PROVIDER_RETRY")
            self.assertTrue(r["retryable"])
            self.assertEqual(r["retry_after_seconds"],45.0)
            self.assertTrue((out/"daily_model_analysis_status.json").exists())

    def test_provider_quota_block_is_recorded_not_retried(self):
        def quota(*args,**kwargs):
            raise OpenAIExecutorError("quota",status_code=429,provider_code="credit_balance_exhausted",provider_type="insufficient_quota",retryable=False)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"},clear=True):
            r=run_model_analysis("daily",runtime_out=self._runtime_out(td,"daily"),cost_state_path=self._cost_state(td),output_dir=Path(td)/"out",at="2026-09-26T15:00:00Z",executor=quota)
            self.assertEqual(r["status"],"BLOCKED_PROVIDER_QUOTA")
            self.assertFalse(r["retryable"])

    def test_cost_duplicate_is_nonfatal_skip(self):
        def duplicate(*args,**kwargs):
            raise OpenAIExecutorError("cost duplicate",gate_status="DUPLICATE_SUPPRESSED",reason_codes=["EXISTING_RESERVATION_OR_CONSUMPTION"])
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"},clear=True):
            r=run_model_analysis("daily",runtime_out=self._runtime_out(td,"daily"),cost_state_path=self._cost_state(td),output_dir=Path(td)/"out",at="2026-09-26T15:00:00Z",executor=duplicate)
            self.assertEqual(r["status"],"SKIPPED_DUPLICATE_PACKET")


    def test_billing_not_active_is_explicit_nonfatal_status(self):
        def billing(*args,**kwargs):
            raise OpenAIExecutorError("billing",status_code=429,provider_code="billing_not_active",provider_type="billing_not_active",retryable=False)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"},clear=True):
            r=run_model_analysis("daily",runtime_out=self._runtime_out(td,"daily"),cost_state_path=self._cost_state(td),output_dir=Path(td)/"out",at="2026-09-26T15:00:00Z",executor=billing)
            self.assertEqual(r["status"],"BLOCKED_PROVIDER_BILLING")
            self.assertFalse(r["retryable"])

    def test_retryable_provider_attempt_advances_once_and_persists_accounting(self):
        calls=[]
        def deferred(url,headers,payload,timeout):
            calls.append(1)
            raise OpenAIExecutorError("slow",status_code=429,provider_code="slow_down",provider_type="rate_limit_error",retryable=True,retry_after=45.0)
        def governed(request,text,state,**kwargs):
            return execute_openai(request,text,state,transport=deferred,**kwargs)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"},clear=True):
            cost=self._cost_state(td);runtime=self._runtime_out(td,"daily");out=Path(td)/"out"
            first=run_model_analysis("daily",runtime_out=runtime,cost_state_path=cost,output_dir=out,at="2026-09-26T15:00:00Z",executor=governed)
            second=run_model_analysis("daily",runtime_out=runtime,cost_state_path=cost,output_dir=out,at="2026-09-26T15:01:00Z",executor=governed)
            third=run_model_analysis("daily",runtime_out=runtime,cost_state_path=cost,output_dir=out,at="2026-09-26T15:02:00Z",executor=governed)
            self.assertEqual([first["provider_attempt"],second["provider_attempt"]],[1,2])
            self.assertEqual(third["status"],"SKIPPED_DUPLICATE_PACKET")
            self.assertEqual(len(calls),2)
            state=json.loads(cost.read_text())
            rows=[r for r in state["reservations"] if r["resource_kind"]=="MODEL_CALL"]
            self.assertEqual([r["attempt"] for r in rows],[1,2])
            self.assertEqual(sum(r["actual_usage"]["api_calls"] for r in rows),2)

    def test_analysis_output_is_advisory_only(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_MODEL_API_KEY":"test-key"},clear=True):
            out=Path(td)/"out"
            r=run_model_analysis("daily",runtime_out=self._runtime_out(td,"daily"),cost_state_path=self._cost_state(td),output_dir=out,at="2026-09-26T15:00:00Z",executor=executor)
            body=json.loads((out/"daily_model_analysis.json").read_text())
            self.assertEqual(body["receipt"]["authority_granted"],False)
            self.assertEqual(body["receipt"]["evidence_upgraded"],False)
            self.assertEqual(r["analysis_text"].startswith("{"),True)

if __name__=="__main__":unittest.main()
