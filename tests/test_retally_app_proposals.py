import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from brain import retally_app_proposals as broker


BASE, HEAD = "b"*40, "a"*40
BRANCH = "automation/retally-technology-12345-1"
REQUEST = dict(version=1, lane="technology", base=BASE, head=HEAD, branch=BRANCH, file_count=1, scout_fingerprint="")
RUN = dict(id=12345, run_attempt=1, event="push", conclusion="success", head_branch="main",
           repository={"full_name":broker.REPO}, head_repository={"full_name":broker.REPO},
           path=".github/workflows/technology-intelligence.yml")


class AppProposalTests(unittest.TestCase):
    def test_matching_source_and_explicit_authority(self):
        self.assertTrue(broker.check_request(REQUEST, RUN, BASE))
        self.assertFalse(broker.check_request(REQUEST, RUN, "f"*40))
        with patch.object(broker,"candidate_pr_authority",return_value={"token_mint_allowed":False}):
            with self.assertRaises(ValueError):
                broker.check_request(REQUEST, RUN, BASE)

    def test_app_recovery_receipt_is_an_authorized_scout_source(self):
        request={**REQUEST, "lane":"scout", "scout_fingerprint":"1"*64,
                 "branch":"automation/retally-scout-12345-1"}
        run={**RUN, "event":"repository_dispatch",
             "path":".github/workflows/public-repo-hunter.yml"}
        self.assertTrue(broker.check_request(request, run, BASE))
        with self.assertRaises(ValueError):
            broker.check_request(request, {**run, "event":"pull_request"}, BASE)

    def test_rejects_ineligible_sources(self):
        for changes in (dict(path=".github/workflows/other.yml"),dict(event="pull_request"),
                        dict(run_attempt=2),dict(id=23456),dict(head_branch="topic"),
                        dict(head_repository={"full_name":"other/fork"}),
                        dict(repository={"full_name":"other/fork"}),dict(conclusion="failure")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                broker.check_request(REQUEST, {**RUN,**changes}, BASE)

    def test_receipt_digest_layout_and_size(self):
        for filename in ("retally-app-request.json","../retally-app-request.json"):
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,"w") as f:
                f.writestr(filename,json.dumps(REQUEST))
            raw=stream.getvalue()
            artifact={"size_in_bytes":len(raw),"digest":"sha256:"+hashlib.sha256(raw).hexdigest()}
            if filename.startswith(".."):
                with self.assertRaises(ValueError):
                    broker.read_request(artifact,raw)
            else:
                self.assertEqual(broker.read_request(artifact,raw),REQUEST)
                with self.assertRaises(ValueError):
                    broker.read_request({**artifact,"digest":"broken"},raw)

    def test_write_only_opens_pr_and_reconciles_exact_head_and_bot(self):
        pr={"number":9, "user":{"id":343751880,"login":"portfolio-brain-v8-runtime[bot]"},
            "state":"open","head":{"sha":HEAD,"repo":{"full_name":broker.REPO}},
            "base":{"ref":"main","sha":BASE}}
        with patch.object(broker,"api",side_effect=[{"number":9},pr]) as api:
            broker.create(REQUEST)
        self.assertEqual([c.args[0] for c in api.call_args_list], ["pulls","pulls/9"])
        self.assertEqual(api.call_args_list[0].kwargs["payload"]["head"], BRANCH)
        for changed in ({"user":{"id":123,"login":"portfolio-brain-v8-runtime[bot]"}},
                        {"head":{**pr["head"],"sha":BASE}}):
            with patch.object(broker,"api",side_effect=[{"number":9},{**pr,**changed}]), self.assertRaises(ValueError):
                broker.create(REQUEST)

    def test_existing_pr_and_changed_branch_prevent_open(self):
        artifact={"workflow_run":{"id":12345,"head_branch":"main"},"id":55,
                  "name":broker.ARTIFACT,"expired":False,"size_in_bytes":100}
        with patch.object(broker,"read_request",return_value=REQUEST):
            valid_diff={"status":"ahead","ahead_by":1,"behind_by":0,
                        "files":[{"filename":"evidence.json","status":"modified"}]}
            existing={"number":9,"head":{"sha":HEAD},"base":{"sha":BASE}}
            calls=[RUN,b"data",{"commit":{"sha":BASE}},[existing],valid_diff["files"]]
            with patch.object(broker,"api",side_effect=calls) as api:
                self.assertIsNone(broker.current_request(artifact))
                self.assertFalse(any("payload" in c.kwargs for c in api.call_args_list))
            calls=[RUN,b"data",{"commit":{"sha":BASE}},[],{"object":{"sha":BASE}}]
            with patch.object(broker,"api",side_effect=calls), self.assertRaises(ValueError):
                broker.current_request(artifact)

    def test_stale_receipts_regenerate_only_latest_unsuperseded_worker(self):
        stale_one={**REQUEST,"lane":"scout","base":"1"*40,"scout_fingerprint":"1"*64}
        stale_two={**stale_one,"branch":"automation/retally-scout-23456-1","head":"2"*40}
        artifacts=[{"id":1},{"id":2},{"id":3}]
        inspected=[
            ({**stale_one,"branch":"automation/retally-scout-34567-1"},BASE,"HUNTER-01",True),
            (stale_one,BASE,"HUNTER-01",False),
            (stale_two,BASE,"HUNTER-02",False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output=os.path.join(tmp,"output")
            with patch.dict(os.environ,{"GITHUB_OUTPUT":output}), \
                    patch.object(broker,"api",return_value={"artifacts":artifacts}), \
                    patch.object(broker,"inspect_request",side_effect=inspected), \
                    patch("sys.argv",["retally_app_proposals"]):
                broker.main()
            with open(output,encoding="utf-8") as handle:
                self.assertEqual(handle.read(),f"recovery=HUNTER-02:{BASE}\n")

    def test_invalid_historical_artifact_does_not_block_valid_request(self):
        artifacts=[{"id":1},{"id":2}]
        valid=({**REQUEST},BASE,None,False)
        with tempfile.TemporaryDirectory() as tmp:
            output=os.path.join(tmp,"output")
            with patch.dict(os.environ,{"GITHUB_OUTPUT":output}), \
                    patch.object(broker,"api",return_value={"artifacts":artifacts}), \
                    patch.object(broker,"inspect_request",side_effect=[ValueError("malformed"),valid]), \
                    patch("sys.argv",["retally_app_proposals"]):
                broker.main()
            with open(output,encoding="utf-8") as handle:
                self.assertEqual(handle.read(),"artifact=2\n")

    def test_explicit_publish_remains_fail_closed_for_invalid_artifact(self):
        with patch.object(broker,"api",return_value={"id":1}), \
                patch.object(broker,"current_request",side_effect=ValueError("malformed")), \
                patch("sys.argv",["retally_app_proposals","--publish","1"]), \
                self.assertRaisesRegex(ValueError,"malformed"):
            broker.main()

    def test_successful_no_content_dispatch_is_accepted(self):
        result=type("Result",(),{"stdout":b""})()
        with patch.object(broker.subprocess,"run",return_value=result) as run:
            self.assertIsNone(broker.api("dispatches",payload={"event_type":"test"}))
        self.assertEqual(run.call_args.args[0][2:4],["--method","POST"])

    def test_recovery_dispatch_rechecks_main_and_holds_when_active(self):
        empty={"workflow_runs":[]}
        with patch.object(broker,"api",side_effect=[{"commit":{"sha":BASE}},empty,empty,None]) as api:
            broker.dispatch_recovery("HUNTER-05",BASE)
        self.assertEqual(api.call_args_list[-1].args[0],"dispatches")
        self.assertEqual(api.call_args_list[-1].kwargs["payload"]["client_payload"]["worker"],
                         "HUNTER-05")
        self.assertEqual(api.call_args_list[-1].kwargs["payload"]["client_payload"]["expected_main"],
                         BASE)
        with patch.object(broker,"api",side_effect=[{"commit":{"sha":BASE}},
                                                    {"workflow_runs":[{"id":7}]}]), \
                self.assertRaisesRegex(ValueError,"already active"):
            broker.dispatch_recovery("HUNTER-05",BASE)
