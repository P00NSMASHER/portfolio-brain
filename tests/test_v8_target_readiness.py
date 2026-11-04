"""Regression: never mint a CaptureBrief writer token for stale target main."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from brain.v8 import target_readiness as target
from brain.v8 import repair_runtime


def current_branch(sha=target.EXPECTED_TARGET_HEAD, protected=True):
    return {"commit": {"sha": sha}, "protected": protected}


class CaptureBriefPremintTests(unittest.TestCase):
    def test_exact_current_reviewed_protected_main_is_eligible(self):
        result = target.assess_branch(current_branch())
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "EXACT_REVIEWED_TARGET_SOURCE")

    def test_actual_source_drift_never_requests_writer_token(self):
        # Current original provider main is no longer the reviewed 4a7c source.
        result = target.assess_branch(current_branch("1f783833ac8cc42ab5d7ef183eac2c3a146c01d5"))
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "TARGET_SOURCE_CHANGED_NO_TOKEN")

    def test_guide_repair_changes_only_the_wrong_branch_reference(self):
        canonical = "The website build guide lives on gh-pages."
        release = ("Start. See `DEPLOYMENT-TARGET.md` and `STANDALONE_SITE.md` on `gh-pages`. "
                   "End.")
        runtime = repair_runtime
        with patch.object(runtime, "LINK_CANONICAL_BLOB", runtime.digest_blob(canonical.encode())), \
             patch.object(runtime, "LINK_RELEASE_BLOB", runtime.digest_blob(release.encode())):
            fixed = runtime.repair_guide_links(canonical, release)
            self.assertEqual(fixed, "Start. See the [deployment target on main](DEPLOYMENT-TARGET.md) "
                             "and the [standalone build guide on gh-pages]"
                             "(https://github.com/P00NSMASHER/capturebrief/blob/gh-pages/STANDALONE_SITE.md). End.")
            for changed in ((canonical + "!", release), (canonical, release + "!")):
                with self.assertRaisesRegex(ValueError, "REVIEWED_GUIDE_LINK_SOURCE_CHANGED"):
                    runtime.repair_guide_links(*changed)

    def test_after_premint_drift_to_historical_recipe_refuses_any_write(self):
        runtime = repair_runtime
        def read(method, path):
            self.assertEqual(method, "GET")
            if path.startswith("installation/"):
                return {"total_count": 1, "repositories": [{"full_name": runtime.TARGET}]}
            if path == "repos/" + runtime.TARGET:
                return {"full_name": runtime.TARGET, "archived": False, "default_branch": "main"}
            self.assertTrue(path.endswith("/branches/main"))
            return current_branch(runtime.EXPECTED_TARGET_HEAD)
        result = runtime.execute(read, installation=runtime.INSTALLATION, slug=runtime.APP_SLUG,
                                 expected_source=runtime.LINK_REPAIR_HEAD)
        self.assertEqual(result["status"], "TARGET_SOURCE_CHANGED_NO_MUTATION")
        self.assertEqual(result["provider_writes"], 0)

    def test_unprotected_missing_or_invalid_branch_fails_closed(self):
        inputs = [
            current_branch(protected=False), {"commit": {"sha": "not-a-sha"}},
            {"commit": None}, {}, [], {"protected": True},
        ]
        for doc in inputs:
            with self.subTest(doc=doc):
                self.assertFalse(target.assess_branch(doc)["ready"])

    def test_unavailable_source_fails_closed_without_exception_or_token(self):
        for exc in (OSError("network"), ValueError("invalid JSON"),
                    TypeError("bad response")):
            with self.subTest(exc=type(exc).__name__):
                response = target.preflight(lambda: (_ for _ in ()).throw(exc))
                self.assertEqual(response["status"], "TARGET_PROVIDER_UNAVAILABLE_NO_TOKEN")
                self.assertFalse(response["ready"])

    def test_exact_one_readonly_bounded_get(self):
        doc = current_branch()
        seen = {}
        class Response(io.BytesIO):
            status = 200
        class FakeOpener:
            def open(self, request, timeout):
                seen["url"] = request.full_url
                seen["method"] = request.get_method()
                seen["timeout"] = timeout
                seen["data"] = request.data
                return Response(json.dumps(doc).encode())
        with patch.dict(os.environ, {"GH_TOKEN": "x" * 32}):
            with patch.object(target.urllib.request, "build_opener",
                              return_value=FakeOpener()) as opener:
                self.assertEqual(target.fetch_target_branch(), doc)
        self.assertEqual(seen["url"], target.TARGET_URL)
        self.assertEqual(seen["method"], "GET")
        self.assertIsNone(seen["data"])
        self.assertEqual(seen["timeout"], 10)
        self.assertIsInstance(opener.call_args.args[0], target.NoRedirect)

    def test_runner_receipt_and_gate_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "github-output.txt"
            out.touch()
            env = {"GITHUB_OUTPUT": str(out), "RUNNER_TEMP": td}
            with patch.dict(os.environ, env):
                with patch.object(target, "preflight", return_value={
                    "ready": False, "status": "TARGET_SOURCE_CHANGED_NO_TOKEN"}):
                    self.assertEqual(target.main(), 0)
            self.assertEqual(out.read_text(), "ready=false\n")
            receipt = json.loads((Path(td) / "v8-target-preflight.json").read_text())
            self.assertFalse(receipt["ready"])
            self.assertFalse(receipt["writer_token_issued"])
            self.assertEqual(receipt["phase"], "READ_ONLY_BEFORE_APP_TOKEN")

    def test_trusted_workflow_pins_source_and_gates_both_token_and_writer(self):
        wf = Path(".github/workflows/v8-scoped-repair.yml").read_text()
        script = Path("brain/v8/target_readiness.py").read_bytes()
        sha = hashlib.sha1(
            b"blob " + str(len(script)).encode() + b"\0" + script).hexdigest()
        self.assertIn('test "$(git hash-object brain/v8/target_readiness.py)" = "' +
                      sha + '"', wf)
        self.assertEqual(target.EXPECTED_TARGET_HEAD,
                         repair_runtime.LINK_REPAIR_HEAD)
        self.assertFalse(target.assess_branch(current_branch(repair_runtime.EXPECTED_TARGET_HEAD))["ready"])
        preflight = wf.index("- name: Read protected CaptureBrief source before requesting a writer token")
        mint = wf.index("- name: Mint one-CaptureBrief-repository short-lived draft-only contents token")
        writer = wf.index("- name: Reobserve canonical docs and create ONLY source-bound draft PR")
        self.assertLess(preflight, mint)
        self.assertLess(mint, writer)
        guard = "steps.target-source.outputs.ready == 'true'"
        self.assertEqual(wf.count(guard), 2)
        self.assertIn("GH_TOKEN: ${{ github.token }}", wf)
        self.assertIn("python -I \"$RUNNER_TEMP/v8-target-source.py\"", wf)
        self.assertIn("v8-target-preflight.json", wf)
        self.assertNotIn("permission-workflows:", wf)
        self.assertNotIn("schedule:", wf)


if __name__ == "__main__":
    unittest.main()
