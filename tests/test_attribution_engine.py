import unittest

from attribution.attribution_engine import AttributionError, allocator_dimensions, build_attribution_snapshot, validate_snapshot

def r(rid, parent, stage, hour, *, result="NOT_APPLICABLE", evidence="OBSERVED", failure=None):
    return {
        "record_id": rid,
        "parent_id": parent,
        "stage": stage,
        "project_id": "PRJ-009",
        "agent_id": "A1",
        "source_id": "SRC-1",
        "event_time": f"2026-09-21T{hour:02d}:00:00+00:00",
        "evidence_state": evidence,
        "result": result,
        "cost_usd": 1.0 if stage == "EXPERIMENT" else 0.0,
        "model_calls": 1 if stage == "EXPERIMENT" else 0,
        "failure_cause": failure,
        "provenance_refs": [f"evidence:{rid}"],
    }

class AttributionEngineTests(unittest.TestCase):
    def fixture(self):
        return [
            r("D", None, "HUNTER_DISCOVERY", 8),
            r("P", "D", "PROPOSAL", 9),
            r("E", "P", "EXPERIMENT", 10, result="PASSED"),
            r("I", "E", "IMPLEMENTATION", 11),
            r("O", "I", "VERIFIED_OUTCOME", 12, result="PASSED", evidence="VERIFIED"),
        ]

    def test_transparent_dimensions_without_score(self):
        snap = build_attribution_snapshot(self.fixture())
        validate_snapshot(snap)
        self.assertFalse(snap["opaque_score_used"])
        def forbidden_key(value):
            if isinstance(value, dict):
                return any(k in {"score", "weighted_score", "composite_score"} or forbidden_key(v) for k, v in value.items())
            if isinstance(value, list):
                return any(forbidden_key(v) for v in value)
            return False
        self.assertFalse(forbidden_key(snap))
        dims = allocator_dimensions(snap)["PRJ-009"]
        self.assertEqual(dims["verified_outcomes"], 1)
        self.assertEqual(dims["proposal_to_experiment_conversion"], 1.0)

    def test_missing_parent_fails_closed(self):
        rows = self.fixture()
        rows[-1]["parent_id"] = "MISSING"
        with self.assertRaises(AttributionError):
            build_attribution_snapshot(rows)

    def test_unverified_outcome_rejected(self):
        rows = self.fixture()
        rows[-1]["evidence_state"] = "OBSERVED"
        with self.assertRaises(AttributionError):
            build_attribution_snapshot(rows)

if __name__ == "__main__":
    unittest.main()
