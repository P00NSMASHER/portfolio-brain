import copy
import unittest

from brain.v11.owner_executor import configuration, verify, ExecutorError


class Provider:
    def __init__(self, config):
        self.config, self.reads = config, 0

    def get(self, repository, route):
        self.reads += 1
        item = self.config["acceptance"]
        if route == "pulls/881":
            return {"merged": True, "state": "closed",
                    "head": {"sha": item["candidate_sha"]},
                    "base": {"ref": "main"},
                    "merge_commit_sha": item["merge_sha"]}
        if route == "pulls/881/commits?per_page=100":
            return [{"sha": item["attributed_commit_sha"],
                     "commit": {"message": "repair [owner task " +
                                self.config["worker_id"] + "]"}}]
        if route.startswith("commits/"):
            return {"check_runs": [
                {"name": name, "head_sha": item["candidate_sha"],
                 "app": {"id": issuer}, "status": "completed",
                 "conclusion": "success"}
                for name, issuer in item["required_checks"].items()]}
        if route.startswith("actions/runs/"):
            run_id = int(route.rsplit("/", 1)[1])
            name = next(k for k, v in item["postmerge_runs"].items()
                        if v == run_id)
            return {"name": name, "head_branch": "main",
                    "head_sha": item["merge_sha"], "status": "completed",
                    "conclusion": "success"}
        raise AssertionError(route)


class ExecutorTests(unittest.TestCase):
    def test_exact_provider_lifecycle_is_live_verified(self):
        config = configuration()
        result = verify(Provider(config), config)
        self.assertEqual(result["status"],
                         "HISTORICAL_OWNER_DELIVERY_VERIFIED")
        self.assertEqual(result["provider_writes"], 0)
        self.assertFalse(result["brain_runtime_writer_credentials"])
        self.assertEqual(result["lifecycle"][-1], "LIVE_VERIFIED")
        self.assertEqual(len(result["receipt_sha256"]), 64)

    def test_wrong_merge_check_or_runtime_fails_closed(self):
        config = configuration()
        for mode in ("merge", "check", "runtime"):
            class Bad(Provider):
                def get(self, repository, route):
                    row = super().get(repository, route)
                    if mode == "merge" and route == "pulls/881":
                        row["merge_commit_sha"] = "0" * 40
                    if mode == "check" and route.startswith("commits/"):
                        row["check_runs"][0]["app"]["id"] = 1
                    if mode == "runtime" and route.startswith("actions/runs/"):
                        row["conclusion"] = "failure"
                    return row
            with self.subTest(mode=mode), self.assertRaises(ExecutorError):
                verify(Bad(config), config)


if __name__ == "__main__":
    unittest.main()
