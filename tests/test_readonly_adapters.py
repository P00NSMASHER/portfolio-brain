import copy
import unittest

from adapters.github_readonly import AdapterError, next_cursor, observe_repository

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

class ReadOnlyAdapterTests(unittest.TestCase):
    def test_unchanged_source_skips_compare(self):
        sha="a"*40
        fake=FakeGitHub(sha)
        receipt=observe_repository(BASE_ADAPTER,{"cursor_sha":sha},fetch_json=fake,observed_at="2026-09-25T16:00:00Z")
        self.assertEqual(receipt["status"],"UNCHANGED")
        self.assertEqual(receipt["network_reads"],1)
        self.assertEqual(len(fake.urls),1)

    def test_changed_source_compares_only_cursor_to_head(self):
        old="a"*40; new="b"*40
        fake=FakeGitHub(new,{"status":"ahead","ahead_by":2,"behind_by":0,"total_commits":2,"files":[{"filename":"a.py","status":"modified","additions":2,"deletions":1,"changes":3}]})
        receipt=observe_repository(BASE_ADAPTER,{"cursor_sha":old},fetch_json=fake,observed_at="2026-09-25T16:00:00Z")
        self.assertEqual(receipt["status"],"CHANGED")
        self.assertEqual(receipt["prior_sha"],old)
        self.assertEqual(receipt["current_sha"],new)
        self.assertEqual(receipt["network_reads"],2)
        self.assertIn(f"/compare/{old}...{new}",fake.urls[-1])
        self.assertEqual(receipt["compare"]["files"][0]["path"],"a.py")

    def test_blocked_adapter_performs_zero_network_reads(self):
        adapter=copy.deepcopy(BASE_ADAPTER)
        adapter.update({"enabled":False,"blocked_by":"BLK-001"})
        fake=FakeGitHub("b"*40)
        prior={"cursor_sha":"a"*40}
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
            next_cursor(receipt,{"cursor_sha":"a"*40})

    def test_receipt_hash_changes_if_delta_changes(self):
        old="a"*40; new="b"*40
        f1=FakeGitHub(new,{"status":"ahead","ahead_by":1,"behind_by":0,"total_commits":1,"files":[]})
        f2=FakeGitHub(new,{"status":"ahead","ahead_by":2,"behind_by":0,"total_commits":2,"files":[]})
        r1=observe_repository(BASE_ADAPTER,{"cursor_sha":old},fetch_json=f1,observed_at="2026-09-25T16:00:00Z")
        r2=observe_repository(BASE_ADAPTER,{"cursor_sha":old},fetch_json=f2,observed_at="2026-09-25T16:00:00Z")
        self.assertNotEqual(r1["receipt_hash"],r2["receipt_hash"])

if __name__=="__main__":
    unittest.main()
