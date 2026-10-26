import hashlib
import base64
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import unittest
from unittest import mock

from verification import source_acceptance_verifier as sav
from verification import source_acceptance_producer as sap


HEAD = "b" * 40
SOURCE = "a" * 40


class AcceptanceAPI:
    def __init__(self, *, branch=None, pr_head=HEAD, files=None,
                 first_completed="2026-10-24T10:31:00Z"):
        self.branch = (
            branch
            or "auto-repair/pb-01-acceptance-receipt-aaaaaaaa-20261024"
        )
        self.pr_head = pr_head
        date = self.branch.rsplit("-", 1)[-1]
        self.path = f"acceptance/finish-soak-aaaaaaaa-{date}.json"
        self.files = files or [self.path]
        self.first_completed = first_completed

    def json(self, route):
        if route == "/pulls/901":
            return {
                "state": "open", "draft": False,
                "head": {
                    "ref": self.branch, "sha": self.pr_head,
                    "repo": {"full_name": sav.REPOSITORY},
                },
                "base": {
                    "ref": "main", "repo": {"full_name": sav.REPOSITORY},
                },
            }
        if route == "/branches/main":
            return {"commit": {"sha": SOURCE}}
        if route == f"/git/commits/{HEAD}":
            return {"sha": HEAD, "parents": [{"sha": SOURCE}]}
        if route == f"/compare/{SOURCE}...{HEAD}":
            return {
                "ahead_by": 1, "behind_by": 0,
                "merge_base_commit": {"sha": SOURCE},
                "files": [
                    {"filename": path, "status": "added"} for path in self.files
                ],
            }
        if route.startswith("/contents/"):
            receipt = {
                "source_sha": SOURCE, "decision": "RELEASED",
                "status": "PASS", "scope": sav.SCOPE,
                "original_run_evidence": {
                    "all_success_attempt_one": True,
                    "all_original_core_state_parent_child_links_contiguous": True,
                    "all_required_original_job_steps_success": True,
                    "original_artifacts_sha256_size_crc_verified": True,
                    "first_original_monitor_completed_utc": self.first_completed,
                },
            }
            raw = json.dumps(receipt).encode()
            return {
                "encoding": "base64",
                "content": base64.b64encode(raw).decode(),
                "size": len(raw),
            }
        raise AssertionError(route)


class SourceAcceptanceVerifierTests(unittest.TestCase):
    def test_receipt_contract_rejects_authority_and_provenance_drift(self):
        receipt = {
            "schema_version": 2,
            "decision_date_utc": "2026-10-24",
            "decision": "RELEASED",
            "status": "PASS",
            "scope": sav.SCOPE,
            "source_sha": SOURCE,
            "approval_basis": sav.APPROVAL_BASIS,
            "criteria": dict(sav.REQUIRED_CRITERIA),
            "original_run_evidence": {
                "historical_adverse_automatic_cores_for_this_source": [],
                "prior_source_acceptance_is_not_transferable": True,
                "original_proof_status":
                    "SIX_HOUR_ORIGINAL_GITHUB_EVIDENCE_VERIFIED",
            },
            "terminal_state_replay": {},
            "external_cloudflare_provider": {
                "source": (
                    "Original source-bound signed Cloudflare origin records "
                    "retained in GitHub artifacts"
                ),
                "worker_script_name": "portfolio-brain-recovery",
                "only_signed_origin_with_successful_original_github_monitor_counted":
                    True,
                "standalone_worker_invocation_never_counts_as_completed_cycle":
                    True,
            },
            "proof": {},
            "authority_limits": dict(sav.REQUIRED_AUTHORITY_LIMITS),
        }
        sav._verify_receipt_contract(receipt)
        cases = []
        for field in ("criteria", "authority_limits"):
            changed = json.loads(json.dumps(receipt))
            changed[field][next(iter(changed[field]))] = False
            cases.append((field, changed))
        changed = json.loads(json.dumps(receipt))
        changed["external_cloudflare_provider"][
            "standalone_worker_invocation_never_counts_as_completed_cycle"
        ] = False
        cases.append(("external", changed))
        changed = json.loads(json.dumps(receipt))
        changed["original_run_evidence"][
            "prior_source_acceptance_is_not_transferable"
        ] = False
        cases.append(("original", changed))
        for name, changed in cases:
            with self.subTest(name=name):
                with self.assertRaises(sav.SourceAcceptanceError):
                    sav._verify_receipt_contract(changed)

    def test_strict_json_rejects_duplicate_and_nonfinite(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(sav.SourceAcceptanceError):
                sav.strict_json(raw)

    def test_verifier_rejects_unauthorized_or_moved_receipt_branch(self):
        for api in (
            AcceptanceAPI(branch="brain-acceptance-aaaaaaaa-20261024"),
            AcceptanceAPI(pr_head="c" * 40),
        ):
            with self.subTest(branch=api.branch, head=api.pr_head):
                with self.assertRaises(sav.SourceAcceptanceError):
                    sav.verify_acceptance(api, pr_number=901, head_sha=HEAD)

    def test_verifier_rejects_extra_scope_and_wrong_first_core_date(self):
        for api in (
            AcceptanceAPI(files=[
                "acceptance/finish-soak-aaaaaaaa-20261024.json",
                "extra.txt",
            ]),
            AcceptanceAPI(
                branch=(
                    "auto-repair/pb-01-acceptance-receipt-"
                    "aaaaaaaa-20261025"
                ),
            ),
        ):
            with self.subTest(branch=api.branch, files=api.files):
                with self.assertRaises(sav.SourceAcceptanceError):
                    sav.verify_acceptance(api, pr_number=901, head_sha=HEAD)

    def test_publish_check_binds_name_app_source_and_receipt(self):
        external = "source-acceptance:" + SOURCE + ":" + "c" * 64
        expected = {
            "name": sav.CHECK_NAME, "head_sha": HEAD, "external_id": external,
            "app": {"id": sav.VERIFIER_APP_ID}, "id": 7,
        }
        with mock.patch.object(sav, "_app_api", return_value=expected) as call:
            result = sav.publish_check(
                token="token", head_sha=HEAD, external_id=external,
                success=True, summary="verified",
            )
        self.assertEqual(result["id"], 7)
        payload = call.call_args.args[1]
        self.assertEqual(payload["external_id"], external)
        self.assertEqual(payload["conclusion"], "success")

    def test_workflow_is_narrow_and_pins_trusted_main_producer(self):
        workflow = Path(".github/workflows/portfolio-source-acceptance.yml").read_text()
        source = Path("verification/source_acceptance_verifier.py").read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
        self.assertIn(blob, workflow)
        self.assertIn("github.event.workflow_run.event == 'pull_request'", workflow)
        self.assertIn("startsWith(github.event.workflow_run.head_branch, 'auto-repair/pb-01-acceptance-receipt-')", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotIn("schedule:", workflow)

    def test_failure_does_not_publish_unbound_check_or_exception_text(self):
        marker = "UNTRUSTED_VERIFIER_MARKER_MUST_NOT_PERSIST"
        output = io.StringIO()
        with mock.patch.object(
            sav, "verify_acceptance", side_effect=RuntimeError(marker)
        ), mock.patch.object(sav, "publish_check") as publish, \
             mock.patch("sys.stdout", output), \
             mock.patch.dict("os.environ", {
                 "GITHUB_TOKEN": "read", "PORTFOLIO_VERIFIER_TOKEN": "app",
             }):
            self.assertEqual(sav.main(["--pr-number", "1", "--head-sha", HEAD]), 1)
        publish.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), {
            "reason_code": "SOURCE_ACCEPTANCE_VERIFICATION_BLOCKED",
            "status": "BLOCKED",
        })
        self.assertNotIn(marker, output.getvalue())

    def test_receipt_producer_is_automatic_only_and_uses_separate_runtime_app(self):
        workflow = Path(".github/workflows/portfolio-source-acceptance-producer.yml").read_text()
        for path in ("verification/source_acceptance_producer.py",
                     "verification/source_acceptance_verifier.py"):
            source = Path(path).read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
            self.assertIn(blob, workflow)
        self.assertIn("github.event.workflow_run.event == 'schedule'", workflow)
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'", workflow)
        self.assertIn("PORTFOLIO_RUNTIME_PRIVATE_KEY", workflow)
        self.assertIn("python -m verification.source_acceptance_producer", workflow)
        self.assertNotIn("PORTFOLIO_VERIFIER_PRIVATE_KEY", workflow)
        self.assertNotIn("\n  schedule:", workflow)
        self.assertNotIn("pull_request_target:", workflow)

        verifier_workflow = Path(".github/workflows/portfolio-source-acceptance.yml").read_text()
        self.assertIn("python -m verification.source_acceptance_verifier", verifier_workflow)

    def test_source_receipt_key_uses_first_qualifying_core(self):
        first = datetime(2026, 10, 24, 10, 31, tzinfo=timezone.utc)
        later = datetime(2026, 10, 25, 0, 2, tzinfo=timezone.utc)
        self.assertEqual(
            sap._source_receipt_date([{"completed": first}, {"completed": later}]),
            "20261024",
        )

    def test_existing_source_receipt_and_pr_are_reused_without_writes(self):
        receipt = {
            "status": "PASS", "decision": "RELEASED",
            "scope": sav.SCOPE, "source_sha": SOURCE,
            "terminal_state_replay": {"canonical_sequence": 5001},
        }
        existing_receipt = {
            **receipt,
            "terminal_state_replay": {"canonical_sequence": 4921},
        }
        date = "20261024"
        branch = "auto-repair/pb-01-acceptance-receipt-aaaaaaaa-20261024"
        raw = (json.dumps(existing_receipt, indent=2, sort_keys=True) + "\n").encode()

        class API:
            def get(self, route):
                if route.startswith("/git/matching-refs/"):
                    return json.dumps([{"ref": "refs/heads/" + branch,
                                        "object": {"sha": HEAD}}]).encode()
                if route.startswith("/pulls?"):
                    return b'[{"number":901}]'
                raise AssertionError(route)

            def json(self, route):
                return {"encoding": "base64", "content": base64.b64encode(raw).decode(),
                        "size": len(raw)}

        class Writer:
            writes = 0
            def post(self, path, payload):
                raise AssertionError("unexpected write")

        api = API()
        with mock.patch.object(
            sap, "verify_acceptance", return_value=(SOURCE, "source-acceptance:verified"),
        ) as verify:
            result = sap.publish_receipt(
                api, Writer(), source=SOURCE, receipt=receipt, date=date,
            )
        verify.assert_called_once_with(api, pr_number=901, head_sha=HEAD)
        self.assertEqual(result["branch"], branch)
        self.assertEqual(result["pr_number"], 901)
        self.assertEqual(result["provider_writes"], 0)

    def test_reused_truncated_receipt_fails_closed_without_writes(self):
        receipt = {
            "status": "PASS", "decision": "RELEASED",
            "scope": sav.SCOPE, "source_sha": SOURCE,
        }
        date = "20261024"
        branch = "auto-repair/pb-01-acceptance-receipt-aaaaaaaa-20261024"
        raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()

        class API:
            def get(self, route):
                if route.startswith("/git/matching-refs/"):
                    return json.dumps([{
                        "ref": "refs/heads/" + branch,
                        "object": {"sha": HEAD},
                    }]).encode()
                if route.startswith("/pulls?"):
                    return b'[{"number":901}]'
                raise AssertionError(route)

            def json(self, route):
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(raw).decode(),
                    "size": len(raw),
                }

        class Writer:
            writes = 0

            def post(self, path, payload):
                raise AssertionError("unexpected write")

        writer = Writer()
        with mock.patch.object(
            sap, "verify_acceptance",
            side_effect=sav.SourceAcceptanceError("nested evidence missing"),
        ):
            with self.assertRaises(sav.SourceAcceptanceError):
                sap.publish_receipt(
                    API(), writer, source=SOURCE, receipt=receipt, date=date,
                )
        self.assertEqual(writer.writes, 0)

    def test_not_ready_output_never_preserves_exception_text(self):
        marker = "UNTRUSTED_PROVIDER_MARKER_MUST_NOT_PERSIST"
        output = io.StringIO()
        with mock.patch.object(sap, "build_receipt", side_effect=RuntimeError(marker)), \
             mock.patch("sys.stdout", output), \
             mock.patch.dict("os.environ", {
                 "GITHUB_TOKEN": "read", "PORTFOLIO_RUNTIME_TOKEN": "write",
             }):
            self.assertEqual(sap.main(["--source-sha", SOURCE]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value, {
            "reason_code": "SOURCE_ACCEPTANCE_NOT_READY",
            "status": "NOT_READY",
        })
        self.assertNotIn(marker, output.getvalue())

if __name__ == "__main__":
    unittest.main()
