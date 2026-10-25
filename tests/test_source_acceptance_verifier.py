import hashlib
import base64
import json
from pathlib import Path
import unittest
from unittest import mock

from verification import source_acceptance_verifier as sav
from verification import source_acceptance_producer as sap


HEAD = "b" * 40
SOURCE = "a" * 40


def source_receipt_api(dates):
    heads = {date: hex(11 + index)[2:] * 40 for index, date in enumerate(dates)}
    branches = {date: f"brain-acceptance-aaaaaaaa-{date}" for date in dates}
    numbers = {date: 901 + index for index, date in enumerate(dates)}
    rows = [
        {"number": numbers[date], "head": {"ref": branches[date]}}
        for date in dates
    ]

    class API:
        def get(self, route):
            if route == "/pulls?state=open&base=main&per_page=100":
                return json.dumps(rows).encode()
            raise AssertionError(route)

        def json(self, route):
            for date in dates:
                branch = branches[date]
                head = heads[date]
                number = numbers[date]
                path = f"acceptance/finish-soak-aaaaaaaa-{date}.json"
                receipt = {
                    "source_sha": SOURCE, "decision": "RELEASED", "status": "PASS",
                    "scope": sav.SCOPE,
                    "decision_date_utc": f"{date[:4]}-{date[4:6]}-{date[6:]}",
                }
                raw = (json.dumps(receipt, sort_keys=True) + "\n").encode()
                if route == f"/pulls/{number}":
                    return {
                        "state": "open", "draft": False,
                        "user": {"login": "portfolio-brain-v8-runtime[bot]"},
                        "base": {"ref": "main", "sha": SOURCE},
                        "head": {
                            "ref": branch, "sha": head,
                            "repo": {"full_name": sap.REPOSITORY},
                        },
                    }
                if route == f"/git/commits/{head}":
                    return {"parents": [{"sha": SOURCE}]}
                if route == f"/compare/{SOURCE}...{head}":
                    return {
                        "status": "ahead", "ahead_by": 1, "behind_by": 0,
                        "total_commits": 1,
                        "merge_base_commit": {"sha": SOURCE},
                        "files": [{"filename": path, "status": "added"}],
                    }
                if route == f"/contents/{path}?ref={head}":
                    return {
                        "encoding": "base64",
                        "content": base64.b64encode(raw).decode(),
                        "size": len(raw),
                    }
            raise AssertionError(route)

    return API()


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

    def test_existing_exact_source_receipt_is_reused_across_utc_date_without_writes(self):
        class Writer:
            writes = 0
            def post(self, path, payload):
                raise AssertionError("unexpected write")

        result = sap.publish_receipt(
            source_receipt_api(["20261024"]), Writer(), source=SOURCE,
            receipt={"status": "PASS"}, date="20261025",
        )
        self.assertEqual(result["branch"], "brain-acceptance-aaaaaaaa-20261024")
        self.assertEqual(result["pr_number"], 901)
        self.assertEqual(result["provider_writes"], 0)

    def test_duplicate_open_receipts_for_exact_source_fail_closed_without_writes(self):
        class Writer:
            writes = 0
            def post(self, path, payload):
                raise AssertionError("unexpected write")

        with self.assertRaisesRegex(
            sav.SourceAcceptanceError,
            "multiple open acceptance receipts for exact source",
        ):
            sap.publish_receipt(
                source_receipt_api(["20261024", "20261025"]), Writer(),
                source=SOURCE, receipt={"status": "PASS"}, date="20261025",
            )



if __name__ == "__main__":
    unittest.main()
