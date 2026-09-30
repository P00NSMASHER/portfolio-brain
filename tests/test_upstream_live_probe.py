import unittest

from operations.upstream_live_probe import _components, evaluate_proofs, load_pins


class UpstreamLiveProbeTests(unittest.TestCase):
    def _state(self):
        pins=load_pins()
        pinned={}
        current_heads={}
        current_trees={}
        for name,pin in pins.items():
            key=(pin["source_repository"],pin["source_revision"])
            pinned.setdefault(key,{})
            current_trees.setdefault(pin["source_repository"],{})
            current_heads[pin["source_repository"]]="b"*40
            for path,blob in _components(name,pin).items():
                pinned[key][path]=blob
                current_trees[pin["source_repository"]][path]=blob
        smokes={name:{"status":"PASS","detail":{"validator":name}} for name in pins}
        return pins,pinned,current_heads,current_trees,smokes

    def test_head_advance_with_unchanged_interface_is_visible_and_passes(self):
        pins,pinned,heads,current,smokes=self._state()
        pin_proof,live=evaluate_proofs(
            pins,pinned,heads,current,smokes,observed_at="2026-09-30T14:00:00Z"
        )
        self.assertEqual(pin_proof["status"],"PASS")
        self.assertEqual(live["status"],"PASS")
        self.assertTrue(all(row["head_drift_detected"] for row in live["integrations"]))
        self.assertTrue(all(not row["interface_drift_detected"] for row in live["integrations"]))
        self.assertTrue(all(row["drift_classification"]=="HEAD_ADVANCED_COMPONENTS_UNCHANGED" for row in live["integrations"]))
        self.assertFalse(pin_proof["authority_granted"])
        self.assertEqual(live["upstream_mutations"],0)

    def test_current_component_drift_blocks_live_but_not_pin_identity(self):
        pins,pinned,heads,current,smokes=self._state()
        first=next(iter(pins.values()))
        path=next(iter(_components("probe",first)))
        current[first["source_repository"]][path]="c"*40
        pin_proof,live=evaluate_proofs(
            pins,pinned,heads,current,smokes,observed_at="2026-09-30T14:00:00Z"
        )
        self.assertEqual(pin_proof["status"],"PASS")
        self.assertEqual(live["status"],"BLOCKED")
        row=next(x for x in live["integrations"] if x["source_repository"]==first["source_repository"] and any(y["path"]==path for y in x["current_component_checks"]))
        self.assertTrue(row["interface_drift_detected"])
        self.assertEqual(row["drift_classification"],"COMPONENT_DRIFT_REQUIRES_RECONFORMANCE")

    def test_pin_blob_mismatch_blocks_identity_even_when_live_smoke_passes(self):
        pins,pinned,heads,current,smokes=self._state()
        name=next(iter(pins))
        pin=pins[name]
        path=next(iter(_components(name,pin)))
        pinned[(pin["source_repository"],pin["source_revision"])][path]="d"*40
        pin_proof,live=evaluate_proofs(
            pins,pinned,heads,current,smokes,observed_at="2026-09-30T14:00:00Z"
        )
        self.assertEqual(pin_proof["status"],"BLOCKED")
        self.assertEqual(live["status"],"PASS")
        self.assertFalse(live["authority_granted"])

    def test_adapter_smoke_failure_blocks_live_independently(self):
        pins,pinned,heads,current,smokes=self._state()
        smokes["truth_engine"]={"status":"BLOCKED","reason":"synthetic"}
        pin_proof,live=evaluate_proofs(
            pins,pinned,heads,current,smokes,observed_at="2026-09-30T14:00:00Z"
        )
        self.assertEqual(pin_proof["status"],"PASS")
        self.assertEqual(live["status"],"BLOCKED")
        truth=next(row for row in live["integrations"] if row["integration"]=="truth_engine")
        self.assertEqual(truth["adapter_smoke"]["status"],"BLOCKED")


if __name__=="__main__":
    unittest.main()
