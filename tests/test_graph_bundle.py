import json, unittest
from pathlib import Path
from graph.validate_graph import validate_graph_bundle
from graph.universal_graph import upstream_edge_projection

ROOT=Path(__file__).resolve().parents[1]

class GraphBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger=json.loads((ROOT/"graph/UNIVERSAL_GRAPH_LEDGER.json").read_text())
        cls.pin=json.loads((ROOT/"graph/AI_BUSINESS_OS_GRAPH_PIN.json").read_text())

    def test_graph_bundle_validates(self):
        result=validate_graph_bundle()
        self.assertEqual(result["nodes"],25)
        self.assertEqual(result["edges"],26)
        self.assertEqual(result["registered_projects"],12)
        self.assertGreaterEqual(result["upstream_projectable_nodes"],12)
        self.assertGreaterEqual(result["upstream_projectable_edges"],4)
        self.assertTrue(result["ledger_hash"].startswith("sha256:"))

    def test_exact_canonical_source_blobs_are_pinned(self):
        self.assertEqual(self.pin["source_revision"],"21b9023a57392f380c73b2fe952c35840f2e2025")
        self.assertEqual(self.pin["knowledge_graph"]["blob_sha"],"d0ed2e015dc4593361d7600e48cb680a0df13245")
        self.assertEqual(self.pin["entity_canonicalization"]["blob_sha"],"29a765be3598f83d20f5747518deb8de8f41ffd2")
        self.assertFalse(self.pin["copied_source_code"])

    def test_seed_contains_no_fabricated_commercial_outcomes(self):
        types={n["node_type"] for n in self.ledger["nodes"]}
        for t in {"CUSTOMER","REVENUE","OPPORTUNITY","OUTCOME"}:
            self.assertNotIn(t,types)

    def test_only_semantically_compatible_edges_project_upstream(self):
        by_id={n["node_id"]:n for n in self.ledger["nodes"]}
        projected=[e for e in self.ledger["edges"] if upstream_edge_projection(e,by_id) is not None]
        self.assertTrue(all(e["edge_type"]=="IMPLEMENTS" for e in projected))
        self.assertEqual(len(projected),4)

    def test_every_seed_edge_has_provenance(self):
        self.assertTrue(all(e["provenance_refs"] for e in self.ledger["edges"]))

if __name__=="__main__": unittest.main()
