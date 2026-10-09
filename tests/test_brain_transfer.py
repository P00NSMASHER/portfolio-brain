"""Independent contract tests for source -> actual GitHub PR technical evidence.

No external network, automated feedback, customer data or production mutations.
"""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain.adapters import event
from brain.__main__ import main as brain_cli
from brain.core import BrainError, Store
from brain.transfer import review_transfer, write_transfer_review

BRAIN_SHA = "a" * 40
SOURCE_SHA = "b" * 40
SOURCE_BLOB = "c" * 40
SOURCE_DIGEST = "d" * 64
PR_HEAD = "e" * 40
NOW = "2026-10-08T22:00:00Z"
SOURCE_REPO = "Jacob-Met/workflow-checks"
SOURCE_PATH = "freight_packets/freightpkt/invoice_match.py"
KEY = SOURCE_REPO + ":" + SOURCE_PATH
SOURCE_URL = f"https://github.com/{SOURCE_REPO}/blob/{SOURCE_SHA}/{SOURCE_PATH}"
TARGET = "P00NSMASHER/github-value-hunt-ledger"
PREFIX = "/repos/" + TARGET
REQUIRED = ("freight", "recoveryworks", "release-gate", "contracts", "verify")


def request(**changes):
    data = {
        "schema_version": 1, "candidate_key": KEY,
        "target_repository": TARGET, "pull_request_number": 343,
        "expected_head_sha": PR_HEAD,
    }
    data.update(changes)
    return data


def responses():
    checks = []
    for index, name in enumerate((*REQUIRED, "deploy")):
        checks.append({
            "id": index + 1, "name": name, "status": "completed",
            "conclusion": "skipped" if name == "deploy" else "success",
            "head_sha": PR_HEAD, "app": {"id": 15368},
            "details_url": f"https://github.com/{TARGET}/actions/runs/{index + 1}",
        })
    return {
        PREFIX: {
            "full_name": TARGET, "private": False, "default_branch": "main",
        },
        PREFIX + "/pulls/343": {
            "number": 343, "state": "open", "draft": True, "merged": False,
            "changed_files": 3,
            "head": {"sha": PR_HEAD, "repo": {"full_name": TARGET}},
            "base": {"ref": "main", "repo": {"full_name": TARGET}},
            "body": "Source:\n" + SOURCE_URL + "\nProposal is only a review.",
        },
        PREFIX + "/pulls/343/files?per_page=100": [
            {"filename": "freight/duplicate_charge_review.py"},
            {"filename": "freight/test_invoice_reference_review.py"},
            {"filename": "freight/BRAIN_INVOICE_REFERENCE_TRANSFER_REVIEW_20261008.md"},
        ],
        PREFIX + "/commits/" + PR_HEAD + "/check-runs?per_page=100": {
            "total_count": len(checks), "check_runs": checks,
        },
    }


class StubGitHub:
    def __init__(self, docs=None):
        self.docs = docs if docs is not None else responses()
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if path not in self.docs:
            raise AssertionError("Unexpected GET: " + path)
        return copy.deepcopy(self.docs[path])


class TransferEvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = Store(self.root / "state.sqlite", visibility="PUBLIC")
        self.addCleanup(self.store.close)
        repository = {
            "repository": "P00NSMASHER/portfolio-brain",
            "head_sha": BRAIN_SHA,
            "default_branch": "main",
            "checks": [],
            "open_issues": 7,
            "source_ref": "https://github.com/P00NSMASHER/portfolio-brain/commit/" + BRAIN_SHA,
        }
        source = {
            "repository": SOURCE_REPO, "head_sha": SOURCE_SHA, "path": SOURCE_PATH,
            "blob_sha": SOURCE_BLOB, "code_sha256": SOURCE_DIGEST,
            "bytes": 5285, "test_paths": ["freight_packets/tests/test_freight.py"],
            "license": "MIT", "source_ref": SOURCE_URL,
            "target": "freight-recovery", "query": "freight invoice audit",
            "matched_terms": ["invoice", "freight"],
        }
        self.store.submit([
            event("repository", repository["repository"], repository,
                  BRAIN_SHA, now=NOW),
            event("candidate", KEY, source, BRAIN_SHA, now=NOW),
        ], now=NOW)
        self.store.drain()
        self.store.report(BRAIN_SHA, now=NOW)

    def trusted(self):
        return self.store.read_report(BRAIN_SHA, now=NOW)

    def run_review(self, *, docs=None, req=None):
        return review_transfer(self.trusted(), request() if req is None else req,
                               api=StubGitHub(docs))

    def test_real_shape_draft_pr_green_is_only_technical_not_adoption(self):
        api = StubGitHub()
        out = review_transfer(self.trusted(), request(), api=api)
        self.assertEqual(out["status"], "DRAFT_PR_CHECKS_PASSED_NOT_ADOPTED")
        self.assertEqual(out["checks"]["status"], "GITHUB_REPORTED_REQUIRED_CHECKS_SUCCESS")
        self.assertEqual(out["checks"]["matched_required_count"], 5)
        self.assertEqual(out["target"]["pr_head_sha"], PR_HEAD)
        self.assertTrue(out["target"]["draft"])
        self.assertFalse(out["target"]["merged_pr_metadata"])
        self.assertEqual(out["origin"]["source_ref"], SOURCE_URL)
        self.assertEqual(out["origin"]["code_sha256"], SOURCE_DIGEST)
        self.assertEqual(out["origin"]["attribution"], "EXACT_SOURCE_LINK_CLAIMED_IN_PR")
        self.assertFalse(out["origin"]["original_code_executed"])
        self.assertEqual(out["integration"], "NOT_VERIFIED_BY_PULL_REQUEST_CHECKS")
        self.assertEqual(out["operator_feedback"], "NOT_COLLECTED")
        self.assertEqual(out["realized_recovery"], "NOT_VERIFIED")
        self.assertEqual(out["revenue"], "NOT_VERIFIED")
        self.assertEqual(out["time_saved"], "UNMEASURED")
        self.assertFalse(out["event_written"])
        self.assertEqual(out["github_mutations"], 0)
        self.assertEqual(api.calls, [
            PREFIX,
            PREFIX + "/pulls/343",
            PREFIX + "/pulls/343/files?per_page=100",
            PREFIX + "/commits/" + PR_HEAD + "/check-runs?per_page=100",
            PREFIX + "/pulls/343",
        ])

    def test_review_is_deterministic_and_does_not_write_canonical_ledger(self):
        before = {
            table: self.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in ("events", "ledger", "reports", "attempts")
        }
        a = self.run_review()
        b = self.run_review()
        self.assertEqual(a, b)
        after = {
            table: self.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in before
        }
        self.assertEqual(before, after)

    def test_real_cli_entrypoint_reads_existing_authority_without_mutating_events(self):
        source = self.root / "input.json"
        source.write_text(json.dumps(request()))
        destination = self.root / "cli-result"
        original = self.root / "state.sqlite"
        original_bytes_sha256 = hashlib.sha256(original.read_bytes()).hexdigest()
        original_stat = original.stat()
        # The real authority must not be chmod'd from a read-only mode merely
        # because the CLI's Store wrapper normally performs initialization.
        os.chmod(original, 0o400)
        original_mode = original.stat().st_mode & 0o777
        original_mtime = original.stat().st_mtime_ns
        tables = ("events", "ledger", "reports", "attempts")
        before = {
            table: self.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in tables
        }
        with patch("brain.__main__.source_sha", return_value=BRAIN_SHA):
            with patch("brain.__main__.GitHub", return_value=StubGitHub()):
                code = brain_cli([
                    "transfer-review", "--db", str(self.root / "state.sqlite"),
                    "--input", str(source), "--output", str(destination),
                    "--expected-sha", BRAIN_SHA,
                ])
        self.assertEqual(code, 0)
        generated = json.loads((destination / "transfer-review.json").read_text())
        self.assertEqual(generated["status"], "DRAFT_PR_CHECKS_PASSED_NOT_ADOPTED")
        after = {
            table: self.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in tables
        }
        self.assertEqual(after, before)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), original_bytes_sha256)
        self.assertEqual(original.stat().st_mtime_ns, original_mtime)
        self.assertEqual(original.stat().st_mode & 0o777, original_mode)
        self.assertEqual(os.stat(destination / "transfer-review.json").st_mode & 0o777, 0o600)

    def test_cli_rejects_symlinked_or_corrupt_source_before_writing_receipt(self):
        source = self.root / "input.json"
        source.write_text(json.dumps(request()))
        original = self.root / "state.sqlite"
        alias = self.root / "aliased-authority.sqlite"
        alias.symlink_to(original)
        corrupt = self.root / "invalid.sqlite"
        corrupt.write_bytes(b"This is not a real SQLite database.")
        for name, path in (("symlink", alias), ("corrupt", corrupt)):
            with self.subTest(name=name):
                out = self.root / ("blocked-" + name)
                with patch("brain.__main__.source_sha", return_value=BRAIN_SHA):
                    code = brain_cli([
                        "transfer-review", "--db", str(path),
                        "--input", str(source), "--output", str(out),
                        "--expected-sha", BRAIN_SHA,
                    ])
                self.assertEqual(code, 1)
                self.assertFalse((out / "transfer-review.json").exists())
        self.assertTrue(alias.is_symlink())
        self.assertEqual(corrupt.read_bytes(), b"This is not a real SQLite database.")

    def test_cli_refuses_missing_sqlite_instead_of_creating_new_authority(self):
        nonexistent = self.root / "does-not-exist.sqlite"
        source = self.root / "input.json"
        source.write_text(json.dumps(request()))
        with patch("brain.__main__.source_sha", return_value=BRAIN_SHA):
            code = brain_cli([
                "transfer-review", "--db", str(nonexistent),
                "--input", str(source), "--output", str(self.root / "blocked"),
                "--expected-sha", BRAIN_SHA,
            ])
        self.assertEqual(code, 1)
        self.assertFalse(nonexistent.exists())
        self.assertFalse((self.root / "blocked" / "transfer-review.json").exists())

    def test_receipt_writer_never_follows_file_or_directory_symlinks(self):
        report = self.run_review()
        original = self.root / "state.sqlite"
        original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        original_time = original.stat().st_mtime_ns
        original_mode = original.stat().st_mode & 0o777

        file_dest = self.root / "danger-file"
        file_dest.mkdir()
        (file_dest / "transfer-review.json").symlink_to(original)
        with self.assertRaisesRegex(BrainError, "TRANSFER_OUTPUT_SYMLINK_OR_FILE_REFUSED"):
            write_transfer_review(report, file_dest)

        dir_alias = self.root / "danger-dir"
        dir_alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(BrainError, "TRANSFER_OUTPUT_SYMLINK_REFUSED"):
            write_transfer_review(report, dir_alias)

        nested = self.root / "parent-symlink"
        nested.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(BrainError, "TRANSFER_OUTPUT_SYMLINK_REFUSED"):
            write_transfer_review(report, nested / "subdirectory")

        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(original.stat().st_mtime_ns, original_time)
        self.assertEqual(original.stat().st_mode & 0o777, original_mode)
        self.assertTrue((file_dest / "transfer-review.json").is_symlink())

    def test_receipt_written_to_local_private_output_only(self):
        report = self.run_review()
        path = write_transfer_review(report, self.root / "out")
        self.assertEqual(path.name, "transfer-review.json")
        self.assertEqual(json.loads(path.read_text()), report)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(path.parent).st_mode & 0o777, 0o700)

    def test_green_checks_without_exact_source_attribution_are_blocked(self):
        docs = responses()
        docs[PREFIX + "/pulls/343"]["body"] = "Unrelated source or fabricated description."
        out = self.run_review(docs=docs)
        self.assertEqual(out["status"], "TRANSFER_TECHNICAL_EVIDENCE_BLOCKED")
        self.assertEqual(out["origin"]["attribution"], "ORIGIN_LINK_NOT_CORROBORATED")
        self.assertEqual(out["checks"]["status"], "GITHUB_REPORTED_REQUIRED_CHECKS_SUCCESS")

    def test_pr_head_or_status_change_during_check_fetch_fails_closed(self):
        # The first PR response and all checks are otherwise valid. Mutating
        # only the SECOND PR read simulates an actual provider race, not an
        # incorrect initial request or fake bad check.
        scenarios = (
            ("head moved", lambda p: p["head"].update(sha="f" * 40)),
            ("draft changed", lambda p: p.update(draft=False)),
            ("closed", lambda p: p.update(state="closed")),
            ("merged", lambda p: p.update(state="closed", merged=True, draft=False)),
            ("source attribution withdrawn", lambda p: p.update(body="link deleted")),
            ("scope changed", lambda p: p.update(changed_files=2)),
            ("base changed", lambda p: p["base"].update(ref="staging")),
            ("repo replaced", lambda p: p["head"]["repo"].update(full_name="attacker/fork")),
        )
        for label, change in scenarios:
            with self.subTest(label=label):
                class MovingPR(StubGitHub):
                    def get(self, path):
                        answer = super().get(path)
                        if path == PREFIX + "/pulls/343" and self.calls.count(path) == 2:
                            change(answer)
                        return answer
                api = MovingPR()
                with self.assertRaisesRegex(BrainError, "TRANSFER_PR_CHANGED_DURING_REVIEW"):
                    review_transfer(self.trusted(), request(), api=api)
                self.assertEqual(api.calls.count(PREFIX + "/pulls/343"), 2)
                self.assertEqual(len(api.calls), 5)

    def test_nonmaterial_pr_metadata_timestamp_change_is_ignored(self):
        # Harmless provider metadata updates should not produce false blockers.
        class ProviderTimestamp(StubGitHub):
            def get(self, path):
                answer = super().get(path)
                if path == PREFIX + "/pulls/343" and self.calls.count(path) == 2:
                    answer["updated_at"] = "2026-10-09T03:00:00Z"
                return answer
        api = ProviderTimestamp()
        result = review_transfer(self.trusted(), request(), api=api)
        self.assertEqual(result["status"], "DRAFT_PR_CHECKS_PASSED_NOT_ADOPTED")
        self.assertEqual(api.calls.count(PREFIX + "/pulls/343"), 2)

    def test_missing_required_check_blocks_even_if_other_check_is_green(self):
        docs = responses()
        value = docs[PREFIX + "/commits/" + PR_HEAD + "/check-runs?per_page=100"]
        value["check_runs"] = [c for c in value["check_runs"] if c["name"] != "freight"]
        value["total_count"] = len(value["check_runs"])
        out = self.run_review(docs=docs)
        self.assertEqual(out["status"], "TRANSFER_TECHNICAL_EVIDENCE_BLOCKED")
        self.assertEqual(out["checks"]["missing_required"], ["freight"])

    def test_same_named_failed_required_check_cannot_be_hidden_by_pass(self):
        docs = responses()
        check = docs[PREFIX + "/commits/" + PR_HEAD + "/check-runs?per_page=100"]
        failed = dict(check["check_runs"][0], id=90, conclusion="failure")
        check["check_runs"].append(failed)
        check["total_count"] += 1
        out = self.run_review(docs=docs)
        self.assertIn("freight", out["checks"]["failed_or_incomplete_names"])
        self.assertEqual(out["status"], "TRANSFER_TECHNICAL_EVIDENCE_BLOCKED")

    def test_pending_skipped_required_wrong_app_or_wrong_revision_blocks(self):
        for override in (
            {"status": "in_progress", "conclusion": None},
            {"conclusion": "skipped"},
            {"app": {"id": 999999}},
            {"head_sha": "f" * 40},
        ):
            with self.subTest(override=override):
                docs = responses()
                docs[PREFIX + "/commits/" + PR_HEAD + "/check-runs?per_page=100"]["check_runs"][0].update(override)
                if "head_sha" in override:
                    with self.assertRaisesRegex(BrainError, "TRANSFER_CHECK_IDENTITY"):
                        self.run_review(docs=docs)
                else:
                    out = self.run_review(docs=docs)
                    self.assertEqual(out["status"], "TRANSFER_TECHNICAL_EVIDENCE_BLOCKED")

    def test_check_pagination_truncation_and_duplicate_provider_id_fail_closed(self):
        for change in ("truncated", "duplicate", "overcap"):
            with self.subTest(change=change):
                docs = responses()
                value = docs[PREFIX + "/commits/" + PR_HEAD + "/check-runs?per_page=100"]
                if change == "truncated":
                    value["total_count"] += 1
                if change == "duplicate":
                    value["check_runs"][1]["id"] = value["check_runs"][0]["id"]
                if change == "overcap":
                    value["total_count"] = 101
                with self.assertRaisesRegex(BrainError, "TRANSFER_CHECK"):
                    self.run_review(docs=docs)

    def test_mutated_head_base_private_repo_and_out_of_scope_files_block(self):
        scenarios = (
            (PREFIX + "/pulls/343", lambda v: v["head"].update(sha="f" * 40),
             "TRANSFER_PR_WRONG_HEAD"),
            (PREFIX + "/pulls/343", lambda v: v["base"].update(ref="production"),
             "TRANSFER_PR_WRONG_HEAD"),
            (PREFIX, lambda v: v.update(private=True),
             "TRANSFER_TARGET_NOT_PUBLIC"),
            (PREFIX + "/pulls/343/files?per_page=100",
             lambda v: v[0].update(filename=".github/workflows/new-writer.yml"),
             "TRANSFER_PR_OUT_OF_APPROVED_SCOPE"),
        )
        for key, modify, error in scenarios:
            with self.subTest(key=key):
                docs = responses()
                modify(docs[key])
                with self.assertRaisesRegex(BrainError, error):
                    self.run_review(docs=docs)

    def test_closed_unmerged_stays_not_adopted_despite_all_green_checks(self):
        docs = responses()
        docs[PREFIX + "/pulls/343"].update(state="closed", draft=False, merged=False)
        out = self.run_review(docs=docs)
        self.assertEqual(out["status"], "CLOSED_UNMERGED_NOT_ADOPTED")
        self.assertEqual(out["external_use"], "NOT_VERIFIED")

    def test_merged_metadata_is_not_proof_of_deployment_or_customer_value(self):
        docs = responses()
        docs[PREFIX + "/pulls/343"].update(state="closed", draft=False, merged=True)
        out = self.run_review(docs=docs)
        self.assertEqual(out["status"], "MERGED_PR_METADATA_ONLY_NOT_DEPLOYMENT")
        self.assertEqual(out["integration"], "NOT_VERIFIED_BY_PULL_REQUEST_CHECKS")
        self.assertEqual(out["customer_value"], "NOT_VERIFIED")

    def test_missing_or_nonactual_source_cannot_be_claimed_via_pr(self):
        with self.assertRaisesRegex(BrainError, "TRANSFER_CANDIDATE_NOT_UNIQUE"):
            self.run_review(req=request(candidate_key="unobserved/other:x.py"))
        report = self.trusted()
        report["reuse_candidates"][0]["data_kind"] = "SIMULATED"
        with self.assertRaisesRegex(BrainError, "TRANSFER_SOURCE_NOT_ACTUAL"):
            review_transfer(report, request(), api=StubGitHub())

    def test_unknown_target_user_defined_checks_and_extra_input_are_rejected(self):
        for changed in (
            {"target_repository": "attacker/other"},
            {"required_checks": ["trivial-green"]},
            {"schema_version": True},
            {"expected_head_sha": "main"},
            {"pull_request_number": True},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(BrainError):
                    self.run_review(req=request(**changed))


if __name__ == "__main__":
    unittest.main()
