import json, unittest
from pathlib import Path
from memory.validate_value_memory import validate_shared_value_memory

ROOT=Path(__file__).resolve().parents[1]

class SharedMemoryBundleTests(unittest.TestCase):
    def test_bundle_validates(self):
        result=validate_shared_value_memory()
        self.assertTrue(result["verified_learning_only"])
        self.assertEqual(result["source_revision"],"21b9023a57392f380c73b2fe952c35840f2e2025")
        self.assertEqual(result["source_blob_sha"],"5e6450087e2fe0402ebe0af9ea0443383964a7a8")

    def test_ledger_starts_without_fabricated_outcomes(self):
        ledger=json.loads((ROOT/"memory/SHARED_VALUE_MEMORY_LEDGER.json").read_text())
        self.assertEqual(ledger["memories"],[])
        self.assertEqual(ledger["outcomes"],[])

if __name__=="__main__": unittest.main()
