"""V7 strict GitHub check evidence URLs; never follow untrusted pages."""
import copy
import json
import unittest

from brain.adapters import GitHub
from brain.core import BrainError
from brain.evidence_urls import check_run_ref, commit_ref, repo_evidence_ref
from brain.investigate import investigate
from brain.review import review_packet, review_lines
from brain.sidecar import summarize
from test_brain_investigate import REPO, OTHER, REV, SOURCE, NOW, Transport, report
from test_brain_review import check, observation, receipt
from test_brain_evidence_gaps import observe, verified, T0, T1, check as snapshot_check

PREFIX = f"https://github.com/{REPO}/"
VALID = [
    PREFIX + "runs/1",
    PREFIX + "runs/123456789",
    PREFIX + "actions/runs/12",
    PREFIX + "actions/runs/12/job/56",
    PREFIX + "actions/runs/9223372036854775807/job/987654321",
]
INVALID = [
    None, 3, True, "", "https://github.com/",
    "http://github.com/" + REPO + "/actions/runs/12/job/34",
    "https://www.github.com/" + REPO + "/actions/runs/12/job/34",
    "https://github.com@" + REPO + ".evil/actions/runs/12/job/34",
    "https://github.com/" + REPO + "-lookalike/actions/runs/12/job/34",
    "https://github.com/" + OTHER + "/actions/runs/12/job/34",
    PREFIX + "issues/123",
    PREFIX + "pull/685",
    PREFIX + "commit/" + REV,
    PREFIX + "actions",
    PREFIX + "actions/runs/0/job/1",
    PREFIX + "actions/runs/-1/job/1",
    PREFIX + "actions/runs/1/job/0",
    PREFIX + "actions/runs/1/job/nope",
    PREFIX + "runs/1/extra",
    PREFIX + "actions/runs/1/job/2/extra",
    PREFIX + "actions/runs/1/job/2?token=private",
    PREFIX + "actions/runs/1/job/2#fragment",
    PREFIX + "actions/runs/1/job/2/../../pull/1",
    PREFIX + "actions/runs/1%2Fjob%2F2",
    PREFIX + "actions/runs/1%252Fjob%252F2",
    PREFIX + "actions/runs/1/job/2\\something",
    PREFIX + "actions/runs/1/job/2\nsecret",
    PREFIX + "actions/runs/1/job/2\u202e",
    PREFIX + "actions/runs/1/job/2 ",
]


class CanonicalCheckReferenceTests(unittest.TestCase):
    def test_only_exact_original_github_check_urls_are_accepted(self):
        for url in VALID:
            with self.subTest(valid=url):
                self.assertTrue(check_run_ref(url, REPO))
                self.assertTrue(repo_evidence_ref(url, REPO))
        for url in INVALID:
            with self.subTest(invalid=url):
                self.assertFalse(check_run_ref(url, REPO))

    def test_original_commit_sha_cannot_be_replaced_by_non_commit(self):
        ref = PREFIX + "commit/" + REV
        self.assertTrue(commit_ref(ref, REPO, REV))
        self.assertTrue(repo_evidence_ref(ref, REPO))
        self.assertFalse(commit_ref(ref, REPO, "c" * 40))
        for value in (ref + "/", ref + "#foo", ref + "?x=1",
                      ref + "/..", PREFIX + "issues/1",
                      PREFIX + "commit/" + "z" * 40):
            with self.subTest(ref=value):
                self.assertFalse(commit_ref(value, REPO))
                self.assertFalse(repo_evidence_ref(value, REPO))

    def test_same_repo_wrong_page_forged_comparison_rejected_before_get(self):
        for malicious in (PREFIX + "issues/2", PREFIX + "runs/1?redirect=x",
                          PREFIX + "actions/runs/3/job/4#end"):
            value = report(REPO)
            value["repository_changes"][0]["check_deteriorations"][0][
                "source_ref"
            ] = malicious
            transport = Transport()
            with self.subTest(path=malicious), self.assertRaises(BrainError):
                investigate(value, api=GitHub(transport=transport), now=NOW)
            self.assertEqual(transport.calls, [])

    def test_provider_bad_check_link_cannot_certify_adverse_or_green(self):
        for forged in (PREFIX + "issues/11", PREFIX + "runs/19#fragment",
                       "https://invalid.example/runs/13"):
            t = Transport(conclusion="success")
            t.check_mutation = lambda row, forged=forged: row.update(
                html_url=forged
            )
            result = investigate(report(REPO), now=NOW,
                                 api=GitHub(transport=t))
            self.assertEqual(len(t.calls), 4)
            evidence = result["investigations"][0]["checks"][0]
            self.assertEqual(evidence["outcome"],
                             "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK")
            self.assertNotIn("source_ref", evidence)
            safe = summarize(result, SOURCE, *["success"] * 4)
            self.assertEqual(safe["status"], "PARTIAL_READ_ONLY")
            self.assertEqual(safe["observed_outcomes"], {
                "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK": 1,
            })
            self.assertNotIn("invalid.example", str(result))
            self.assertNotIn("invalid.example", str(safe))

    def test_bad_check_reference_quarantined_but_other_unique_check_preserved(self):
        data = lambda when, audit: observe(
            REPO, when, [
                snapshot_check(REPO, name="validate",
                               conclusion="success" if when == T0 else "failure"),
                snapshot_check(REPO, name="audit", conclusion=audit),
            ]
        )
        verified_report, history = verified(
            data(T0, "failure"), data(T1, "failure")
        )
        t = Transport()
        t.check_mutation = lambda row: row.update(
            html_url=PREFIX + "issues/3"
        )
        t.extra_checks = [{
            "id": 21, "name": "audit", "status": "completed",
            "conclusion": "failure", "head_sha": REV,
            "html_url": PREFIX + "actions/runs/21/job/31",
        }]
        result = investigate(verified_report, history=history,
                             api=GitHub(transport=t), now=NOW)
        self.assertEqual(len(t.calls), 4)
        self.assertEqual(result["eligible_count"], 1)
        selected = result["investigations"][0]["checks"]
        observations = {row["name"]: row["outcome"] for row in selected}
        self.assertEqual(observations, {
            "audit": "STILL_ADVERSE",
            "validate": "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK",
        })
        self.assertEqual(
            summarize(result, SOURCE, *["success"] * 4)["status"],
            "PARTIAL_READ_ONLY"
        )
        self.assertFalse(result["root_cause_verified"])

    def test_corrupt_original_check_url_fails_before_provider_get(self):
        for bad in (PREFIX + "pull/685", PREFIX + "runs/1?evil=1"):
            earlier = observe(REPO, T0, [
                snapshot_check(REPO, conclusion="failure"),
            ])
            recent = observe(REPO, T1, [
                snapshot_check(REPO, conclusion="failure"),
            ])
            recent["payload"]["checks"][0]["url"] = bad
            from brain.core import digest
            recent["id"] = recent["kind"] + ":" + digest(
                {**recent, "id": ""}
            )
            source, history = verified(earlier, recent)
            transport = Transport()
            with self.subTest(check=bad), self.assertRaises(BrainError):
                investigate(source, history=history,
                            api=GitHub(transport=transport), now=NOW)
            self.assertEqual(transport.calls, [])

    def test_private_human_review_drops_same_repo_but_wrong_check_page(self):
        row = check()
        row["source_ref"] = PREFIX + "pull/685"
        human = receipt(observation(row))
        item = review_packet(human)["items"][0]
        self.assertEqual(item["evidence_ref"], PREFIX + "commit/" + REV)
        rendered = "\n".join(review_lines(human))
        self.assertNotIn("/pull/685", rendered)
        self.assertIn("commit/", rendered)

    def test_private_review_rejects_forged_extra_original_reference(self):
        original = receipt(observation(check()))
        original["investigations"][0]["source_refs"].append(
            PREFIX + "issues/7"
        )
        with self.assertRaises(ValueError):
            review_packet(original)

    def test_untrusted_page_cannot_trigger_cross_repo_check_name_coincidence(self):
        from test_brain_review_case_identity import real_check, row
        left = real_check(REPO)
        right = real_check(OTHER)
        left["source_ref"] = PREFIX + "pull/99"
        packet = review_packet(receipt(row(REPO, left), row(OTHER, right)))
        self.assertEqual(packet["same_name_adverse_coincidences"], [])
        self.assertFalse(packet["root_cause_verified"])

    def test_valid_canonical_check_run_evidence_retained_without_extra_requests(self):
        t = Transport()
        t.check_mutation = lambda row: row.update(
            html_url=PREFIX + "runs/771"
        )
        result = investigate(report(REPO), api=GitHub(transport=t), now=NOW)
        evidence = result["investigations"][0]["checks"][0]
        self.assertEqual(evidence["outcome"], "STILL_ADVERSE")
        self.assertEqual(evidence["source_ref"], PREFIX + "runs/771")
        self.assertEqual(result["requests_used"], 4)
        self.assertEqual(len(t.calls), 4)
        self.assertEqual(result["events_written"], 0)
        self.assertEqual(result["github_mutations"], 0)


if __name__ == "__main__":
    unittest.main()
