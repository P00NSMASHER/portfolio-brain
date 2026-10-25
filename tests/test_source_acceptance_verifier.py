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


class SourceAcceptanceVerifierTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_and_nonfinite(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(sav.SourceAcceptanceError):
                sav.strict_json(raw)

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
        self.assertIn("startsWith(github.event.workflow_run.head_branch, 'brain-acceptance-')", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotIn("schedule:", workflow)

    def test_failure_does_not_publish_unbound_check(self):
        with mock.patch.object(sav, "verify_acceptance", side_effect=RuntimeError("blocked")), \
             mock.patch.object(sav, "publish_check") as publish, \
             mock.patch.dict("os.environ", {"GITHUB_TOKEN": "read", "PORTFOLIO_VERIFIER_TOKEN": "app"}):
            self.assertEqual(sav.main(["--pr-number", "1", "--head-sha", HEAD]), 1)
        publish.assert_not_called()

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
        branch = "brain-acceptance-aaaaaaaa-20261024"
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

        result = sap.publish_receipt(
            API(), Writer(), source=SOURCE, receipt=receipt, date=date,
        )
        self.assertEqual(result["pr_number"], 901)
        self.assertEqual(result["provider_writes"], 0)

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
