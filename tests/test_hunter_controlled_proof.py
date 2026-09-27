import copy
import unittest

from hunting.controlled_proof import load_cases, run_controlled_proof


class FakeControlledProvider:
    def __init__(self):
        self.requests=0
        self.meta={
          "pwenker/quizli":{"id":448679097,"full_name":"pwenker/quizli","default_branch":"main","private":False},
          "OpenLineage/OpenLineage":{"id":306977038,"full_name":"OpenLineage/OpenLineage","default_branch":"main","private":False},
          "pytest-dev/pytest":{"id":37489525,"full_name":"pytest-dev/pytest","default_branch":"main","private":False},
        }
    def repository_metadata(self,full_name):
        self.requests+=1
        return copy.deepcopy(self.meta[full_name])
    def inspect(self,candidate):
        self.requests+=1
        repo=candidate["full_name"]
        if repo=="pwenker/quizli":
            paths=["quizli/quiz.py","quizli/session.py","tests/test_quizli.py","docs/learning_guide/quiz.md"]
            rev="a"*40
        elif repo=="OpenLineage/OpenLineage":
            paths=["client/go/pkg/facets/lineage.go","client/go/pkg/facets/lineage_test.go","docs/lineage.md"]
            rev="b"*40
        else:
            paths=["src/_pytest/main.py","testing/test_main.py","doc/en/index.rst"]
            rev="c"*40
        return {"revision":rev,"tree_sha":"d"*40,"paths":paths,"truncated":False}


class ControlledHunterProofTests(unittest.TestCase):
    def test_controlled_proof_configuration_requires_three_candidates_and_two_strategies(self):
        doc=load_cases()
        self.assertGreaterEqual(doc["completion_gate"]["min_retained_candidates"],3)
        self.assertGreaterEqual(doc["completion_gate"]["min_distinct_strategies"],2)
        self.assertGreaterEqual(len(doc["cases"]),3)
        self.assertGreaterEqual(len({x["strategy_id"] for x in doc["cases"]}),2)

    def test_controlled_proof_passes_with_exact_public_revision_evidence(self):
        report=run_controlled_proof(FakeControlledProvider())
        self.assertEqual(report["status"],"PASS")
        self.assertGreaterEqual(report["retained_candidate_count"],3)
        self.assertGreaterEqual(report["distinct_strategy_count"],2)
        self.assertTrue(all(report["checks"].values()))
        self.assertTrue(all(len(x["revision"])==40 for x in report["candidate_results"]))
        self.assertTrue(all(x["public_source"] for x in report["candidate_results"]))
        self.assertTrue(all(x["experiment_proposal_id"] for x in report["candidate_results"]))
        self.assertGreaterEqual(len(report["downstream_acceptances"]),1)
        self.assertFalse(report["code_execution_performed"])
        self.assertFalse(report["downstream_mutation_performed"])
        self.assertEqual(report["rights_state"],"NOT_GRANTED_BY_DISCOVERY")

    def test_proof_fails_closed_on_repository_identity_drift(self):
        provider=FakeControlledProvider()
        provider.meta["pwenker/quizli"]["id"]=999
        with self.assertRaises(Exception):
            run_controlled_proof(provider)


if __name__=="__main__":
    unittest.main()
