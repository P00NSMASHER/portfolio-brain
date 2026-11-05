"""Fail-closed cycle accounting and evidence-link funnel."""
import json
from pathlib import Path
import tempfile
import unittest

from brain.v11 import cycle_evidence, value_funnel


SHA = "a" * 40
BEFORE = "b" * 40
AFTER = "c" * 40
HASH = "d" * 64


class CycleAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = {
            "delivery.json": {"schema_version": 2, "source_sha": SHA,
                              "workflow": "brain-cycle-v2", "run_id": "123",
                              "run_attempt": "1", "publication_verified": True,
                              "state_commit": AFTER, "state_parent": BEFORE},
            "state-restoration.json": {"storage_format": "sqlite-zlib-chunks-v1",
                                       "raw_size": 1000, "compressed_size": 200,
                                       "restored": True},
            "state-publication.json": {"storage_format": "sqlite-zlib-chunks-v1",
                                       "raw_size": 1200, "compressed_size": 250,
                                       "published": False},
            "state-capacity.json": {
                "status": "VERIFIED_PRODUCTION_CAPACITY_ENVELOPE_PASS",
                "raw_size": 1200, "compressed_size": 250,
                "raw_headroom_bytes": 1800, "compressed_headroom_bytes": 750,
                "verified_raw_capacity_bytes": 3000,
                "verified_compressed_capacity_bytes": 1000,
                "published": False},
            "state-maintenance.json": {"storage_pressure": {
                "raw_bytes": 1200, "compressed_bytes": 250,
                "capacity_warning": "LOW_VERIFIED_HEADROOM", "reports": 40}},
            "v8-engineering.json": {"source_sha": SHA, "production_accepted": False,
                                    "owner_jobs": [{}, {}]},
            "research/report.json": {"source_sha": SHA, "operation": {
                "name": "research", "candidates_observed": 2,
                "unchanged_events_coalesced": 1}},
            "upgrade/report.json": {"source_sha": SHA, "status": "COOLDOWN"},
        }
        self.write()

    def write(self):
        for name, data in self.data.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))

    def inspect(self):
        return cycle_evidence.inspect(self.root, source_sha=SHA, run_id=123)

    def test_exact_original_delivery_and_growth(self):
        row = self.inspect()
        self.assertEqual(row["state_growth_raw_bytes"], 200)
        self.assertEqual(row["state_growth_compressed_bytes"], 50)
        self.assertEqual(row["candidate_events_persisted"], 1)
        self.assertIsNone(row["verified_novel_candidates"])
        self.assertEqual(row["unchanged_source_events_coalesced"], 1)
        self.assertEqual(row["unreleased_owner_jobs"], 2)
        self.assertTrue(row["knowledge_cooldown_observed"])
        self.assertIsNone(row["real_world_value_verified"])

    def test_reject_forged_release_or_mismatched_pub(self):
        self.data["delivery.json"]["publication_verified"] = False
        self.write()
        with self.assertRaisesRegex(cycle_evidence.CycleEvidenceError, "DELIVERY"):
            self.inspect()
        self.data["delivery.json"]["publication_verified"] = True
        self.data["state-capacity.json"]["raw_size"] = 1199
        self.write()
        with self.assertRaisesRegex(cycle_evidence.CycleEvidenceError, "CAPACITY"):
            self.inspect()

    def test_no_freshness_from_missing_research(self):
        (self.root / "research/report.json").unlink()
        self.assertEqual(self.inspect()["activity_classification"],
                         "RESEARCH_ACTIVITY_UNKNOWN")

    def test_no_symlink_or_replay_admission(self):
        (self.root / "delivery.json").unlink()
        (self.root / "delivery.json").symlink_to("state-restoration.json")
        with self.assertRaisesRegex(cycle_evidence.CycleEvidenceError, "SYMLINK"):
            self.inspect()
        with self.assertRaisesRegex(cycle_evidence.CycleEvidenceError, "ORIGIN"):
            cycle_evidence.inspect(self.root, source_sha=SHA, run_id=123,
                                   run_attempt=2)

    def test_no_duplicate_keys(self):
        (self.root / "delivery.json").write_text('{"schema_version":2,"schema_version":2}')
        with self.assertRaisesRegex(cycle_evidence.CycleEvidenceError, "INVALID_JSON"):
            self.inspect()


class FunnelTests(unittest.TestCase):
    def data(self):
        src = {"code_sha256": HASH, "source_ref": "https://github.com/a/b/blob/a",
               "head_sha": SHA}
        return ({"sources": [src]}, {"schema_version": 1, "links": [
                {"source_code_sha256": HASH, "pr_number": 12,
                 "candidate_head_sha": BEFORE}]},
                [{"number": 12, "head_sha": BEFORE,
                  "verification": "VERIFIED_BOTH_APPS", "merged_sha": AFTER}],
                {"results": [{"repository": "P00NSMASHER/portfolio-brain",
                             "pr_number": 12, "status": "VERIFIED_REAL_WORLD_REPAIR",
                             "candidate_head_sha": BEFORE, "merge_main_sha": AFTER}]})

    def test_pinned_release_and_live_replay(self):
        d = self.data()
        row = value_funnel.summarize(*d)
        self.assertEqual(row["source_linked_protected_merges"], 1)
        self.assertEqual(row["source_linked_live_behavior_repairs"], 1)
        self.assertIsNone(row["independently_verified_reviews"])
        self.assertIsNone(row["verified_customer_revenue"])

    def test_forged_check_or_mismatched_merges_do_not_count(self):
        d = list(self.data())
        d[2][0]["verification"] = "FAKE_GREEN"
        self.assertEqual(value_funnel.summarize(*d)["source_linked_protected_merges"], 0)
        d = list(self.data())
        d[3]["results"][0]["merge_main_sha"] = "f" * 40
        self.assertEqual(value_funnel.summarize(*d)["source_linked_live_behavior_repairs"], 0)

    def test_missing_link_is_not_an_implicit_review(self):
        d = list(self.data())
        d[1] = {"schema_version": 1, "links": []}
        row = value_funnel.summarize(*d)
        self.assertEqual(row["discovered_source_revisions"], 1)
        self.assertEqual(row["source_linked_protected_merges"], 0)
        self.assertEqual(row["unlinked_sources_not_released"], 1)

    def test_unrecognized_source_refused(self):
        d = list(self.data())
        d[1]["links"][0]["source_code_sha256"] = "0" * 64
        with self.assertRaisesRegex(value_funnel.FunnelError, "LINK_UNTRUSTED"):
            value_funnel.summarize(*d)


if __name__ == "__main__":
    unittest.main()
