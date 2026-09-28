import copy
import unittest
from unittest.mock import MagicMock, patch

from adapters.github_readonly import AdapterError, GitHubReadOnlyClient, next_cursor, observe_repository

BASE_ADAPTER={
 "schema_version":"1.0.0","adapter_id":"ADP-001","adapter_name":"example",
 "adapter_type":"GITHUB_REPOSITORY","repository_id":"REPO-001",
 "repository_full_name":"P00NSMASHER/example","project_ids":["PRJ-001"],
 "authority_class":"OBSERVE","enabled":True,
 "source_ref_policy":{"mode":"DEFAULT_BRANCH","ref":"main"},
 "data_classification":"PUBLIC",
 "cursor_policy":{"persist_exact_sha":True,"skip_unchanged":True,"compare_changed_only":True},
 "blocked_by":None
}

def compare_payload(old, new, *, ahead_by=1, files=None, **overrides):
    commits=[{"sha":f"{index:040x}"} for index in range(1,ahead_by)] + [{"sha":new}]
    payload={
        "status":"ahead","ahead_by":ahead_by,"behind_by":0,"total_commits":ahead_by,
        "base_commit":{"sha":old},"merge_base_commit":{"sha":old},
        "commits":commits,"files":files or [],
    }
    payload.update(overrides)
    return payload

class FakeGitHub:
    def __init__(self, head, compare=None):
        self.head=head; self.compare=compare or {}; self.urls=[]
    def __call__(self,url):
        self.urls.append(url)
        if "/commits/" in url:
            return {"sha":self.head}
        if "/compare/" in url:
            return self.compare
        raise AssertionError(url)

class TreeAwareFakeGitHub(FakeGitHub):
    def __init__(self, head, compare, trees):
        super().__init__(head,compare); self.trees=trees
    def __call__(self,url):
        if "/git/trees/" in url:
            self.urls.append(url)
            sha=url.split("/git/trees/",1)[1].split("?",1)[0]
            return self.trees[sha]
        return super().__call__(url)

def tree_entry(path, sha):
    return {"path":path,"mode":"100644","type":"blob","sha":sha}

class ReadOnlyAdapterTests(unittest.TestCase):
    def test_client_honors_shorter_runtime_timeout(self):
        response=MagicMock(); response.status=200; response.read.return_value=b'{"sha":"ok"}'
        response.__enter__.return_value=response
        with patch("adapters.github_readonly.urllib.request.urlopen",return_value=response) as open_url:
            self.assertEqual(GitHubReadOnlyClient().get_json(
                "https://api.github.com/repos/example/repo",timeout=3.5),{"sha":"ok"})
        self.assertEqual(open_url.call_args.kwargs["timeout"],3.5)

    def test_unchanged_source_skips_compare(self):
        sha="a"*40
        fake=FakeGitHub(sha)
        receipt=observe_repository(BASE_ADAPTER,{"source_ref":"main","cursor_sha":sha},fetch_json=fake,observed_at="2026-09-25T16:00:00Z")
        self.assertEqual(receipt["status"],"UNCHANGED")
        self.assertEqual(receipt["network_reads"],1)
        self.assertEqual(len(fake.urls),1)

    def test_changed_source_compares_only_cursor_to_head(self):
        old="a"*40; new="b"*40
        fake=FakeGitHub(new,compare_payload(old,new,ahead_by=2,files=[{"filename":"a.py","status":"modified","additions":2,"deletions":1,"changes":3}]))
        receipt=observe_repository(BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},fetch_json=fake,observed_at="2026-09-25T16:00:00Z")
        self.assertEqual(receipt["status"],"CHANGED")
        self.assertEqual(receipt["prior_sha"],old)
        self.assertEqual(receipt["current_sha"],new)
        self.assertEqual(receipt["network_reads"],2)
        self.assertIn(f"/compare/{old}...{new}",fake.urls[-1])
        self.assertEqual(receipt["compare"]["files"][0]["path"],"a.py")
        self.assertTrue(receipt["compare"]["files_complete"])
        self.assertEqual(receipt["source_ref"],"main")

    def test_blocked_adapter_performs_zero_network_reads(self):
        adapter=copy.deepcopy(BASE_ADAPTER)
        adapter.update({"enabled":False,"blocked_by":"BLK-001"})
        fake=FakeGitHub("b"*40)
        prior={"source_ref":"main","cursor_sha":"a"*40}
        receipt=observe_repository(adapter,prior,fetch_json=fake,observed_at="2026-09-25T16:00:00Z")
        self.assertEqual(receipt["status"],"BLOCKED")
        self.assertEqual(receipt["network_reads"],0)
        self.assertEqual(fake.urls,[])
        self.assertEqual(next_cursor(receipt,prior),prior)

    def test_disabled_without_blocker_fails_closed(self):
        adapter=copy.deepcopy(BASE_ADAPTER)
        adapter["enabled"]=False
        with self.assertRaises(AdapterError):
            observe_repository(adapter,None,fetch_json=FakeGitHub("b"*40),observed_at="2026-09-25T16:00:00Z")

    def test_adapter_must_be_observe_only(self):
        adapter=copy.deepcopy(BASE_ADAPTER)
        adapter["authority_class"]="MODIFY"
        with self.assertRaises(AdapterError):
            observe_repository(adapter,None,fetch_json=FakeGitHub("b"*40),observed_at="2026-09-25T16:00:00Z")

    def test_initialization_reads_head_only(self):
        sha="c"*40
        fake=FakeGitHub(sha)
        receipt=observe_repository(BASE_ADAPTER,None,fetch_json=fake,observed_at="2026-09-25T16:00:00Z")
        self.assertEqual(receipt["status"],"INITIALIZED")
        self.assertEqual(receipt["network_reads"],1)
        self.assertEqual(next_cursor(receipt,None)["cursor_sha"],sha)

    def test_cursor_advances_only_from_valid_observation(self):
        receipt={"status":"ERROR","current_sha":"b"*40}
        with self.assertRaises(AdapterError):
            next_cursor(receipt,{"source_ref":"main","cursor_sha":"a"*40})

    def test_receipt_hash_changes_if_delta_changes(self):
        old="a"*40; new="b"*40
        f1=FakeGitHub(new,compare_payload(old,new,ahead_by=1))
        f2=FakeGitHub(new,compare_payload(old,new,ahead_by=2))
        r1=observe_repository(BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},fetch_json=f1,observed_at="2026-09-25T16:00:00Z")
        r2=observe_repository(BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},fetch_json=f2,observed_at="2026-09-25T16:00:00Z")
        self.assertNotEqual(r1["receipt_hash"],r2["receipt_hash"])

    def test_cursor_is_bound_to_configured_source_ref(self):
        with self.assertRaisesRegex(AdapterError,"source_ref"):
            observe_repository(
                BASE_ADAPTER,
                {"source_ref":"release","cursor_sha":"a"*40},
                fetch_json=FakeGitHub("b"*40),
                observed_at="2026-09-25T16:00:00Z",
            )

    def test_next_cursor_preserves_observed_ref_instead_of_hardcoding_main(self):
        adapter=copy.deepcopy(BASE_ADAPTER)
        adapter["source_ref_policy"]["ref"]="release"
        sha="c"*40
        receipt=observe_repository(adapter,None,fetch_json=FakeGitHub(sha),observed_at="2026-09-25T16:00:00Z")
        self.assertEqual(next_cursor(receipt,None)["source_ref"],"release")

    def test_non_fast_forward_compare_fails_closed(self):
        old="a"*40; new="b"*40
        fake=FakeGitHub(new,compare_payload(old,new,status="diverged",behind_by=1))
        with self.assertRaisesRegex(AdapterError,"not a fast-forward"):
            observe_repository(BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},fetch_json=fake,observed_at="2026-09-25T16:00:00Z")

    def test_github_compare_file_cap_fails_closed_without_complete_tree_proof(self):
        old="a"*40; new="b"*40
        files=[{"filename":f"f{i}.py","status":"modified","additions":1,"deletions":0,"changes":1} for i in range(300)]
        fake=FakeGitHub(new,compare_payload(old,new,files=files))
        with self.assertRaisesRegex(AdapterError,"tree identity"):
            observe_repository(BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},fetch_json=fake,observed_at="2026-09-25T16:00:00Z")

    def test_github_compare_file_cap_uses_complete_tree_snapshot_proof(self):
        old="a"*40; new="b"*40; base_tree="c"*40; head_tree="d"*40
        files=[{"filename":f"capped-{i}.py","status":"modified","additions":1,"deletions":0,"changes":1} for i in range(300)]
        payload=compare_payload(
            old,new,files=files,
            base_commit={"sha":old,"commit":{"tree":{"sha":base_tree}}},
            commits=[{"sha":new,"commit":{"tree":{"sha":head_tree}}}],
        )
        base_entries=[tree_entry(f"old/f{i}.txt",f"{i+1:040x}") for i in range(700)]
        head_entries=[tree_entry("old/f0.txt",f"{1:040x}")]
        head_entries += [tree_entry(f"new/n{i}.txt",f"{1001+i:040x}") for i in range(12)]
        fake=TreeAwareFakeGitHub(new,payload,{
            base_tree:{"sha":base_tree,"truncated":False,"tree":base_entries},
            head_tree:{"sha":head_tree,"truncated":False,"tree":head_entries},
        })
        receipt=observe_repository(
            BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},
            fetch_json=fake,observed_at="2026-09-25T16:00:00Z",
        )
        comp=receipt["compare"]; proof=comp["tree_snapshot"]
        self.assertEqual(receipt["status"],"CHANGED")
        self.assertEqual(receipt["current_sha"],new)
        self.assertEqual(receipt["network_reads"],4)
        self.assertEqual(comp["comparison_method"],"GIT_TREE_SNAPSHOT")
        self.assertFalse(comp["files_complete"])
        self.assertEqual(comp["files"],[])
        self.assertEqual(comp["github_compare_file_count"],300)
        self.assertEqual(comp["changed_file_count"],711)
        self.assertTrue(proof["complete"])
        self.assertEqual(proof["base_leaf_count"],700)
        self.assertEqual(proof["head_leaf_count"],13)
        self.assertEqual(proof["removed_path_count"],699)
        self.assertEqual(proof["added_path_count"],12)
        self.assertEqual(proof["modified_path_count"],0)
        self.assertTrue(proof["changed_path_manifest_hash"].startswith("sha256:"))
        self.assertEqual(next_cursor(receipt,{"source_ref":"main","cursor_sha":old})["cursor_sha"],new)

    def test_github_compare_file_cap_rejects_truncated_tree_snapshot(self):
        old="a"*40; new="b"*40; base_tree="c"*40; head_tree="d"*40
        files=[{"filename":f"capped-{i}.py","status":"modified","additions":1,"deletions":0,"changes":1} for i in range(300)]
        payload=compare_payload(
            old,new,files=files,
            base_commit={"sha":old,"commit":{"tree":{"sha":base_tree}}},
            commits=[{"sha":new,"commit":{"tree":{"sha":head_tree}}}],
        )
        fake=TreeAwareFakeGitHub(new,payload,{
            base_tree:{"sha":base_tree,"truncated":True,"tree":[]},
            head_tree:{"sha":head_tree,"truncated":False,"tree":[]},
        })
        with self.assertRaisesRegex(AdapterError,"truncated"):
            observe_repository(
                BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},
                fetch_json=fake,observed_at="2026-09-25T16:00:00Z",
            )

    def test_heads_and_cursors_require_canonical_lowercase_sha(self):
        with self.assertRaisesRegex(AdapterError,"lowercase"):
            observe_repository(BASE_ADAPTER,None,fetch_json=FakeGitHub("A"*40),observed_at="2026-09-25T16:00:00Z")
        with self.assertRaisesRegex(AdapterError,"lowercase"):
            observe_repository(
                BASE_ADAPTER,{"source_ref":"main","cursor_sha":"z"*40},
                fetch_json=FakeGitHub("b"*40),observed_at="2026-09-25T16:00:00Z",
            )
        with self.assertRaisesRegex(AdapterError,"lowercase"):
            next_cursor({"status":"CHANGED","current_sha":"A"*40,"source_ref":"main"},None)

    def test_compare_response_is_bound_to_requested_base_and_head(self):
        old="a"*40; new="b"*40
        cases=(
            compare_payload(old,new,base_commit={"sha":"c"*40}),
            compare_payload(old,new,merge_base_commit={"sha":"c"*40}),
            compare_payload(old,new,commits=[{"sha":"c"*40}]),
        )
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaisesRegex(AdapterError,"requested|linear"):
                observe_repository(
                    BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},
                    fetch_json=FakeGitHub(new,payload),observed_at="2026-09-25T16:00:00Z",
                )

    def test_github_compare_commit_cap_fails_closed(self):
        old="a"*40; new="b"*40
        fake=FakeGitHub(new,compare_payload(old,new,ahead_by=250))
        with self.assertRaisesRegex(AdapterError,"250-commit"):
            observe_repository(BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},fetch_json=fake,observed_at="2026-09-25T16:00:00Z")

    def test_compare_file_metadata_is_validated_before_persistence(self):
        old="a"*40; new="b"*40
        invalid_files=(
            [{"filename":"../poison.json","status":"modified","additions":1,"deletions":0,"changes":1}],
            [{"filename":"a.py","status":"modified","additions":1,"deletions":1,"changes":1}],
            [
                {"filename":"a.py","status":"modified","additions":1,"deletions":0,"changes":1},
                {"filename":"a.py","status":"modified","additions":1,"deletions":0,"changes":1},
            ],
        )
        for files in invalid_files:
            with self.subTest(files=files), self.assertRaises(AdapterError):
                observe_repository(
                    BASE_ADAPTER,{"source_ref":"main","cursor_sha":old},
                    fetch_json=FakeGitHub(new,compare_payload(old,new,files=files)),
                    observed_at="2026-09-25T16:00:00Z",
                )

if __name__=="__main__":
    unittest.main()
