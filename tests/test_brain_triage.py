"""V7 decision-queue tests: actionable only after source/evidence gates."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from brain.triage import decision_queue
from brain.render import write_report

SOURCE = "a" * 40
REV = "b" * 40
BASE = "c" * 40
REPO = "example/repository"
ROOT_REF = "https://github.com/example/repository/commit/" + REV


def sample_report(*, status="PASS", candidates=None, changes=None):
    return {
        "schema_version": 2, "status": status,
        "scope": "READ_ONLY_BUSINESS_PORTFOLIO_INTELLIGENCE",
        "source_sha": SOURCE, "state_sequence": 42,
        "repositories": [], "repository_changes": changes or [],
        "reuse_candidates": candidates or [], "business_opportunities": [],
        "learning": {"experiments": []},
    }


def change(*, repo=REPO, quality="ACTUAL_FRESH", delta=0,
           failures=None, recovery=None, revision=False):
    failures = failures or []
    recovery = recovery or []
    # The original source links must match the recorded comparison
    # revisions exactly, including the same-revision fixture.
    refs = [
        "https://github.com/" + repo + "/commit/" + (BASE if revision else REV),
        "https://github.com/" + repo + "/commit/" + REV,
    ]
    return {
        "repository": repo, "previous_observed_at": "2026-10-12T14:00:00Z",
        "current_observed_at": "2026-10-12T15:00:00Z",
        "previous_revision": BASE if revision else REV,
        "current_revision": REV, "revision_changed": revision,
        "open_issue_pr_tally": {
            "previous": 3, "current": 3 + delta, "net_delta": delta,
            "definition": "GITHUB_OPEN_ISSUES_COUNT_INCLUDES_PULL_REQUESTS",
        },
        "check_comparison": "REVISION_CHANGED" if revision else "COMPARABLE",
        "compared_check_names": 1,
        "check_deteriorations": [
            {"name": name, "source_ref": refs[1]}
            for name in failures
        ],
        "check_recoveries": [
            {"name": name, "source_ref": refs[1]}
            for name in recovery
        ],
        "change_types": (
            (["REVISION_CHANGED"] if revision else [])
            + (["OPEN_TRACKER_TALLY_CHANGED"] if delta else [])
            + (["CHECK_DETERIORATED"] if failures else [])
            + (["CHECK_RECOVERED"] if recovery else [])
        ),
        "evidence_quality": quality, "source_refs": refs,
        "scope": "OBSERVED_DIFFERENCES_NOT_CAUSATION_OR_VALUE_VERIFICATION",
    }


def candidate(target, n, *, score=8, freshness="CURRENT", kind="ACTUAL",
              license="MIT", feedback=None, tests=True):
    repository = "source/research"
    path = "src/" + target + "/source" + str(n) + ".py"
    return {
        "key": repository + ":" + path,
        "repository": repository,
        "head_sha": REV, "blob_sha": "d" * 40,
        "code_sha256": ("e" * 63) + hex(n % 16)[2:],
        "bytes": 1200, "path": path, "query": target,
        "source_ref": "https://github.com/" + repository + "/blob/" + REV + "/" + path,
        "license": license, "target": target,
        "matched_terms": ["test", "source"],
        "test_paths": ["tests/test_source.py"] if tests else [],
        "reuse_score": score, "freshness": freshness, "data_kind": kind,
        "utility_evidence": "STRUCTURAL_ONLY_NOT_EXECUTED",
        "feedback": feedback,
    }


class EvidenceGatedDecisionQueueTests(unittest.TestCase):
    def test_blocked_and_missing_source_never_instruct_action(self):
        blocked = sample_report(status="BLOCKED", changes=[change(failures=["ci"])])
        self.assertEqual(decision_queue(blocked)["items"], [])
        no_source = sample_report(changes=[change(failures=["ci"])])
        no_source["source_sha"] = "unknown"
        with self.assertRaisesRegex(ValueError, "source-bound"):
            decision_queue(no_source)
        with self.assertRaisesRegex(ValueError, "limit"):
            decision_queue(sample_report(), max_items=100)

    def test_fresh_actual_deterioration_precedes_revision_and_tally(self):
        report = sample_report(changes=[
            change(repo="test/tally", delta=1),
            change(repo="test/revision", revision=True),
            change(repo="test/failed", failures=["unit"], delta=4),
        ])
        entries = decision_queue(report)["items"]
        self.assertEqual([x["category"] for x in entries], [
            "INVESTIGATE_CHECK_CHANGE",
            "REVIEW_SOURCE_REVISION",
            "REVIEW_TRACKER_TALLY",
        ])
        self.assertTrue(all(x["action_authority"] is False for x in entries))
        self.assertTrue(all(x["verified_revenue"] is None for x in entries))
        self.assertEqual(entries[0]["metadata"]["observed_check_deteriorations"], 1)
        self.assertEqual(entries[-1]["metadata"]["tally_delta_including_prs"], 1)
        self.assertIn("includes pull requests", entries[-1]["limitations"][0])

    def test_stale_and_nonactual_never_become_current_incidents(self):
        report = sample_report(changes=[
            change(repo="test/old", quality="ACTUAL_STALE_BASELINE",
                   failures=["ci"]),
            change(repo="test/simulated", quality="NON_ACTUAL",
                   failures=["ci"]),
            change(repo="test/historical", quality="HISTORICAL",
                   recovery=["ci"]),
        ])
        entries = decision_queue(report)["items"]
        self.assertEqual(
            {x["category"] for x in entries}, {"REVALIDATE_EVIDENCE"},
        )
        self.assertTrue(all(x["band"] == "EVIDENCE_QUALITY_BLOCKER" for x in entries))
        self.assertTrue(all("Not verified as a recent incident" in x["limitations"][0] for x in entries))

    def test_unknown_quality_and_unbound_sources_fail_closed(self):
        report = sample_report(changes=[change(quality="UNKNOWN", delta=1)])
        with self.assertRaisesRegex(ValueError, "unsupported evidence"):
            decision_queue(report)
        report["repository_changes"][0]["evidence_quality"] = "ACTUAL_FRESH"
        report["repository_changes"][0]["source_refs"] = ["https://other.invalid"]
        with self.assertRaisesRegex(ValueError, "source-bound"):
            decision_queue(report)

    def test_current_actual_structural_candidates_balanced_across_projects(self):
        candidates = [
            candidate("agent-products", i, score=12-i) for i in range(9)
        ] + [
            candidate("freight-recovery", 10, score=6),
            candidate("school-tools", 11, score=5),
            candidate("school-tools", 12, score=4, license="UNKNOWN"),
        ]
        report = sample_report(candidates=candidates)
        first = decision_queue(report)
        second = decision_queue(sample_report(candidates=list(reversed(candidates))))
        self.assertEqual(first, second, "provider list order must not change review order")
        rows = first["items"]
        self.assertEqual(len(rows), 5)
        self.assertEqual({x["category"] for x in rows}, {"REVIEW_THIRD_PARTY_SOURCE"})
        selected = [x["metadata"]["target"] for x in rows]
        self.assertEqual(selected.count("agent-products"), 2)
        self.assertEqual(selected.count("freight-recovery"), 1)
        self.assertEqual(selected.count("school-tools"), 2)
        self.assertEqual(first["proposals_considered"], 5)
        self.assertTrue(any(
            x["metadata"]["license_metadata_only"] == "UNKNOWN"
            for x in rows
        ))
        self.assertTrue(all(
            "not executed" in x["limitations"][0].lower()
            and x["status"] == "HUMAN_REVIEW_PROPOSAL_NOT_EXECUTED"
            for x in rows
        ))

    def test_stale_simulated_without_tests_or_hash_never_credited(self):
        rows = [
            candidate("agent-products", 1, freshness="HISTORICAL"),
            candidate("freight-recovery", 2, kind="SIMULATED"),
            candidate("school-tools", 3, tests=False),
        ]
        row = candidate("agent-products", 4)
        row["code_sha256"] = "bad"
        rows.append(row)
        self.assertEqual(decision_queue(sample_report(candidates=rows))["items"], [])

    def test_operator_reported_integrated_and_not_useful_are_not_repromoted(self):
        integrations = [candidate("agent-products", 1, feedback={
            "basis": "OPERATOR_REPORTED", "outcome": "INTEGRATED",
        }), candidate("agent-products", 2, feedback={
            "basis": "OPERATOR_REPORTED", "outcome": "NOT_USEFUL",
        }), candidate("agent-products", 3)]
        selected = decision_queue(sample_report(candidates=integrations))["items"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["metadata"]["candidate_key"], integrations[2]["key"])
        self.assertTrue(all(x["metadata"]["candidate_key"] != integrations[0]["key"] for x in selected))
        self.assertTrue(all(x["metadata"]["candidate_key"] != integrations[1]["key"] for x in selected))
        self.assertTrue(all(x["verified_revenue"] is None for x in selected))

    def test_renderer_adds_review_only_section_without_mutating_canonical_json(self):
        report = sample_report(
            changes=[change(repo="test/tally", delta=2)],
            candidates=[candidate("school-tools", 1, license="UNKNOWN")],
        )
        original = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as d:
            write_report(report, Path(d) / "out")
            path = Path(d) / "out"
            md = (path / "report.md").read_text()
            rendered_html = (path / "report.html").read_text()
            machine = json.loads((path / "report.json").read_text())
            self.assertIn("Evidence-gated decision queue", md)
            self.assertIn("REVIEW_TRACKER_TALLY", md)
            self.assertIn("STRUCTURAL_REVIEW_ONLY", md)
            self.assertIn("authorization to execute", md)
            self.assertIn("Evidence-gated decision queue", rendered_html)
            self.assertEqual(report, original)
            self.assertEqual(machine, original, "canonical report JSON must remain unchanged")
            self.assertNotIn("decision_queue", machine)

    def test_license_metadata_is_not_permission_and_all_caveats_render(self):
        report = sample_report(candidates=[
            candidate("agent-products", 1, license="MIT"),
            candidate("freight-recovery", 2, license="UNKNOWN"),
            candidate("school-tools", 3, license="NOASSERTION"),
        ])
        queue = decision_queue(report)
        self.assertEqual(len(queue["items"]), 3)
        statuses = {
            item["metadata"]["target"]: item["metadata"]["license_review_status"]
            for item in queue["items"]
        }
        self.assertEqual(
            statuses["agent-products"],
            "DECLARED_LICENSE_METADATA_NOT_INDEPENDENTLY_VERIFIED",
        )
        for target in ("freight-recovery", "school-tools"):
            self.assertEqual(
                statuses[target], "MISSING_OR_INCONCLUSIVE_LICENSE_METADATA",
            )
        self.assertTrue(all(
            item["metadata"]["source_reuse_permission_confirmed"] is False
            and item["action_authority"] is False
            and item["verified_revenue"] is None
            for item in queue["items"]
        ))
        with tempfile.TemporaryDirectory() as directory:
            write_report(report, Path(directory) / "out")
            out = Path(directory) / "out"
            markdown = (out / "report.md").read_text()
            html = (out / "report.html").read_text()
            self.assertIn("Declared license metadata: MIT", markdown)
            self.assertIn("unverified declaration; review rights before reuse", markdown)
            self.assertIn("Declared license metadata: UNKNOWN", markdown)
            self.assertIn("Declared license metadata: NOASSERTION", markdown)
            self.assertEqual(
                markdown.count("missing/inconclusive; review rights before reuse"), 2
            )
            # Existing renderer showed only the first generic limitation:
            # now it must expose every rights and benefit caveat.
            self.assertEqual(markdown.count("License metadata is not a grant of permission."), 3)
            self.assertEqual(markdown.count(
                "No customer demand, engineering time saved, revenue or safety measured."
            ), 3)
            self.assertIn("Declared license metadata: UNKNOWN", html)
            self.assertEqual(json.loads((out / "report.json").read_text()), report)
            self.assertNotIn("license_review_status", (out / "report.json").read_text())

    def test_untrusted_license_text_escaped_and_malformed_metadata_rejected(self):
        unsafe = candidate("school-tools", 1, license="<script>alert(1)</script>")
        report = sample_report(candidates=[unsafe])
        with tempfile.TemporaryDirectory() as directory:
            write_report(report, Path(directory) / "out")
            output = (Path(directory) / "out" / "report.html").read_text()
            self.assertNotIn("<script>", output)
            self.assertIn("&lt;", output)
            self.assertEqual(json.loads(
                (Path(directory) / "out" / "report.json").read_text()
            ), report)
        unsafe["license"] = ""
        with self.assertRaisesRegex(ValueError, "license metadata malformed"):
            decision_queue(report)

    def test_no_forged_ranking_on_empty_or_failed_report(self):
        self.assertEqual(decision_queue(sample_report())["items"], [])
        with tempfile.TemporaryDirectory() as d:
            write_report({"status": "FAIL", "error_class": "BrainError"}, Path(d)/"fail")
            md=(Path(d)/"fail"/"report.md").read_text()
            self.assertNotIn("Evidence-gated decision queue", md)
            self.assertNotIn("HUMAN_REVIEW_PROPOSAL", md)


if __name__ == "__main__":
    unittest.main()
