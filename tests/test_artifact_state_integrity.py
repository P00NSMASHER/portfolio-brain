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
from runtime.state import advance_cycle, bootstrap_state, canonical_hash, cycle_id_for, validate_state

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


def runtime_bundle(*,tamper_state=False,tamper_receipt=False,disabled=False,omit_receipt=False,
                   initial_state=None,repository_id="REPO-001"):
    initial=json.loads(json.dumps(initial_state)) if initial_state is not None else bootstrap_state(now="2026-09-25T17:00:00Z")
    if disabled:
        receipt={
          "schema_version":"1.0.0","cycle_id":"disabled","mode":"sync",
          "started_at":"2026-09-25T18:00:00Z","finished_at":"2026-09-25T18:00:00Z",
          "status":"DISABLED","reason":"test kill switch","observations":[],"api_requests":0,
        }
        receipt["receipt_hash"]=canonical_hash(receipt)
        state=initial
    else:
        rid=repository_id;sha=initial["repositories"][rid]["cursor_sha"]
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


# These checks intentionally inspect the repository's block-style workflow YAML;
# a new/unsupported writer layout must be reviewed rather than silently skipped.
WRITER_GROUP = "portfolio-state-writer-v1"
WRITER_WORKFLOWS = {
    "agent-heartbeat-sweep.yml", "command-center-pages.yml",
    "continuous-learning-bootstrap.yml", "hunter-autonomous-cycle.yml",
    "model-value-proof.yml", "operator-console.yml",
    "portfolio-autonomous-scheduler.yml", "portfolio-notification-cycle.yml",
    "runtime-worker.yml", "software-factory-candidate.yml",
    "verified-feedback-bootstrap.yml",
}
CANONICAL_REDUCER_WORKFLOW = "portfolio-state-reducer.yml"
OPERATOR_WRITER_GROUP = "${{ inputs.operation == 'EMERGENCY_STOP' && format('portfolio-emergency-writer-bypass-{0}', github.run_id) || 'portfolio-state-writer-v1' }}"
OPERATOR_ENTRY_GROUP = "${{ inputs.operation == 'EMERGENCY_STOP' && format('portfolio-emergency-entry-{0}', github.run_id) || 'portfolio-operator-console' }}"


def workflow_jobs(text):
    header, separator, jobs = text.partition("\njobs:\n")
    if not separator:
        raise AssertionError("workflow must expose block-style jobs")
    starts = list(re.finditer(r"(?m)^  ([A-Za-z0-9_-]+):[ \t]*$", jobs))
    if not starts:
        raise AssertionError("no inspectable workflow jobs")
    return header, {
        item.group(1): jobs[item.end():starts[i+1].start() if i+1<len(starts) else len(jobs)]
        for i, item in enumerate(starts)
    }


def concurrency_fields(text, indent):
    prefix = " " * indent
    matches = list(re.finditer(r"(?m)^"+prefix+r"concurrency:[ \t]*\n((?:"+prefix+r"  [^\n]*\n)+)", text+"\n"))
    if len(matches) != 1:
        raise AssertionError("expected one explicit concurrency block")
    values = {}
    for line in matches[0].group(1).splitlines():
        key, separator, value = line.strip().partition(":")
        if not separator or key in values:
            raise AssertionError("ambiguous concurrency configuration")
        values[key] = value.strip()
    return values


def artifact_names(text):
    return set(re.findall(r"(?m)^          name: (portfolio-[^\n]+)$", text))


def mutable_artifact_names(text):
    return {name for name in artifact_names(text)
            if name.endswith("-state") or name == "portfolio-command-center-history"}


def assert_writer_contract(filename, text):
    header, jobs = workflow_jobs(text)
    outer = concurrency_fields(header, 0)
    if outer.get("group") == WRITER_GROUP:
        raise AssertionError("global writer mutex must not be reacquired by a child job")
    if outer.get("cancel-in-progress") != "false" or outer.get("queue") != "max":
        raise AssertionError("entry queue can cancel a running or waiting writer")
    guarded = 0
    for job in jobs.values():
        if not mutable_artifact_names(job):
            continue
        guarded += 1
        inner = concurrency_fields(job, 4)
        expected = OPERATOR_WRITER_GROUP if filename == "operator-console.yml" else WRITER_GROUP
        if inner != {"group": expected, "cancel-in-progress": "false", "queue": "max"}:
            raise AssertionError("state publisher lacks the exact non-cancelling global mutex")
        if re.search(r"(?m)^    uses: \./\.github/workflows/", job):
            raise AssertionError("state writer cannot synchronously call a second writer")
    if not guarded:
        raise AssertionError("registered writer publishes no recognized durable state")


class SharedStateWriterRegressionTests(unittest.TestCase):
    def workflows(self):
        return {p.name:p.read_text(encoding="utf-8") for p in (ROOT/".github/workflows").glob("*.yml")}

    def test_every_legacy_mirror_publisher_holds_the_same_job_mutex(self):
        workflows = self.workflows()
        discovered = {name for name,text in workflows.items() if mutable_artifact_names(text)}
        self.assertEqual(discovered, WRITER_WORKFLOWS | {CANONICAL_REDUCER_WORKFLOW}, "review new or removed state publishers")
        for name in sorted(WRITER_WORKFLOWS):
            with self.subTest(workflow=name):
                assert_writer_contract(name, workflows[name])

    def test_sole_canonical_reducer_uses_independent_non_cancelling_lane(self):
        workflows = self.workflows()
        reducer = workflows[CANONICAL_REDUCER_WORKFLOW]
        header, jobs = workflow_jobs(reducer)
        self.assertEqual(concurrency_fields(header,0), {
            "group":"portfolio-state-reducer",
            "cancel-in-progress":"false",
            "queue":"max",
        })
        self.assertNotIn(WRITER_GROUP, jobs["reduce"])
        self.assertIn("portfolio-canonical-shadow-state", jobs["reduce"])
        publishers = [
            name for name,text in workflows.items()
            if "name: portfolio-canonical-shadow-state" in text
        ]
        self.assertEqual(publishers, [CANONICAL_REDUCER_WORKFLOW])

    def test_separate_group_or_cancelling_writer_is_rejected(self):
        text = self.workflows()["hunter-autonomous-cycle.yml"]
        for old,new in [
            ("group: "+WRITER_GROUP, "group: portfolio-hunter-cycle"),
            ("      cancel-in-progress: false", "      cancel-in-progress: true"),
            ("      queue: max", "      queue: single"),
            ("  cancel-in-progress: false", "  cancel-in-progress: true"),
            ("  queue: max", "  queue: single"),
        ]:
            with self.subTest(mutation=new):
                self.assertIn(old, text)
                with self.assertRaises(AssertionError):
                    assert_writer_contract("hunter-autonomous-cycle.yml", text.replace(old,new,1))

    def test_reusable_workflow_callers_cannot_cancel_or_reacquire_writer_lock(self):
        workflows = self.workflows()
        callers = 0
        for name,text in workflows.items():
            header,jobs = workflow_jobs(text)
            for job in jobs.values():
                call = re.search(r"(?m)^    uses: \./\.github/workflows/([^\n]+)$", job)
                if not call or call.group(1) not in WRITER_WORKFLOWS:
                    continue
                callers += 1
                for scope,indent in [(header,0),(job,4)]:
                    if re.search(r"(?m)^"+" "*indent+r"concurrency:", scope):
                        cfg = concurrency_fields(scope,indent)
                        self.assertNotIn(WRITER_GROUP,cfg.get("group", ""),name)
                        self.assertEqual(cfg.get("cancel-in-progress"),"false",name)
                        self.assertEqual(cfg.get("queue"),"max",name)
        self.assertGreaterEqual(callers,4)

    def test_emergency_cancellation_is_not_queued_behind_the_writer_it_must_stop(self):
        text = self.workflows()["operator-console.yml"]
        header,jobs = workflow_jobs(text)
        self.assertEqual(concurrency_fields(header,0)["group"],OPERATOR_ENTRY_GROUP)
        self.assertEqual(concurrency_fields(jobs["operate"],4)["group"],OPERATOR_WRITER_GROUP)
        self.assertIn("inputs.operation == 'EMERGENCY_STOP'",text)
        self.assertIn("gh run cancel",text)
        self.assertRegex(text, r"- name: Upload operator-updated scheduler state\n        if: \$\{\{ inputs.operation == 'CANCEL_QUEUE_ITEM' \}\}")

    def test_read_only_watchdog_remains_outside_mutable_state_mutex(self):
        text = self.workflows()["portfolio-cost-watchdog.yml"]
        self.assertFalse(mutable_artifact_names(text))
        self.assertNotIn(WRITER_GROUP,text)
        self.assertIn("cost_governor.cancel_managed_jobs",text)
        self.assertNotIn("cost_governor.workflow_gate finalize",text)

    def restore_runtime(self, payloads, output, metadata):
        candidates = {"artifacts":[{
            "id":i, "name":"portfolio-runtime-state",
            "created_at":f"2026-09-26T{16+i:02d}:00:00Z",
            "archive_download_url":key,
            "workflow_run":{"id":i,"head_branch":"main","head_sha":str(i)*40},
        } for i,key in enumerate(payloads,1)]}
        def download(key):
            raw=payloads[key]
            validate_runtime_artifact_bundle(raw,max_archive_bytes=100000,max_member_bytes=50000)
            return raw
        return restore_latest_valid_state(
            candidates,current_run="99",expected_head_branch="main",download=download,
            output=output,member_name="runtime_state.json",expected_state_id="portfolio-runtime-state",
            max_archive_bytes=100000,max_state_bytes=50000,validator=validate_state,metadata_output=metadata)

    def test_two_real_writers_from_one_snapshot_fail_closed_without_losing_existing_state(self):
        initial=bootstrap_state(now="2026-09-25T17:00:00Z")
        first=runtime_bundle(initial_state=initial,repository_id="REPO-001")
        second=runtime_bundle(initial_state=initial,repository_id="REPO-002")
        for payloads in ({"first":first,"second":second},{"second":second,"first":first}):
            with self.subTest(upload_order=list(payloads)), tempfile.TemporaryDirectory() as td:
                out=Path(td)/"runtime_state.json";metadata=Path(td)/"restore.json"
                state_bytes=json.dumps(initial).encode(); proof_bytes=b'{"existing":"preserve"}'
                out.write_bytes(state_bytes);metadata.write_bytes(proof_bytes)
                with self.assertRaisesRegex(InvalidStateArtifact,"conflicting state artifacts at highest sequence"):
                    self.restore_runtime(payloads,out,metadata)
                self.assertEqual(out.read_bytes(),state_bytes)
                self.assertEqual(metadata.read_bytes(),proof_bytes)

    def test_serialized_restore_advance_publish_preserves_both_real_mutations(self):
        initial=bootstrap_state(now="2026-09-25T17:00:00Z")
        first=runtime_bundle(initial_state=initial,repository_id="REPO-001")
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"runtime_state.json";metadata=Path(td)/"restore.json"
            self.restore_runtime({"first":first},out,metadata)
            predecessor=json.loads(out.read_text())
            second=runtime_bundle(initial_state=predecessor,repository_id="REPO-002")
            self.restore_runtime({"first":first,"second":second},out,metadata)
            final=json.loads(out.read_text())
            self.assertEqual(final["sequence"],initial["sequence"]+2)
            self.assertEqual(len(final["recent_cycles"]),len(initial["recent_cycles"])+2)
            self.assertEqual(final["recent_cycles"][-2],predecessor["recent_cycles"][-1])
            self.assertNotEqual(final["recent_cycles"][-1]["cycle_id"],final["recent_cycles"][-2]["cycle_id"])
            self.assertEqual(json.loads(metadata.read_text())["source_sequence"],final["sequence"])


if __name__=="__main__":unittest.main()
