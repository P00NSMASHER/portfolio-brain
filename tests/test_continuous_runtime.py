import copy, json, os, tempfile, unittest\nfrom unittest.mock import patch
from pathlib import Path
from runtime.continuous_runtime import RuntimePolicyError, run
from runtime.state import bootstrap_state, validate_state
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
            return {"status":"ahead","ahead_by":1 if files else 0,"behind_by":0,
                    "total_commits":1 if files else 0,
                    "files":[{"filename":x,"status":"modified","additions":1,"deletions":0,"changes":1} for x in files]}
        raise AssertionError(url)

def current_heads():
    curs=json.loads((ROOT/"adapters/cursors/repositories.json").read_text())["repositories"]
    reg=json.loads((ROOT/"adapters/ADAPTER_REGISTRY.json").read_text())["adapters"]
    by={x["repository_id"]:x["repository_full_name"] for x in reg}
    return {by[rid]:item["cursor_sha"] for rid,item in curs.items() if rid!="REPO-006"}

class RuntimeTests(unittest.TestCase):
    def test_static_runtime_contract(self):
        result=validate_runtime()
        self.assertEqual(result["workflows"],5)
        self.assertEqual(result["model_calls"],0)
        self.assertEqual(result["downstream_writes"],0)

    def test_bootstrap_state_is_valid_and_blocked_repo_preserved(self):
        state=bootstrap_state(now="2026-09-25T17:00:00Z")
        validate_state(state)
        self.assertEqual(state["repositories"]["REPO-006"]["status"],"BLOCKED_HISTORICAL_ONLY")

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

    def test_daily_rebuild_is_deterministic_and_no_model_needed(self):
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
