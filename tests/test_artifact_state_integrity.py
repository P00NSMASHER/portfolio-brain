import io
import json
import re
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from runtime.artifact_state import ArtifactRestoreError, BudgetedHTTP, validate_runtime_artifact_bundle
from runtime.artifact_restore import InvalidStateArtifact, restore_latest_valid_state
from runtime.state import advance_cycle, bootstrap_state, canonical_hash, cycle_id_for
from agents.heartbeat_state import heartbeat, seed_state as heartbeat_seed, validate_state as validate_heartbeat

ROOT=Path(__file__).resolve().parents[1]


def artifact(member, body, *, duplicate=False):
    out=io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",UserWarning)
        with zipfile.ZipFile(out,"w") as archive:
            archive.writestr(member,body)
            if duplicate:
                archive.writestr(member,body)
    return out.getvalue()


def runtime_bundle(*,tamper_state=False,tamper_receipt=False,disabled=False,omit_receipt=False):
    initial=bootstrap_state(now="2026-09-25T17:00:00Z")
    if disabled:
        receipt={
          "schema_version":"1.0.0","cycle_id":"disabled","mode":"sync",
          "started_at":"2026-09-25T18:00:00Z","finished_at":"2026-09-25T18:00:00Z",
          "status":"DISABLED","reason":"test kill switch","observations":[],"api_requests":0,
        }
        receipt["receipt_hash"]=canonical_hash(receipt)
        state=initial
    else:
        rid="REPO-001";sha=initial["repositories"][rid]["cursor_sha"]
        observations=[{
          "repository_id":rid,"status":"UNCHANGED","source_ref":"main",
          "prior_sha":sha,"current_sha":sha,"observed_at":"2026-09-25T18:00:00Z",
        }]
        receipt={
          "schema_version":"1.0.0",
          "cycle_id":cycle_id_for(initial,mode="observe",target_repository_id=rid,observations=observations),
          "mode":"observe","started_at":"2026-09-25T18:00:00Z","finished_at":"2026-09-25T18:00:00Z",
          "status":"PASS","reason":None,"observations":observations,"api_requests":1,
        }
        receipt["receipt_hash"]=canonical_hash(receipt)
        state=advance_cycle(initial,receipt)
    if tamper_state and state["recent_cycles"]:
        state=json.loads(json.dumps(state))
        state["recent_cycles"][-1]["receipt_hash"]="sha256:"+"9"*64
    if tamper_receipt:
        receipt=json.loads(json.dumps(receipt))
        receipt["api_requests"]+=1
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w") as archive:
        archive.writestr("runtime_state.json",json.dumps(state).encode())
        if not omit_receipt:
            archive.writestr("cycle_receipt.json",json.dumps(receipt).encode())
    return out.getvalue()


class ArtifactStateIntegrityTests(unittest.TestCase):
    def test_runtime_artifact_bundle_binds_state_to_validated_cycle_receipt(self):
        validate_runtime_artifact_bundle(runtime_bundle(),max_archive_bytes=100000,max_member_bytes=50000)

    def test_runtime_artifact_bundle_rejects_tampered_receipt(self):
        with self.assertRaisesRegex(InvalidStateArtifact,"hash mismatch"):
            validate_runtime_artifact_bundle(runtime_bundle(tamper_receipt=True),max_archive_bytes=100000,max_member_bytes=50000)

    def test_runtime_artifact_bundle_rejects_state_receipt_mismatch(self):
        with self.assertRaisesRegex(InvalidStateArtifact,"state/receipt binding mismatch"):
            validate_runtime_artifact_bundle(runtime_bundle(tamper_state=True),max_archive_bytes=100000,max_member_bytes=50000)

    def test_runtime_artifact_bundle_requires_companion_cycle_receipt(self):
        with self.assertRaisesRegex(InvalidStateArtifact,"cycle_receipt.json"):
            validate_runtime_artifact_bundle(runtime_bundle(omit_receipt=True),max_archive_bytes=100000,max_member_bytes=50000)

    def test_runtime_artifact_bundle_accepts_disabled_no_mutation_receipt(self):
        validate_runtime_artifact_bundle(runtime_bundle(disabled=True),max_archive_bytes=100000,max_member_bytes=50000)

    def test_artifact_http_does_not_retry_permanent_failure(self):
        error=HTTPError("https://api.github.com/example",404,"not found",None,None)
        http=BudgetedHTTP("token",max_requests=6,retries=2,backoff=0)
        with patch("runtime.artifact_state.open_url",side_effect=error) as opened:
            with self.assertRaises(ArtifactRestoreError):
                http.bytes("https://api.github.com/example")
        self.assertEqual(opened.call_count,1)
        self.assertEqual(http.requests,1)

    def test_artifact_http_retries_transient_failure(self):
        response=io.BytesIO(b"restored")
        http=BudgetedHTTP("token",max_requests=6,retries=2,backoff=0)
        with patch("runtime.artifact_state.open_url",side_effect=[URLError("temporary"),response]) as opened:
            self.assertEqual(http.bytes("https://api.github.com/example"),b"restored")
        self.assertEqual(opened.call_count,2)
        self.assertEqual(http.requests,2)

    def test_artifact_http_deadline_prevents_retry_backoff_overrun(self):
        now=[10.0]; sleeps=[]
        def unavailable(*_args,**_kwargs):
            now[0]=11.0
            raise URLError("temporary")
        http=BudgetedHTTP("token",max_requests=6,retries=2,backoff=2,
                          deadline=12.0,clock=lambda:now[0],sleep=sleeps.append)
        with patch("runtime.artifact_state.open_url",side_effect=unavailable):
            with self.assertRaisesRegex(ArtifactRestoreError,"time budget"):
                http.bytes("https://api.github.com/example")
        self.assertEqual(http.requests,1)
        self.assertEqual(sleeps,[])

    def test_all_persistent_restorers_use_shared_validated_atomic_restore(self):
        for relative in [
            "runtime/artifact_state.py","cost_governor/artifact_state.py",
            "scheduler/artifact_state.py","notifications/artifact_state.py",
            "hunting/artifact_state.py","agents/artifact_state.py",
            "dashboard/history_artifact_state.py",
        ]:
            body=(ROOT/relative).read_text()
            self.assertIn("from runtime.artifact_restore import restore_latest_valid_state",body,relative)
            self.assertIn("restore_latest_valid_state(",body,relative)
            self.assertIn('expected_head_branch=os.environ.get("GITHUB_REF_NAME")',body,relative)
            self.assertNotIn("write_bytes(",body,relative)

    def state(self,sequence=1,state_id="portfolio-runtime-state"):
        return json.dumps({"schema_version":"1.0.0","state_id":state_id,"sequence":sequence}).encode()

    def candidates(self):
        return {"artifacts":[
            {"id":2,"name":"portfolio-runtime-state","created_at":"2026-09-26T17:00:00Z","expires_at":"2026-10-26T17:00:00Z","archive_download_url":"new","workflow_run":{"id":20,"head_branch":"main","head_sha":"2"*40}},
            {"id":1,"name":"portfolio-runtime-state","created_at":"2026-09-26T16:00:00Z","expires_at":"2026-10-26T16:00:00Z","archive_download_url":"old","workflow_run":{"id":10,"head_branch":"main","head_sha":"1"*40}},
        ]}

    def restore(self,data,payloads,output,metadata_output=None):
        download=payloads if callable(payloads) else payloads.__getitem__
        return restore_latest_valid_state(data,current_run="99",expected_head_branch="main",download=download,output=output,member_name="runtime_state.json",expected_state_id="portfolio-runtime-state",max_archive_bytes=10000,max_state_bytes=1000,metadata_output=metadata_output)

    def test_corrupt_newest_falls_back_to_newest_valid_predecessor(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            status=self.restore(self.candidates(),{"new":b"not-a-zip","old":artifact("runtime_state.json",self.state(4))},output)
            self.assertEqual(status,"RESTORED_AFTER_REJECTING_1_INVALID")
            self.assertEqual(json.loads(output.read_text())["sequence"],4)

    def test_later_uploaded_stale_snapshot_cannot_roll_state_backward(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            metadata=Path(td)/"restore.json"
            status=self.restore(
                self.candidates(),
                {
                    "new":artifact("runtime_state.json",self.state(4)),
                    "old":artifact("runtime_state.json",self.state(9)),
                },
                output,
                metadata,
            )
            self.assertEqual(status,"RESTORED_HIGHEST_SEQUENCE")
            self.assertEqual(json.loads(output.read_text())["sequence"],9)
            receipt=json.loads(metadata.read_text())
            self.assertEqual(receipt["artifact_id"],1)
            self.assertEqual(receipt["source_sequence"],9)
            self.assertTrue(receipt["source_state_hash"].startswith("sha256:"))
            self.assertEqual(receipt["candidates_inspected"],2)

    def test_conflicting_payloads_at_highest_sequence_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            first=json.loads(self.state(9));first["branch"]="first"
            second=json.loads(self.state(9));second["branch"]="second"
            with self.assertRaisesRegex(InvalidStateArtifact,"conflicting state artifacts"):
                self.restore(
                    self.candidates(),
                    {
                        "new":artifact("runtime_state.json",json.dumps(first).encode()),
                        "old":artifact("runtime_state.json",json.dumps(second).encode()),
                    },
                    output,
                )
            self.assertFalse(output.exists())

    def test_canonical_duplicates_at_highest_sequence_restore_newest(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            compact=self.state(9)
            pretty=json.dumps(json.loads(compact),indent=2).encode()
            status=self.restore(
                self.candidates(),
                {
                    "new":artifact("runtime_state.json",pretty),
                    "old":artifact("runtime_state.json",compact),
                },
                output,
            )
            self.assertEqual(status,"RESTORED")
            self.assertEqual(json.loads(output.read_text())["sequence"],9)

    def test_restore_scan_is_bounded(self):
        data={"artifacts":[
            {
                "id":index,
                "created_at":f"2026-09-26T{index:02d}:00:00Z",
                "archive_download_url":f"artifact-{index}",
                "workflow_run":{"id":index,"head_branch":"main"},
            }
            for index in range(10,0,-1)
        ]}
        downloads=[]
        def download(url):
            downloads.append(url)
            return artifact("runtime_state.json",self.state(int(url.rsplit("-",1)[1])))
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            status=self.restore(data,download,output)
            self.assertEqual(status,"RESTORED")
            self.assertEqual(len(downloads),5)
            self.assertEqual(json.loads(output.read_text())["sequence"],10)

    def test_unavailable_newest_falls_back_to_newest_valid_predecessor(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            downloads=[]
            def download(url):
                downloads.append(url)
                if url=="new":
                    raise OSError("archive disappeared after listing")
                return artifact("runtime_state.json",self.state(6))
            status=self.restore(self.candidates(),download,output)
            self.assertEqual(status,"RESTORED_AFTER_REJECTING_1_INVALID")
            self.assertEqual(json.loads(output.read_text())["sequence"],6)
            self.assertEqual(downloads,["new","old"])

    def test_all_unavailable_candidates_fail_closed_without_partial_state(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            with self.assertRaises(InvalidStateArtifact):
                self.restore(self.candidates(),lambda _url: (_ for _ in ()).throw(OSError("gone")),output)
            self.assertFalse(output.exists())

    def test_metadata_receipt_points_to_exact_valid_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            metadata=Path(td)/"restore.json"
            status=self.restore(self.candidates(),{"new":b"bad","old":artifact("runtime_state.json",self.state(9))},output,metadata)
            self.assertEqual(status,"RESTORED_AFTER_REJECTING_1_INVALID")
            receipt=json.loads(metadata.read_text())
            self.assertEqual(receipt["artifact_id"],1)
            self.assertEqual(receipt["source_run_id"],10)
            self.assertEqual(receipt["source_head_sha"],"1"*40)
            self.assertEqual(receipt["artifact_created_at"],"2026-09-26T16:00:00Z")

    def test_identity_mismatch_and_duplicate_member_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            bad_identity=artifact("runtime_state.json",self.state(state_id="attacker-state"))
            duplicate=artifact("runtime_state.json",self.state(),duplicate=True)
            with self.assertRaises(InvalidStateArtifact):
                self.restore(self.candidates(),{"new":bad_identity,"old":duplicate},output)
            self.assertFalse(output.exists())

    def test_current_run_and_expired_artifacts_are_ignored(self):
        data={"artifacts":[
            {"id":3,"created_at":"2026-09-26T18:00:00Z","archive_download_url":"current","workflow_run":{"id":99,"head_branch":"main"}},
            {"id":2,"created_at":"2026-09-26T17:00:00Z","archive_download_url":"expired","expired":True,"workflow_run":{"id":20,"head_branch":"main"}},
            {"id":1,"created_at":"2026-09-26T16:00:00Z","archive_download_url":"valid","workflow_run":{"id":10,"head_branch":"main"}},
        ]}
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            status=self.restore(data,{"valid":artifact("runtime_state.json",self.state(7))},output)
            self.assertEqual(status,"RESTORED")
            self.assertEqual(json.loads(output.read_text())["sequence"],7)

    def test_newer_artifact_from_other_branch_is_ignored(self):
        data={"artifacts":[
            {"id":3,"created_at":"2026-09-26T18:00:00Z","archive_download_url":"feature","workflow_run":{"id":30,"head_branch":"feature/runtime-test"}},
            {"id":2,"created_at":"2026-09-26T17:00:00Z","archive_download_url":"main","workflow_run":{"id":20,"head_branch":"main"}},
        ]}
        downloads=[]
        payloads={"feature":artifact("runtime_state.json",self.state(99)),"main":artifact("runtime_state.json",self.state(8))}
        def download(url):
            downloads.append(url)
            return payloads[url]
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"runtime_state.json"
            status=restore_latest_valid_state(
                data,current_run="99",expected_head_branch="main",download=download,
                output=output,member_name="runtime_state.json",
                expected_state_id="portfolio-runtime-state",
                max_archive_bytes=10000,max_state_bytes=1000,
            )
            self.assertEqual(status,"RESTORED")
            self.assertEqual(json.loads(output.read_text())["sequence"],8)
            self.assertEqual(downloads,["main"])



    def test_two_real_heartbeat_writers_from_same_parent_fail_without_overwriting(self):
        # Hunter and Scheduler both restore N, then independently publish N+1.
        parent = heartbeat_seed()
        first = heartbeat(parent, agent_ids=["AGT-HUNTER"],
                          activity_kind="HUNT", source_workflow="hunter-autonomous-cycle",
                          source_run_id="10", at="2026-09-26T16:00:00Z")
        second = heartbeat(parent, agent_ids=["AGT-PORTFOLIO-MANAGER"],
                           activity_kind="SCHEDULER", source_workflow="portfolio-autonomous-scheduler",
                           source_run_id="20", at="2026-09-26T17:00:00Z")
        self.assertEqual(first["sequence"], second["sequence"])
        self.assertNotEqual(canonical_hash(first), canonical_hash(second))
        payloads = {"old": artifact("agent_heartbeat_state.json", json.dumps(first).encode()),
                    "new": artifact("agent_heartbeat_state.json", json.dumps(second).encode())}
        data = self.candidates()
        for row in data["artifacts"]:
            row["name"] = "portfolio-agent-heartbeat-state"
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "state.json"
            metadata = Path(td) / "restore.json"
            before = json.dumps(parent).encode()
            output.write_bytes(before)
            metadata.write_bytes(b"previous restore evidence")
            with self.assertRaisesRegex(InvalidStateArtifact, "conflicting state artifacts"):
                restore_latest_valid_state(
                    data, current_run="99", expected_head_branch="main",
                    download=payloads.__getitem__, output=output,
                    member_name="agent_heartbeat_state.json",
                    expected_state_id="portfolio-agent-heartbeat-state",
                    max_archive_bytes=100000, max_state_bytes=50000,
                    validator=validate_heartbeat, metadata_output=metadata)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(metadata.read_bytes(), b"previous restore evidence")

    def test_serialized_restore_mutate_publish_preserves_both_real_writers(self):
        first = heartbeat(heartbeat_seed(), agent_ids=["AGT-HUNTER"],
                          activity_kind="HUNT", source_workflow="hunter-autonomous-cycle",
                          source_run_id="10", at="2026-09-26T16:00:00Z")
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "state.json"
            candidates = self.candidates()["artifacts"]
            for row in candidates:
                row["name"] = "portfolio-agent-heartbeat-state"
            data = {"artifacts": [candidates[1]]}
            payloads = {"old": artifact("agent_heartbeat_state.json", json.dumps(first).encode())}
            def restore():
                return restore_latest_valid_state(
                    data, current_run="99", expected_head_branch="main",
                    download=payloads.__getitem__, output=output,
                    member_name="agent_heartbeat_state.json",
                    expected_state_id="portfolio-agent-heartbeat-state",
                    max_archive_bytes=100000, max_state_bytes=50000,
                    validator=validate_heartbeat)
            restore()
            # The next writer restores only AFTER its predecessor publishes.
            second = heartbeat(json.loads(output.read_text()),
                               agent_ids=["AGT-PORTFOLIO-MANAGER"], activity_kind="SCHEDULER",
                               source_workflow="portfolio-autonomous-scheduler",
                               source_run_id="20", at="2026-09-26T17:00:00Z")
            self.assertEqual(second["sequence"], first["sequence"] + 1)
            data["artifacts"].append(candidates[0])
            payloads["new"] = artifact("agent_heartbeat_state.json", json.dumps(second).encode())
            restore()
            final = json.loads(output.read_text())
            self.assertEqual(final["agents"]["AGT-HUNTER"]["source_run_id"], "10")
            self.assertEqual(final["agents"]["AGT-PORTFOLIO-MANAGER"]["source_run_id"], "20")
            self.assertEqual(len(final["recent_events"]), 2)
            validate_heartbeat(final)

    def test_every_canonical_state_writer_uses_global_non_cancelling_lane(self):
        # Discover actual fixed-name state uploads, not just the four known producers.
        # These workflows currently have exactly one job. Refuse a multi-job rewrite
        # until this check explicitly accounts for each writer's effective lock.
        expected = {
            "agent-heartbeat-sweep.yml", "command-center-pages.yml",
            "continuous-learning-bootstrap.yml", "hunter-autonomous-cycle.yml",
            "model-value-proof.yml", "operator-console.yml",
            "portfolio-autonomous-scheduler.yml", "portfolio-notification-cycle.yml",
            "runtime-worker.yml", "software-factory-candidate.yml",
            "verified-feedback-bootstrap.yml",
        }
        found = set()
        for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
            body = path.read_text()
            names = re.findall(r"(?m)^ +name: (portfolio-[a-z0-9-]+)\s*$", body)
            if not any(name.endswith(("-state", "-history")) for name in names):
                continue
            found.add(path.name)
            with self.subTest(workflow=path.name):
                jobs = body.split("\njobs:\n", 1)[1]
                self.assertEqual(len(re.findall(r"(?m)^  [a-zA-Z0-9_-]+:\s*$", jobs)), 1)
                locks = re.findall(r"(?m)^( *)concurrency:\n((?: +[^\n]*\n)+)", body)
                self.assertEqual(len(locks), 1, "writer must have exactly one concurrency lock")
                indent, block = locks[0]
                self.assertIn(indent, ("", "    "))
                pad = indent + "  "
                fields = dict(re.findall(r"(?m)^" + pad + r"(group|cancel-in-progress|queue): ([^\n]+)$", block))
                self.assertEqual(fields, {"group": "portfolio-state-writer-v1",
                                          "cancel-in-progress": "false", "queue": "max"})
        self.assertEqual(found, expected)

    def test_runtime_callers_never_hold_writer_lock_or_cancel_running_worker(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            body = path.read_text()
            if "uses: ./.github/workflows/runtime-worker.yml" not in body:
                continue
            with self.subTest(workflow=path.name):
                self.assertNotIn("group: portfolio-state-writer-v1", body,
                                 "caller would wait for a child that needs its own held lock")
                for value in re.findall(r"(?m)^ +cancel-in-progress: (.+)$", body):
                    self.assertEqual(value, "false")
                if "concurrency:" in body:
                    self.assertIn("queue: max", body)


if __name__=="__main__":unittest.main()
