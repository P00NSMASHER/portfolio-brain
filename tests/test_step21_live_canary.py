import json
import unittest
from pathlib import Path

from acceptance.step21_quiz_canary import (
    AUTHORITY_GRANTED, PRODUCTION_IMPORTED, SOURCE_FINDING_ID, SOURCE_PROPOSAL_ID,
    SOURCE_REPOSITORY, SOURCE_REVISION, bounded_quiz_score,
)

ROOT=Path(__file__).resolve().parents[1]

class Step21CanaryTests(unittest.TestCase):
    def test_canary_is_harmless_and_bound_to_existing_value_contract(self):
        contract=json.loads((ROOT/"value_proof/MODEL_TASK_CONTRACT.json").read_text())
        src=contract["source_candidate"]
        self.assertFalse(AUTHORITY_GRANTED)
        self.assertFalse(PRODUCTION_IMPORTED)
        self.assertEqual(src["finding_id"],SOURCE_FINDING_ID)
        self.assertEqual(src["experiment_proposal_id"],SOURCE_PROPOSAL_ID)
        self.assertEqual(src["repository_full_name"],SOURCE_REPOSITORY)
        self.assertEqual(src["revision"],SOURCE_REVISION)

    def test_clean_room_quiz_score_is_deterministic_and_bounded(self):
        self.assertEqual(bounded_quiz_score(3,4),0.75)
        self.assertEqual(bounded_quiz_score(0,4),0.0)
        with self.assertRaises(ValueError):
            bounded_quiz_score(5,4)
        with self.assertRaises(ValueError):
            bounded_quiz_score(0,0)

if __name__=="__main__":
    unittest.main()
