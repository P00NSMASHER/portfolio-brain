from legacy.workflow_archive import legacy_workflow_path
#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verification import upstream_readonly_probe as probe


class UpstreamReadonlyProbeTests(unittest.TestCase):
    def _source(self, integration_id: str) -> bytes:
        bodies = {
            "truth-engine": """
class TruthEngineError(ValueError):
    pass
class TruthEngine:
    def register_claim(self): pass
    def add_evidence(self): pass
    def evaluate(self): pass
    def rank_next_evidence(self): pass
    def request_evidence_acquisition(self): pass
    def get_receipt(self): pass
""",
            "value-memory": """
class ValueMemoryError(ValueError):
    pass
class ValueMemory:
    def register_memory(self): pass
    def observe_outcome(self): pass
    def verify_observation(self): pass
    def value_summary(self): pass
    def rank_memories(self): pass
""",
            "hunter-bridge": """
class HunterBridgeError(ValueError):
    pass
def compile_hunter_seeds(plan):
    return []
""",
            "production-learning-engine": """
class ExperienceKind: pass
class ValueMemory: pass
class FailureEvent: pass
class RepairCandidate: pass
def learn_value_memory(): pass
def assess_failure_for_repair(): pass
def assess_repair_candidate(): pass
def assess_peer_skill_transfer(): pass
def build_training_manifest(): pass
""",
        }
        return bodies[integration_id].lstrip().encode("utf-8")

    def _pin_source(self, spec, _repository, *, source_override=None):
        raw = source_override if source_override is not None else self._source(spec["integration_id"])
        return {
            "repository": "P00NSMASHER/github-value-hunt-ledger",
            "revision": "a" * 40,
            "path": f"fixtures/{spec['integration_id']}.py",
            "blob_sha": probe._git_blob_sha(raw),
            "pin_path": spec["pin_path"],
            "pin_schema_version": "1.0.0",
        }

    def test_pin_and_live_receipts_are_separate_positive_proofs(self):
        raws = {}
        def pin_source(spec, repository):
            row = self._pin_source(spec, repository)
            raws[row["path"]] = self._source(spec["integration_id"])
            return row
        def metadata(_repo, _rev, path):
            raw = raws[path]
            return {"type": "file", "path": path, "sha": probe._git_blob_sha(raw)}
        def raw(_repo, _rev, path):
            return raws[path]

        with tempfile.TemporaryDirectory() as td, patch.object(probe, "_pin_source", side_effect=pin_source):
            identity, live = probe.run_probe(
                output_dir=Path(td), at="2026-09-30T14:00:00Z",
                metadata_fetcher=metadata, raw_fetcher=raw,
            )
            self.assertEqual(identity["status"], "VERIFIED")
            self.assertEqual(live["status"], "LIVE")
            self.assertEqual(identity["proof_kind"], "PIN_BLOB_IDENTITY")
            self.assertEqual(live["proof_kind"], "LIVE_READ_ONLY_SOURCE_INTERFACE")
            self.assertNotEqual(identity["receipt_hash"], live["receipt_hash"])
            self.assertFalse(live["upstream_code_executed"])
            self.assertTrue(all(x["status"] == "VERIFIED" for x in identity["components"]))
            self.assertTrue(all(x["status"] == "LIVE" for x in live["components"]))

    def test_matching_pin_cannot_green_live_probe_when_raw_fetch_fails(self):
        raws = {}
        def pin_source(spec, repository):
            row = self._pin_source(spec, repository)
            raws[row["path"]] = self._source(spec["integration_id"])
            return row
        def metadata(_repo, _rev, path):
            return {"type": "file", "path": path, "sha": probe._git_blob_sha(raws[path])}
        def raw(_repo, _rev, _path):
            raise probe.UpstreamNetworkError("offline")

        with tempfile.TemporaryDirectory() as td, patch.object(probe, "_pin_source", side_effect=pin_source):
            identity, live = probe.run_probe(
                output_dir=Path(td), at="2026-09-30T14:00:00Z",
                metadata_fetcher=metadata, raw_fetcher=raw,
            )
            self.assertEqual(identity["status"], "VERIFIED")
            self.assertEqual(live["status"], "UNKNOWN")
            self.assertTrue(all(x["status"] == "UNKNOWN" for x in live["components"]))

    def test_exact_blob_with_interface_drift_is_blocked(self):
        broken = b"class Placeholder:\n    pass\n"
        def pin_source(spec, repository):
            return self._pin_source(spec, repository, source_override=broken)
        def metadata(_repo, _rev, path):
            return {"type": "file", "path": path, "sha": probe._git_blob_sha(broken)}
        def raw(_repo, _rev, _path):
            return broken

        with tempfile.TemporaryDirectory() as td, patch.object(probe, "_pin_source", side_effect=pin_source):
            identity, live = probe.run_probe(
                output_dir=Path(td), at="2026-09-30T14:00:00Z",
                metadata_fetcher=metadata, raw_fetcher=raw,
            )
            self.assertEqual(identity["status"], "VERIFIED")
            self.assertEqual(live["status"], "BLOCKED")
            self.assertTrue(all(x["reason"] == "UPSTREAM_INTERFACE_DRIFT" for x in live["components"]))

    def test_blob_identity_mismatch_blocks_live_probe_before_raw_use(self):
        raws = {}
        calls = []
        def pin_source(spec, repository):
            row = self._pin_source(spec, repository)
            raws[row["path"]] = self._source(spec["integration_id"])
            return row
        def metadata(_repo, _rev, path):
            return {"type": "file", "path": path, "sha": "b" * 40}
        def raw(*args):
            calls.append(args)
            raise AssertionError("raw fetch must not run after pin mismatch")

        with tempfile.TemporaryDirectory() as td, patch.object(probe, "_pin_source", side_effect=pin_source):
            identity, live = probe.run_probe(
                output_dir=Path(td), at="2026-09-30T14:00:00Z",
                metadata_fetcher=metadata, raw_fetcher=raw,
            )
            self.assertEqual(identity["status"], "BLOCKED")
            self.assertEqual(live["status"], "BLOCKED")
            self.assertEqual(calls, [])

    def test_contract_is_read_only_and_never_executes_upstream(self):
        contract = probe.load_contract()
        self.assertEqual(contract["network_policy"]["mode"], "READ_ONLY_PUBLIC_GITHUB")
        self.assertFalse(contract["network_policy"]["execute_upstream_code"])
        self.assertEqual(contract["network_policy"]["max_requests_per_run"], 8)
        self.assertEqual(
            set(contract["network_policy"]["allowed_hosts"]),
            {"api.github.com", "raw.githubusercontent.com"},
        )

    def test_live_workflow_has_read_only_repository_permission(self):
        workflow=(legacy_workflow_path(probe.ROOT/".github/workflows/upstream-readonly-integration.yml")).read_text()
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("actions: write", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("verification/upstream_readonly_probe.py", workflow)


if __name__ == "__main__":
    unittest.main()
