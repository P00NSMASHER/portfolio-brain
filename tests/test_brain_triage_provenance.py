"""V7 GitHub source review provenance: no unpinned third-party code suggestions."""
import copy
import json
import unittest

from brain.evidence_urls import blob_ref, commit_ref, check_run_ref
from brain.triage import decision_queue
from test_brain_triage import candidate, change, sample_report, SOURCE, REV, BASE

REPO = "source/research"
BASE_CANDIDATE = candidate("agent-products", 1)


class ExactBlobReferenceTests(unittest.TestCase):
    def test_immutable_exact_repo_commit_and_path_is_the_only_trusted_blob(self):
        source = BASE_CANDIDATE
        ref = source["source_ref"]
        self.assertTrue(blob_ref(ref, source["repository"],
                                 source["head_sha"], source["path"]))
        self.assertFalse(commit_ref(ref, source["repository"]))
        self.assertFalse(check_run_ref(ref, source["repository"]))

    def test_lookalike_hosts_encoded_paths_and_ambiguous_segments_rejected(self):
        original = BASE_CANDIDATE
        prefix = f'https://github.com/{original["repository"]}/blob/{REV}/'
        valid_path = original["path"]
        bad = [
            "http://github.com/" + original["repository"] + "/blob/" + REV + "/" + valid_path,
            "https://www.github.com/" + original["repository"] + "/blob/" + REV + "/" + valid_path,
            "https://github.com@" + original["repository"] + ".attacker.example/blob/" + REV + "/" + valid_path,
            "https://github.com/source/research-clone/blob/" + REV + "/" + valid_path,
            "https://github.com/source/other/blob/" + REV + "/" + valid_path,
            prefix + valid_path + "?redirect=https://evil.example",
            prefix + valid_path + "#tracked",
            prefix + valid_path + "/..",
            prefix + "./" + valid_path,
            prefix + "src//app.py",
            prefix + "src/%2e%2e/app.py",
            prefix + "src/%2f/app.py",
            prefix + "src/x.py\\\\payload",
            prefix + "src/x.py\nhidden",
            prefix + "src/x.py " ,
            prefix + "src/éxample.py",
            prefix + "src/test<script>.py",
            prefix + "src/app.py@" + "attacker",
            prefix.replace("/blob/" + REV + "/", "/tree/" + REV + "/") + valid_path,
        ]
        for ref in bad:
            with self.subTest(ref=ref):
                self.assertFalse(blob_ref(ref, original["repository"],
                                          original["head_sha"], original["path"]))

    def test_revision_and_expected_exact_source_path_cannot_be_swapped(self):
        c = BASE_CANDIDATE
        self.assertFalse(blob_ref(c["source_ref"], c["repository"], "c"*40,c["path"]))
        self.assertFalse(blob_ref(c["source_ref"], c["repository"], c["head_sha"],
                                  "tests/other.py"))
        self.assertFalse(blob_ref(c["source_ref"], c["repository"], True,c["path"]))
        self.assertFalse(blob_ref(c["source_ref"], c["repository"], c["head_sha"],4))
        self.assertFalse(blob_ref(None, c["repository"], c["head_sha"],c["path"]))


class ReviewedSourceCandidateTests(unittest.TestCase):
    def test_exact_source_selects_read_only_rights_caveat(self):
        result=decision_queue(sample_report(candidates=[copy.deepcopy(BASE_CANDIDATE)]))
        self.assertEqual(len(result["items"]),1)
        item=result["items"][0]
        self.assertEqual(item["category"],"REVIEW_THIRD_PARTY_SOURCE")
        metadata=item["metadata"]
        self.assertTrue(metadata["immutable_repo_revision_path_pin_verified"])
        self.assertFalse(metadata["code_bytes_independently_executed_or_tested"])
        self.assertFalse(metadata["declared_license_independently_verified"])
        self.assertFalse(metadata["source_reuse_permission_confirmed"])
        self.assertFalse(item["action_authority"])
        self.assertIsNone(item["verified_revenue"])

    def test_invalid_candidate_source_and_cross_commit_substitution_suppressed(self):
        baseline=copy.deepcopy(BASE_CANDIDATE)
        probes=[
            {"repository":"source/other"},
            {"head_sha":"c"*40},
            {"path":"src/other.py"},
            {"key":"source/research:src/other.py"},
            {"source_ref":baseline["source_ref"]+"?evil=1"},
            {"source_ref":baseline["source_ref"]+"#private"},
            {"source_ref":baseline["source_ref"].replace("/blob/","/tree/")},
            {"source_ref":"https://github.com/source/research/issues/1"},
            {"source_ref":"https://evil.example/source/research/blob/" + REV+"/app.py"},
            {"head_sha":True}, {"blob_sha":0}, {"code_sha256":[]},
            {"path":None}, {"repository":[]}, {"reuse_score":True},
            {"key":["unhashable"]},
        ]
        for changes in probes:
            with self.subTest(changes=changes):
                altered={**baseline,**changes}
                result=decision_queue(sample_report(candidates=[altered]))
                self.assertEqual(result["items"],[])
                self.assertFalse(result["execution_authority"])

    def test_one_bad_candidate_does_not_suppress_another_valid_target(self):
        bad={**BASE_CANDIDATE, "source_ref":BASE_CANDIDATE["source_ref"]+"#unsafe"}
        valid=candidate("school-tools",2)
        packet=decision_queue(sample_report(candidates=[bad,valid]))
        self.assertEqual(len(packet["items"]),1)
        self.assertEqual(packet["items"][0]["metadata"]["target"],"school-tools")
        self.assertTrue(packet["items"][0]["metadata"]["immutable_repo_revision_path_pin_verified"])

    def test_duplicate_unhashable_candidate_key_not_processed(self):
        packet=decision_queue(sample_report(candidates=[
            {**BASE_CANDIDATE,"key":{}},
            copy.deepcopy(BASE_CANDIDATE),copy.deepcopy(BASE_CANDIDATE),
        ]))
        self.assertEqual(len(packet["items"]),1)
        self.assertFalse(packet["execution_authority"])

    def test_no_unreviewed_source_is_executed_even_if_declared_license_known(self):
        evidence=candidate("school-tools",5,license="MIT")
        packet=decision_queue(sample_report(candidates=[evidence]))
        self.assertEqual(packet["items"][0]["metadata"]["license_review_status"],
            "DECLARED_LICENSE_METADATA_NOT_INDEPENDENTLY_VERIFIED")
        self.assertEqual(packet["items"][0]["metadata"]["code_bytes_independently_executed_or_tested"],False)



    def test_bad_same_key_record_cannot_hide_valid_immutable_source(self):
        valid = candidate("agent-products", 1)
        invalid = {**valid, "source_ref": valid["source_ref"] + "#unsafe"}
        for order in ([invalid, valid], [valid, invalid]):
            with self.subTest(first=order[0]["source_ref"]):
                packet = decision_queue(sample_report(candidates=order))
                self.assertEqual(len(packet["items"]), 1)
                self.assertEqual(packet["items"][0]["metadata"]["candidate_key"],
                                 valid["key"])
                self.assertTrue(packet["items"][0]["metadata"]
                                ["immutable_repo_revision_path_pin_verified"])

    def test_explicit_operator_decline_cannot_be_bypassed_by_duplicate(self):
        valid = candidate("agent-products", 1)
        declined = {**valid, "feedback": {
            "basis": "OPERATOR_REPORTED", "outcome": "NOT_USEFUL"
        }}
        altered = {**valid, "source_ref": valid["source_ref"] + "?tampered",
                   "feedback": declined["feedback"]}
        for order in ([valid, declined], [declined, valid],
                      [altered, valid], [valid, altered]):
            with self.subTest(first=order[0]["source_ref"]):
                packet = decision_queue(sample_report(candidates=order))
                self.assertEqual(packet["items"], [])

    def test_conflicting_qualified_revisions_are_order_deterministic(self):
        old = candidate("agent-products", 1)
        next_rev = {**old,
            "head_sha": "c" * 40,
            "source_ref": old["source_ref"].replace(
                "/blob/" + old["head_sha"] + "/",
                "/blob/" + "c" * 40 + "/",
            )
        }
        one = decision_queue(sample_report(candidates=[old, next_rev]))
        two = decision_queue(sample_report(candidates=[next_rev, old]))
        self.assertEqual(one, two)
        self.assertEqual(len(one["items"]), 1)
        self.assertFalse(one["execution_authority"])


class OriginalComparisonReferenceTests(unittest.TestCase):
    def test_exact_commit_refs_preserve_source_comparable_review(self):
        report=sample_report(changes=[change(repo="example/repository",failures=["validate"])])
        packet=decision_queue(report)
        self.assertEqual(packet["items"][0]["category"],"INVESTIGATE_CHECK_CHANGE")
        self.assertTrue(packet["items"][0]["action_authority"] is False)

    def test_other_sha_or_wrong_repo_in_original_pair_rejected(self):
        for transformation in ("revision","foreign","query","unrelated"):
            row=change(repo="example/repository",delta=1)
            if transformation=="revision":
                row["source_refs"][0]=row["source_refs"][0].replace(REV,"c"*40)
            elif transformation=="foreign":
                row["source_refs"][0]=row["source_refs"][0].replace("example/repository","other/repository")
            elif transformation=="query":
                row["source_refs"][1]+="?sensitive=1"
            else:
                row["source_refs"][1]="https://github.com/example/repository/issues/10"
            with self.subTest(transformation=transformation),self.assertRaisesRegex(
                ValueError,"source-bound"
            ):
                decision_queue(sample_report(changes=[row]))

    def test_noncanonical_check_run_link_cannot_be_human_review_evidence(self):
        base=change(repo="example/repository",failures=["unit"])
        valid="https://github.com/example/repository/actions/runs/101/job/202"
        for url in (valid+"#foo",
                    "https://github.com/example/repository/pull/33",
                    "https://github.com/another/repository/actions/runs/101/job/202",
                    "https://github.com/example/repository/runs/101?redirect=x"):
            malformed=copy.deepcopy(base)
            malformed["check_deteriorations"][0]["source_ref"]=url
            with self.subTest(url=url),self.assertRaisesRegex(
                ValueError,"check transition source"
            ):
                decision_queue(sample_report(changes=[malformed]))
        original=copy.deepcopy(base)
        original["check_deteriorations"][0]["source_ref"]=valid
        packet=decision_queue(sample_report(changes=[original]))
        self.assertEqual(len(packet["items"]),1)

    def test_original_check_urls_remain_source_bound_but_not_incident_resolution(self):
        original=change(repo="example/repository",recovery=["ci"])
        packet=decision_queue(sample_report(changes=[original]))
        self.assertEqual(len(packet["items"]),1)
        self.assertEqual(packet["items"][0]["category"],"REVIEW_CHECK_RECOVERY")
        self.assertFalse(packet["items"][0]["action_authority"])
        self.assertIsNone(packet["items"][0]["verified_revenue"])


if __name__=="__main__":
    unittest.main()
