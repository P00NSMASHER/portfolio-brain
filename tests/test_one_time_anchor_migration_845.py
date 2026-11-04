"""Adversarial, offline one-time trust-root migration policy regressions."""
import base64
import hashlib
from copy import deepcopy
import unittest
from unittest.mock import patch

from verification import one_time_anchor_migration_845 as m

HEAD = "c" * 40
MAIN = "b" * 40


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.writes = []
        self.protected = True
        self.main = MAIN
        self.pr_head = HEAD
        self.pr_base = MAIN
        self.pr_branch = m.PR_BRANCH
        self.pr_draft = True
        self.pr_user = "P00NSMASHER"
        self.compare_rows = [
            {"filename": k, "sha": v, "status": "modified"}
            for k, v in m.SOURCE_BLOBS.items()
        ]
        self.lineage = m.BASELINE_SHA
        self.foundation_issuer = m.FOUNDATION_APP
        self.foundation_conclusion = "success"
        self.independent_issuer = m.INDEPENDENT_APP
        self.gate_conclusion = "failure"
        self.gate_enabled = True
        self.bad_census = False
        self.bad_check_readback = False

    def read(self, path):
        self.calls.append(("GET", path))
        if path == "/branches/main":
            return {"protected": self.protected, "commit": {"sha": self.main}}
        if path == "/pulls/845":
            return {
                "number": 845, "state": "open", "draft": self.pr_draft,
                "merged": False, "user": {"login": self.pr_user},
                "head": {"ref": self.pr_branch, "sha": self.pr_head,
                         "repo": {"full_name": m.REPOSITORY}},
                "base": {"ref": "main", "sha": self.pr_base,
                         "repo": {"full_name": m.REPOSITORY}},
            }
        if path == "/compare/" + m.BASELINE_SHA + "..." + MAIN:
            return {"merge_base_commit": {"sha": self.lineage}, "behind_by": 0}
        if path == "/compare/" + MAIN + "..." + HEAD:
            return {"merge_base_commit": {"sha": MAIN}, "behind_by": 0,
                    "files": deepcopy(self.compare_rows)}
        if path == "/commits/" + HEAD + "/check-runs?per_page=100":
            rows = [{
                "name": "validate", "head_sha": HEAD, "status": "completed",
                "conclusion": self.foundation_conclusion,
                "app": {"id": self.foundation_issuer},
            }]
            if self.gate_enabled:
                rows.append({
                    "name": m.CHECK_NAME, "head_sha": HEAD,
                    "status": "completed", "conclusion": self.gate_conclusion,
                    "app": {"id": self.independent_issuer},
                })
            return {"total_count": len(rows) + int(self.bad_census),
                    "check_runs": rows}
        if path == "/check-runs/901":
            return {
                "id": 901, "name": m.CHECK_NAME, "head_sha": HEAD,
                "status": "completed", "conclusion":
                "failure" if self.bad_check_readback else "success",
                "app": {"id": m.INDEPENDENT_APP},
            }
        raise AssertionError("unapproved fake request: " + path)

    def post(self, path, payload):
        self.writes.append((path, deepcopy(payload)))
        return {"id": 901}


def fake_blobs(_read, path, ref):
    if ref == HEAD:
        return m.SOURCE_BLOBS[path]
    if ref == MAIN:
        return m.MAIN_PREIMAGES[path]
    raise AssertionError(ref)


class MigrationProofTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeGitHub()
        self.blobs = patch.object(m, "file_blob", side_effect=fake_blobs)
        self.blobs.start()
        self.addCleanup(self.blobs.stop)

    def verify(self, *, require_original_failure=True):
        return m.verify_source(self.provider.read, HEAD, MAIN,
                               require_original_failure=require_original_failure)

    def test_valid_exact_source_and_original_independent_red_are_read_only(self):
        receipt = self.verify()
        self.assertEqual(receipt["status"],
                         "EXACT_SOURCE_INDEPENDENTLY_READ_NOT_APPROVED")
        self.assertEqual(receipt["candidate_files"], sorted(m.SOURCE_BLOBS))
        self.assertEqual(receipt["source_sha"], HEAD)
        self.assertEqual(receipt["provider_writes"], 0)
        self.assertEqual(self.provider.writes, [])

    def test_only_one_genuine_app_check_is_published_after_source_proof(self):
        result = m.issue_exact_check(self.provider.read,
                                     self.provider.post, HEAD, MAIN)
        self.assertEqual(result["check_run_id"], 901)
        self.assertEqual(result["app_id"], m.INDEPENDENT_APP)
        self.assertFalse(result["merged"])
        self.assertEqual(len(self.provider.writes), 1)
        path, payload = self.provider.writes[0]
        self.assertEqual(path, "/check-runs")
        self.assertEqual(payload["name"], m.CHECK_NAME)
        self.assertEqual(payload["head_sha"], HEAD)
        self.assertEqual(payload["conclusion"], "success")
        self.assertEqual([x[0] for x in self.provider.calls], ["GET"] *
                         len(self.provider.calls))

    def test_wrong_head_branch_owner_draft_or_protected_main_is_blocked(self):
        for field, bad in (
            ("pr_head", "d" * 40),
            ("pr_branch", "malicious/self-approve"),
            ("pr_user", "github-actions[bot]"),
            ("pr_draft", False),
            ("protected", False),
            ("main", "e" * 40),
            ("pr_base", "e" * 40),
            ("lineage", "f" * 40),
        ):
            with self.subTest(field=field):
                self.provider = FakeGitHub()
                setattr(self.provider, field, bad)
                with self.assertRaises(m.MigrationDenied):
                    self.verify()
                self.assertEqual(self.provider.writes, [])

    def test_unreviewed_renames_extra_files_and_modified_blobs_fail(self):
        for mutation in ("rename", "extra", "new_blob", "previous_name",
                         "wrong_status", "deleted", "duplicates"):
            with self.subTest(mutation=mutation):
                self.provider = FakeGitHub()
                row = self.provider.compare_rows[0]
                if mutation == "rename":
                    row["status"] = "renamed"
                    row["previous_filename"] = "verification/old_verifier.py"
                if mutation == "extra":
                    self.provider.compare_rows.append({
                        "filename": "docs/extra.md", "status": "added",
                        "sha": "f" * 40})
                if mutation == "new_blob":
                    row["sha"] = "e" * 40
                if mutation == "previous_name":
                    row["previous_filename"] = "verification/old_verifier.py"
                if mutation == "wrong_status":
                    row["status"] = "added"
                if mutation == "deleted":
                    row["status"] = "removed"
                if mutation == "duplicates":
                    self.provider.compare_rows[1] = deepcopy(row)
                with self.assertRaises(m.MigrationDenied):
                    self.verify()
                self.assertEqual(self.provider.writes, [])

    def test_wrong_foundation_issuer_or_original_independent_gate_blocked(self):
        for field, value in (
            ("foundation_issuer", 123),
            ("foundation_conclusion", "failure"),
            ("independent_issuer", 9999),
            ("gate_conclusion", "success"),
            ("gate_conclusion", "neutral"),
            ("gate_enabled", False),
            ("bad_census", True),
        ):
            with self.subTest(field=field, value=value):
                self.provider = FakeGitHub()
                setattr(self.provider, field, value)
                with self.assertRaises(m.MigrationDenied):
                    m.issue_exact_check(self.provider.read,
                                        self.provider.post, HEAD, MAIN)
                self.assertEqual(self.provider.writes, [])

    def test_bad_post_write_readback_never_claims_verified_check(self):
        self.provider.bad_check_readback = True
        with self.assertRaisesRegex(m.MigrationDenied, "READBACK"):
            m.issue_exact_check(self.provider.read,
                                self.provider.post, HEAD, MAIN)
        self.assertEqual(len(self.provider.writes), 1)

    def test_transport_has_no_merge_admin_or_unrelated_repo_write_routes(self):
        for method, route in (
            ("POST", "/pulls/845/merge"),
            ("POST", "/rulesets/24182301"),
            ("PUT", "/check-runs"),
            ("GET", "/actions/secrets"),
            ("GET", "//evil.example"),
            ("GET", "/contents/.github/workflows/production.yml?ref=" + HEAD),
        ):
            with self.subTest(method=method, route=route):
                self.assertFalse(m.valid_route(method, route))
        self.assertTrue(m.valid_route("POST", "/check-runs"))

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in (b'{"id":1,"id":2}', b'{"x":NaN}', b'\xff'):
            with self.subTest(raw=raw):
                with self.assertRaises(m.MigrationDenied):
                    m.json_strict(raw)

    def test_original_github_blob_digest_and_size_bound(self):
        self.blobs.stop()
        self.addCleanup(lambda: None)
        raw = b"original immutable file\n"
        blob = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\x00" + raw).hexdigest()
        def read(_):
            return {"type": "file", "encoding": "base64", "size": len(raw),
                    "content": base64.b64encode(raw).decode(), "sha": blob}
        self.assertEqual(
            m.file_blob(read, "verification/independent_verifier.py", HEAD),
            blob)
        def changed(_):
            data = read(_)
            data["sha"] = "a" * 40
            return data
        with self.assertRaisesRegex(m.MigrationDenied, "BLOB_HASH"):
            m.file_blob(changed, "verification/independent_verifier.py", HEAD)


if __name__ == "__main__":
    unittest.main()
