"""Non-deploying CI proof using a real pinned Brain source defect.

This is an explicitly injected pilot task, not a claim that the live allocator
selected work or that independent review, PR delivery, or rollout occurred.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import traceback

from scheduler.autonomous_scheduler import _candidate, _work_packet, load_state, now_iso
from scheduler.engineering_executor import handler_table, repair_handler
from scheduler.work_executor import execute_cycle, write_outputs
from software_factory.candidate_worker import digest, load_snapshot, object_hash, require

BASE = "bb60815ba1ed25c6914752eee03882c6d183e607"
ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCE = r'''import unittest
from software_factory.software_factory import _path_allowed, SoftwareFactoryError

class FactoryPortablePathRegression(unittest.TestCase):
    def test_backslash_traversal_is_rejected(self):
        with self.assertRaises(SoftwareFactoryError, msg="FACTORY_BACKSLASH_TRAVERSAL_REJECTED"):
            _path_allowed(r"src\..\outside.py")

    def test_normal_python_path_is_still_allowed(self):
        self.assertTrue(_path_allowed("src/parser.py"))
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output-dir", default="candidate-worker-proof")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    source_identity = {"base_sha": BASE, "repository": "P00NSMASHER/portfolio-brain"}
    source = load_snapshot(ROOT, source_identity)
    path = "software_factory/software_factory.py"
    before = 'req(isinstance(path,str) and path and not path.startswith("/") and ".." not in Path(path).parts,"invalid candidate path")'
    after = r'req(isinstance(path,str) and path and "\\" not in path and ":" not in path and "\x00" not in path and not path.startswith("/") and ".." not in Path(path).parts,"invalid candidate path")'
    task = {"schema_version": 1, "driver": "exact-replacement-v1",
            "task_id": "BUILD-CI-PORTABLE-FACTORY-PATH", "source_ref": "RPR-CI-PORTABLE-FACTORY-PATH",
            "project_id": "PRJ-000", **source_identity, "timeout_seconds": 45,
            "test_path": "tests/test_candidate_portable_path_regression.py", "test_source": TEST_SOURCE,
            "baseline_failure_marker": "FACTORY_BACKSLASH_TRAVERSAL_REJECTED",
            "edits": [{"path": path, "source_sha256": digest(source[path]), "before": before, "after": after}]}
    task_hash = object_hash(task)
    configuration = {"tasks": [{"source_ref": task["source_ref"], "task_hash": task_hash, "task": task}],
                     "checkout": ROOT, "image_id": args.image_id,
                     "output_root": output / "candidate_builds"}
    at = now_iso()
    candidate = _candidate("REPAIR", task["source_ref"], ["PRJ-000"], "AGT-ENGINEER",
                           "ISOLATED_IMPLEMENTATION", "MODIFY", "LOW",
                           reason="Controlled CI pilot of a pinned real-source defect; not live allocation.",
                           evidence_refs=["ci-pilot:" + task_hash])
    state = load_state()
    state["work_items"] = [_work_packet(candidate, at)]
    state["completed_fingerprints"] = []
    def diagnostic_handler(work, context):
        try:
            return repair_handler(work, context)
        except Exception:
            traceback.print_exc()
            raise
    handlers = {**handler_table(), "REPAIR": diagnostic_handler}
    updated, receipts, executed, meta = execute_cycle(
        state, runtime_state={}, handlers=handlers, max_items=1,
        context_overrides={"candidate_build_configuration": configuration}, at=at)
    write_outputs(scheduler_state=updated, receipts=receipts, executed_work=executed, meta=meta,
                  output_dir=output, hunter_output_dir=output / "unused-hunter")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    proof = {"schema_version": 1, "proof_kind": "CONTROLLED_REAL_SOURCE_REPAIR_PILOT",
             "worker_head_sha": head, "pilot_base_sha": BASE,
             "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
             "image_id": args.image_id, "task_hash": task_hash,
             "queue_origin": "EXPLICIT_CI_PILOT_NOT_LIVE_ALLOCATION",
             "summary": meta["summary"], "independent_verification": False,
             "production_changed": False, "merged": False, "deployed": False}
    proof["receipt_hash"] = object_hash(proof)
    (output / "pilot_receipt.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))
    require(meta["summary"]["attempted_count"] == 1 and meta["summary"]["completed_count"] == 1
            and meta["summary"]["deferred_count"] == 0, "pilot did not complete candidate build")
    require(receipts[0]["result_kind"] == "CANDIDATE_BUILD_TESTED", "wrong completion kind")
    require(receipts[0]["result"]["delivered_improvements"] == 0, "pilot overclaimed delivery")


if __name__ == "__main__":
    main()
