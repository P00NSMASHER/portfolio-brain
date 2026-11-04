import hashlib
import io
import json
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
            for existing,ref in (([{"number":9}],None),([],BASE)):
                calls=[RUN,b"data",{"commit":{"sha":BASE}},existing]
                if ref:
                    calls.append({"object":{"sha":ref}})
                with patch.object(broker,"api",side_effect=calls) as api:
                    if existing:
                        self.assertIsNone(broker.current_request(artifact))
                    else:
                        with self.assertRaises(ValueError):
                            broker.current_request(artifact)
                    self.assertFalse(any("payload" in c.kwargs for c in api.call_args_list))
