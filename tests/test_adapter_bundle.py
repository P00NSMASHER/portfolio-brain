import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from adapters.validate_adapters import validate_adapter_bundle

class AdapterBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry=json.loads((ROOT/"adapters/ADAPTER_REGISTRY.json").read_text())
        cls.cursors=json.loads((ROOT/"adapters/cursors/repositories.json").read_text())
        cls.observation=json.loads((ROOT/"adapters/observations/INITIAL_STEP4_OBSERVATION.json").read_text())

    def test_bundle_validates(self):
        counts=validate_adapter_bundle()
        self.assertEqual(counts["adapters"],8)
        self.assertEqual((counts["changed"],counts["unchanged"],counts["blocked"],counts["initialized"]),(3,3,1,1))
        self.assertEqual(counts["changed_files"],131)

    def test_every_adapter_is_observe_only(self):
        for adapter in self.registry["adapters"]:
            self.assertEqual(adapter["authority_class"],"OBSERVE")
            self.assertTrue(adapter["cursor_policy"]["skip_unchanged"])
            self.assertTrue(adapter["cursor_policy"]["compare_changed_only"])

    def test_no_write_or_act_configuration_fields_exist(self):
        forbidden={"write","push","deploy","send","act","modify","merge","delete","payment","trade"}
        for adapter in self.registry["adapters"]:
            keys={k.lower() for k in adapter}
            self.assertFalse(keys & forbidden)

    def test_permitplate_state_is_disabled_and_not_refreshed(self):
        adapter=next(a for a in self.registry["adapters"] if a["repository_id"]=="REPO-006")
        self.assertFalse(adapter["enabled"])
        self.assertEqual(adapter["blocked_by"],"BLK-001")
        obs=next(o for o in self.observation["observations"] if o["repository_id"]=="REPO-006")
        self.assertEqual(obs["status"],"BLOCKED")
        self.assertEqual(obs["network_reads"],0)
        self.assertIsNone(obs["current_sha"])

    def test_unchanged_sources_have_no_compare_payload(self):
        unchanged=[o for o in self.observation["observations"] if o["status"]=="UNCHANGED"]
        self.assertEqual(len(unchanged),3)
        self.assertTrue(all(o["compare"] is None for o in unchanged))
        self.assertEqual(self.observation["unchanged_content_rereads"],0)

    def test_cursors_are_exact_shas(self):
        for cursor in self.cursors["repositories"].values():
            self.assertEqual(len(cursor["cursor_sha"]),40)
            int(cursor["cursor_sha"],16)

if __name__=="__main__":
    unittest.main()
