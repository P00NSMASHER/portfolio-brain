import json
import tempfile
import unittest
from pathlib import Path

from verification.upstream_live_integration import (
    ROOT,
    UpstreamIntegrationError,
    _pin_files,
    _primary_file,
    interface_check,
    run_probe,
)


PRIMARY_SOURCE = {
    "truth-engine": """
VALID_VERDICTS = set()
VALID_FINDING_STATUSES = set()
class TruthEngineError(ValueError):
    pass
class TruthEngine:
    def register_claim(self):
        pass
""",
    "value-memory": """
class ValueMemoryError(ValueError):
    pass
class ValueMemory:
    def register_memory(self):
        pass
    def observe_outcome(self):
        pass
    def verify_observation(self):
        pass
""",
    "hunter-bridge": """
PUBLIC_TECHNICAL_SOURCE_TYPES = set()
class HunterBridgeError(ValueError):
    pass
def compile_hunter_seeds(plan):
    return []
""",
    "production-learning-engine": """
class ValueConfig:
    pass
class MemoryCandidate:
    pass
class ExperienceKind:
    pass
class ValueMemory:
    def observe(self):
        pass
    def update(self):
        pass
    def rank(self):
        pass
    def to_state(self):
        pass
def contextual_memory_key(base_key, objective):
    return None
""",
}


class FakeClient:
    def __init__(self, entries, *, head="f" * 40, pinned_bad=None, head_bad=None, head_text=None):
        self.entries = entries
        self.head = head
        self.pinned_bad = pinned_bad
        self.head_bad = head_bad
        self.head_text = head_text or {}
        self.network_reads = 0

    def branch_head(self, repository, branch):
        return self.head

    def file(self, repository, path, ref):
        row = self.entries[(repository, path)]
        if ref == row["revision"]:
            sha = "0" * 40 if path == self.pinned_bad else row["blob_sha"]
            return {"sha": sha, "text": row["text"]}
        if ref == self.head:
            sha = "1" * 40 if path == self.head_bad else row["blob_sha"]
            return {"sha": sha, "text": self.head_text.get(path, row["text"])}
        raise AssertionError(f"unexpected ref {ref}")


def make_entries():
    config = json.loads((ROOT / "verification" / "UPSTREAM_LIVE_TARGETS.json").read_text())
    entries = {}
    primary_paths = {}
    for target in config["targets"]:
        pin = json.loads((ROOT / target["pin_path"]).read_text())
        rows = _pin_files(pin)
        primary = _primary_file(rows, target["primary"])
        primary_paths[target["target_id"]] = primary["path"]
        for row in rows:
            entries[(pin["source_repository"], row["path"])] = {
                "revision": pin["source_revision"],
                "blob_sha": row["blob_sha"],
                "text": PRIMARY_SOURCE[target["target_id"]]
                if row["path"] == primary["path"]
                else "x = 1\n",
            }
    return entries, primary_paths


class UpstreamLiveIntegrationTests(unittest.TestCase):
    def test_repository_head_may_advance_when_all_target_blobs_and_interfaces_are_stable(self):
        entries, _ = make_entries()
        receipt = run_probe(FakeClient(entries), generated_at="2026-09-30T14:00:00Z")
        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(receipt["separate_proofs"]["pin_blob_identity"])
        self.assertTrue(receipt["separate_proofs"]["live_readonly_integration"])
        for target in receipt["targets"]:
            self.assertEqual(target["pin_identity_proof"]["status"], "PASS")
            self.assertEqual(target["live_readonly_integration_proof"]["status"], "PASS")
            self.assertTrue(target["live_readonly_integration_proof"]["repository_head_advanced"])
            self.assertEqual(
                target["live_readonly_integration_proof"]["drift_class"],
                "REPOSITORY_HEAD_ADVANCED_TARGETS_STABLE",
            )

    def test_pinned_blob_identity_mismatch_fails_closed(self):
        entries, primary = make_entries()
        bad = primary["truth-engine"]
        receipt = run_probe(
            FakeClient(entries, pinned_bad=bad),
            generated_at="2026-09-30T14:00:00Z",
        )
        self.assertEqual(receipt["status"], "BLOCKED")
        truth = next(x for x in receipt["targets"] if x["target_id"] == "truth-engine")
        self.assertIn("PIN_IDENTITY_MISMATCH", truth["blocked_reasons"])
        self.assertEqual(truth["pin_identity_proof"]["status"], "BLOCKED")

    def test_live_target_blob_drift_is_not_mistaken_for_a_healthy_pin(self):
        entries, primary = make_entries()
        bad = primary["hunter-bridge"]
        receipt = run_probe(
            FakeClient(entries, head_bad=bad),
            generated_at="2026-09-30T14:00:00Z",
        )
        self.assertEqual(receipt["status"], "BLOCKED")
        hunter = next(x for x in receipt["targets"] if x["target_id"] == "hunter-bridge")
        self.assertEqual(hunter["pin_identity_proof"]["status"], "PASS")
        self.assertIn("TARGET_BLOB_DRIFT", hunter["blocked_reasons"])
        self.assertEqual(
            hunter["live_readonly_integration_proof"]["drift_class"],
            "TARGET_BLOB_DRIFT",
        )

    def test_interface_schema_drift_is_explicit(self):
        entries, primary = make_entries()
        bad = primary["production-learning-engine"]
        receipt = run_probe(
            FakeClient(
                entries,
                head_bad=bad,
                head_text={bad: "class ValueMemory:\n    pass\n"},
            ),
            generated_at="2026-09-30T14:00:00Z",
        )
        learning = next(
            x for x in receipt["targets"]
            if x["target_id"] == "production-learning-engine"
        )
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertIn("INTERFACE_SCHEMA_DRIFT", learning["blocked_reasons"])
        self.assertEqual(
            learning["live_readonly_integration_proof"]["head_interface"]["status"],
            "BLOCKED",
        )

    def test_unsupported_target_config_schema_is_rejected(self):
        entries, _ = make_entries()
        config = json.loads((ROOT / "verification" / "UPSTREAM_LIVE_TARGETS.json").read_text())
        config["schema_version"] = "2.0.0"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "targets.json"
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(UpstreamIntegrationError, "schema_version"):
                run_probe(FakeClient(entries), targets_path=path)

    def test_interface_check_reports_missing_methods(self):
        result = interface_check(
            "class ValueMemory:\n    def observe(self):\n        pass\n",
            {
                "classes": ["ValueMemory"],
                "functions": [],
                "names": [],
                "methods": {"ValueMemory": ["observe", "rank"]},
            },
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["missing"], ["method:ValueMemory.rank"])


if __name__ == "__main__":
    unittest.main()
