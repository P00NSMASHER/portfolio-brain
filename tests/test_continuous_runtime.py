import copy, json, os, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError, URLError
from runtime.continuous_runtime import RequestBudget, RuntimePolicyError, run
from runtime.state import RuntimeStateError, advance_cycle, bootstrap_state, canonical_hash, validate_state
from runtime.validate_runtime import validate_runtime

ROOT=Path(__file__).resolve().parents[1]

class FakeGitHub:
    def __init__(self, heads, changed=None):
        self.heads=heads; self.changed=changed or {}; self.urls=[]
    def __call__(self,url):
        self.urls.append(url)
        if "/commits/" in url:
            repo=url.split("/repos/",1)[1].split("/commits/",1)[0]
            return {"sha":self.heads[repo]}
        if "/compare/" in url:
            repo=url.split("/repos/",1)[1].split("/compare/",1)[0]
            files=self.changed.get(repo,[])
            pair=url.rsplit("/compare/",1)[1]
            old,new=pair.split("...",1)
            return {"status":"ahead","ahead_by":1 if files else 0,"behind_by":0,
                    "total_commits":1 if files else 0,
                    "base_commit":{"sha":old},"merge_base_commit":{"sha":old},
                    "commits":[{"sha":new}] if files else [],
                    "files":[{"filename":x,"status":"modified","additions":1,"deletions":0,"changes":1} for x in files]}
        raise AssertionError(url)

def current_heads():
    curs=json.loads((ROOT/"adapters/cursors/repositories.json").read_text())["repositories"]
    reg=json.loads((ROOT/"adapters/ADAPTER_REGISTRY.json").read_text())["adapters"]
    by={x["repository_id"]:x["repository_full_name"] for x in reg}
    return {by[rid]:item["cursor_sha"] for rid,item in curs.items() if rid!="REPO-006"}

class RuntimeTests(unittest.TestCase):
    def cycle_receipt(self,state,observation,*,finished_at="2026-09-25T18:00:00Z"):
        receipt={
            "schema_version":"1.0.0","cycle_id":"cycle-"+"1"*24,"mode":"observe",
            "started_at":finished_at,"finished_at":finished_at,"status":"PASS","reason":None,
            "observations":[observation],"api_requests":1,
        }
        receipt["receipt_hash"]=canonical_hash(receipt)
        return receipt

    def test_permanent_github_error_is_not_retried(self):
        calls=[]
        def missing(url):
            calls.append(url)
            raise HTTPError(url,404,"not found",None,None)
        budget=RequestBudget(missing,limit=10,retries=2,backoff=0)
        with self.assertRaises(RuntimePolicyError):budget("https://api.github.com/repos/example/missing")
        self.assertEqual(len(calls),1)
        self.assertEqual(budget.used,1)

    def test_transient_github_error_uses_bounded_retry(self):
        calls=[]
        def temporary(url):
            calls.append(url)
            if len(calls)<3:raise URLError("temporary network failure")
            return {"sha":"f"*40}
        budget=RequestBudget(temporary,limit=10,retries=2,backoff=0)
        self.assertEqual(budget("https://api.github.com/repos/example/repo"),{"sha":"f"*40})
        self.assertEqual(len(calls),3)
        self.assertEqual(budget.used,3)

    def test_github_server_error_uses_bounded_retry(self):
        calls=[]
        def unavailable(url):
            calls.append(url)
            if len(calls)<2:raise HTTPError(url,503,"service unavailable",None,None)
            return {"sha":"e"*40}
        budget=RequestBudget(unavailable,limit=10,retries=2,backoff=0)
        self.assertEqual(budget("https://api.github.com/repos/example/repo"),{"sha":"e"*40})
        self.assertEqual(len(calls),2)
        self.assertEqual(budget.used,2)

    def test_runtime_deadline_stops_requests_before_budget_exhaustion(self):
        now=[10.0]; calls=[]
        def slow(url):
            calls.append(url); now[0]+=6
            return {"sha":"d"*40}
        budget=RequestBudget(slow,limit=10,retries=2,backoff=0,deadline=15,clock=lambda:now[0])
        with self.assertRaisesRegex(RuntimePolicyError,"time budget"):
            budget("https://api.github.com/repos/example/repo")
        self.assertEqual(len(calls),1)
        self.assertEqual(budget.used,1)

    def test_runtime_deadline_prevents_retry_backoff_overrun(self):
        now=[10.0]; calls=[]; sleeps=[]
        def temporary(url):
            calls.append(url); now[0]+=1
            raise URLError("temporary network failure")
        budget=RequestBudget(temporary,limit=10,retries=2,backoff=2,deadline=12,
                             clock=lambda:now[0],sleep=sleeps.append)
        with self.assertRaisesRegex(RuntimePolicyError,"time budget"):
            budget("https://api.github.com/repos/example/repo")
        self.assertEqual(len(calls),1)
        self.assertEqual(sleeps,[])

    def test_static_runtime_contract(self):
        result=validate_runtime()
        self.assertEqual(result["workflows"],5)
        self.assertEqual(result["model_calls"],0)
        self.assertEqual(result["governed_daily_model_calls"],1)
        self.assertEqual(result["governed_weekly_model_calls"],1)
        self.assertEqual(result["downstream_writes"],0)

    def test_bootstrap_state_is_valid_and_blocked_repo_preserved(self):
        state=bootstrap_state(now="2026-09-25T17:00:00Z")
        validate_state(state)
        self.assertEqual(state["repositories"]["REPO-006"]["status"],"BLOCKED_HISTORICAL_ONLY")

    def test_runtime_state_rejects_noncanonical_cursor_sha(self):
        state=bootstrap_state(now="2026-09-25T17:00:00Z")
        state["repositories"]["REPO-001"]["cursor_sha"]="A"*40
        with self.assertRaisesRegex(RuntimeStateError,"lowercase"):
            validate_state(state)

    def test_stale_observation_cannot_roll_durable_cursor_backward(self):
        state=bootstrap_state(now="2026-09-25T17:00:00Z")
        rid="REPO-001"; durable_sha=state["repositories"][rid]["cursor_sha"]
        observation={
            "repository_id":rid,"status":"CHANGED","source_ref":"main",
            "prior_sha":"a"*40,"current_sha":"b"*40,
            "observed_at":"2026-09-25T18:00:00Z",
        }
        with self.assertRaisesRegex(RuntimeStateError,"durable cursor"):
            advance_cycle(state,self.cycle_receipt(state,observation))
        self.assertEqual(state["repositories"][rid]["cursor_sha"],durable_sha)

    def test_cycle_timestamp_cannot_roll_freshness_backward(self):
        state=bootstrap_state(now="2026-09-25T19:00:00Z")
        rid="REPO-001"; sha=state["repositories"][rid]["cursor_sha"]
        observation={
            "repository_id":rid,"status":"UNCHANGED","source_ref":"main",
            "prior_sha":sha,"current_sha":sha,"observed_at":"2026-09-25T18:00:00Z",
        }
        with self.assertRaisesRegex(RuntimeStateError,"roll durable state backward"):
            advance_cycle(state,self.cycle_receipt(state,observation,finished_at="2026-09-25T18:00:00Z"))

    def test_observation_timestamp_must_match_cycle(self):
        state=bootstrap_state(now="2026-09-25T17:00:00Z")
        rid="REPO-001"; sha=state["repositories"][rid]["cursor_sha"]
        observation={
            "repository_id":rid,"status":"UNCHANGED","source_ref":"main",
            "prior_sha":sha,"current_sha":sha,"observed_at":"2026-09-25T17:30:00Z",
        }
        with self.assertRaisesRegex(RuntimeStateError,"timestamp is not bound"):
            advance_cycle(state,self.cycle_receipt(state,observation))

    def test_tampered_cycle_receipt_cannot_mutate_state(self):
        state=bootstrap_state(now="2026-09-25T17:00:00Z")
        rid="REPO-001"; sha=state["repositories"][rid]["cursor_sha"]
        observation={
            "repository_id":rid,"status":"UNCHANGED","source_ref":"main",
            "prior_sha":sha,"current_sha":sha,"observed_at":"2026-09-25T18:00:00Z",
        }
        receipt=self.cycle_receipt(state,observation);receipt["api_requests"]=99
        with self.assertRaisesRegex(RuntimeStateError,"hash mismatch"):
            advance_cycle(state,receipt)
        self.assertEqual(state["sequence"],0)

    def test_restored_state_rejects_forged_cycle_history(self):
        state=bootstrap_state(now="2026-09-25T18:00:00Z")
        state["sequence"]=1;state["last_cycle_id"]="cycle-"+"1"*24
        state["recent_cycles"]=[{
            "cycle_id":state["last_cycle_id"],"mode":"sync","finished_at":state["updated_at"],
            "status":"PASS","receipt_hash":"sha256:not-a-digest",
        }]
        with self.assertRaisesRegex(RuntimeStateError,"receipt hash invalid"):
            validate_state(state)

    def test_restored_state_rejects_history_identity_mismatch(self):
        state=bootstrap_state(now="2026-09-25T18:00:00Z")
        state["sequence"]=1;state["last_cycle_id"]="cycle-"+"2"*24
        state["recent_cycles"]=[{
            "cycle_id":"cycle-"+"1"*24,"mode":"sync","finished_at":state["updated_at"],
            "status":"PASS","receipt_hash":"sha256:"+"2"*64,
        }]
        with self.assertRaisesRegex(RuntimeStateError,"last cycle id"):
            validate_state(state)

    def test_hourly_sync_skips_blocked_and_updates_changed_cursor(self):
        heads=current_heads()
        heads["P00NSMASHER/StarBlox"]="f"*40
        fake=FakeGitHub(heads,{"P00NSMASHER/StarBlox":["src/App.jsx"]})
        with tempfile.TemporaryDirectory() as td:
            receipt=run("sync",state_path=Path(td)/"missing.json",output_dir=Path(td)/"out",
                        fetch_json=fake,forced_now="2026-09-25T17:00:00Z")
            state=json.loads((Path(td)/"out"/"runtime_state.json").read_text())
        by={x["repository_id"]:x for x in receipt["observations"]}
        self.assertEqual(by["REPO-002"]["status"],"CHANGED")
        self.assertEqual(state["repositories"]["REPO-002"]["cursor_sha"],"f"*40)
        self.assertEqual(by["REPO-006"]["network_reads"],0)
        self.assertFalse(any("permitplate-state" in u for u in fake.urls))

    def test_event_observe_targets_only_one_repo(self):
        fake=FakeGitHub(current_heads())
        with tempfile.TemporaryDirectory() as td:
            receipt=run("observe",state_path=Path(td)/"none.json",output_dir=Path(td)/"out",
                        target_repository_id="REPO-008",fetch_json=fake,forced_now="2026-09-25T17:00:00Z")
        self.assertEqual([x["repository_id"] for x in receipt["observations"]],["REPO-008"])
        self.assertEqual(len(fake.urls),1)

    def test_same_inputs_generate_same_cycle_id(self):
        ids=[]
        for _ in range(2):
            fake=FakeGitHub(current_heads())
            with tempfile.TemporaryDirectory() as td:
                r=run("sync",state_path=Path(td)/"none.json",output_dir=Path(td)/"out",
                      fetch_json=fake,forced_now="2026-09-25T17:00:00Z")
                ids.append(r["cycle_id"])
        self.assertEqual(ids[0],ids[1])

    def test_environment_kill_switch_exits_cleanly_with_state(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"PORTFOLIO_RUNTIME_DISABLED":"true"}):
            receipt=run("sync",state_path=Path(td)/"none.json",output_dir=Path(td)/"out",
                        fetch_json=FakeGitHub(current_heads()),forced_now="2026-09-25T17:00:00Z")
            self.assertEqual(receipt["status"],"DISABLED")
            state=json.loads((Path(td)/"out"/"runtime_state.json").read_text())
            self.assertEqual(state["sequence"],0)

    def test_daily_deterministic_core_rebuild_remains_model_independent(self):
        fake=FakeGitHub(current_heads())
        with tempfile.TemporaryDirectory() as td:
            run("daily",state_path=Path(td)/"none.json",output_dir=Path(td)/"out",
                fetch_json=fake,forced_now="2026-09-25T17:00:00Z")
            snap=json.loads((Path(td)/"out"/"daily_learning_state.json").read_text())
        self.assertIn("snapshot_hash",snap)
        self.assertEqual(snap["verified_memory_outcomes"],0)
        self.assertEqual(snap["runtime_sequence_before_rebuild"],1)

    def test_weekly_synthesis_contains_portfolio_counts(self):
        fake=FakeGitHub(current_heads())
        with tempfile.TemporaryDirectory() as td:
            run("weekly",state_path=Path(td)/"none.json",output_dir=Path(td)/"out",
                fetch_json=fake,forced_now="2026-09-25T17:00:00Z")
            snap=json.loads((Path(td)/"out"/"weekly_portfolio_synthesis.json").read_text())
        self.assertEqual(snap["registered_projects"],12)
        self.assertEqual(snap["graph_nodes"],25)

    def test_changed_file_budget_fails_closed(self):
        heads=current_heads(); heads["P00NSMASHER/StarBlox"]="e"*40
        fake=FakeGitHub(heads,{"P00NSMASHER/StarBlox":[f"f{i}" for i in range(501)]})
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimePolicyError):
                run("sync",state_path=Path(td)/"none.json",output_dir=Path(td)/"out",
                    fetch_json=fake,forced_now="2026-09-25T17:00:00Z")

    def test_restored_state_advances_sequence(self):
        state=bootstrap_state(now="2026-09-25T16:00:00Z"); state["sequence"]=9
        fake=FakeGitHub(current_heads())
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"state.json"; path.write_text(json.dumps(state))
            run("sync",state_path=path,output_dir=Path(td)/"out",
                fetch_json=fake,forced_now="2026-09-25T17:00:00Z")
            new=json.loads((Path(td)/"out"/"runtime_state.json").read_text())
        self.assertEqual(new["sequence"],10)

if __name__=="__main__": unittest.main()
