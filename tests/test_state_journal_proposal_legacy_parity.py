import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from state_journal import legacy_parity
from state_journal.contracts import DOMAINS, JournalError, strict_load


class ProposalLegacyParityTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        checkpoint = strict_load(
            gzip.decompress((root / "state_journal/CHECKPOINT.json.gz").read_bytes())
        )
        self.projected = checkpoint["states"]
        self.projected["proposals"] = json.loads(
            (root / "hunting/HUNTER_PROPOSAL_STATE_SEED.json").read_text()
        )
        self.refs = {domain: f"fixture:{domain}" for domain in DOMAINS}

    def test_accepted_legacy_proposal_shape_matches_normalized_projection(self):
        legacy = copy.deepcopy(self.projected)
        legacy["proposals"].pop("origins")

        with tempfile.TemporaryDirectory() as work, patch.object(
            legacy_parity, "restore_all", return_value=(legacy, self.refs)
        ):
            result = legacy_parity.verify(self.projected, Path(work))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["domains"]["proposals"]["projection_hash"],
            result["domains"]["proposals"]["legacy_hash"],
        )

    def test_proposal_content_drift_still_fails_parity(self):
        legacy = copy.deepcopy(self.projected)
        legacy["proposals"]["sequence"] += 1

        with tempfile.TemporaryDirectory() as work, patch.object(
            legacy_parity, "restore_all", return_value=(legacy, self.refs)
        ):
            with self.assertRaisesRegex(JournalError, "LEGACY_PARITY_MISMATCH:proposals"):
                legacy_parity.verify(self.projected, Path(work))


if __name__ == "__main__":
    unittest.main()
