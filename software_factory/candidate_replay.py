"""Replay the exported patch in a fresh Git repository and prepare review input.

This is a technical reproduction, NOT independent approval. No network, remote
ref update, PR, merge or deployment is performed. Production CLI tests use only
DockerRunner; runner injection is for trusted unit fixtures.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable

from software_factory.candidate_worker import (
    BuildError, MAX_PATCH_BYTES, _measure, _write_tree, digest, load_snapshot,
    object_hash, require, safe_path, validate_task,
)
from software_factory.software_factory import (
    SoftwareFactory, SoftwareFactoryError, make_commit_action, policy,
)

BUILD_FIELDS = {
    "schema_version", "task_id", "task_hash", "repository", "base_sha", "status",
    "source_tree_hash", "candidate_tree_hash", "changed_paths", "patch_sha256",
    "tests", "builder_driver", "model_calls", "model_cost_usd",
    "independent_verification", "production_changed", "merge_authorized",
    "deployment_authorized", "receipt_hash",
}
STAGES = ("baseline", "candidate_regression", "candidate_suite")
MAX_LOG = 1048576


def read_bytes(root: Path, name: str, limit: int) -> bytes:
    safe_path(name)
    root = root.resolve(strict=True)
    path = root / name
    require(not path.is_symlink() and path.is_file(), "missing or linked artifact member")
    require(path.resolve().is_relative_to(root), "artifact path escaped root")
    require(path.stat().st_size <= limit, "artifact member too large")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "artifact member too large")
    return raw


def read_json(root: Path, name: str, limit: int = MAX_PATCH_BYTES) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    def constant(value):
        raise BuildError("nonfinite JSON value")
    return json.loads(read_bytes(root, name, limit), object_pairs_hook=pairs,
                      parse_constant=constant)


def tree_hash(files: dict[str, bytes]) -> str:
    return object_hash({p: digest(v) for p, v in sorted(files.items())})


def commands(task: dict) -> tuple[list[str], list[str]]:
    command = ["python", "-m", "unittest", "discover", "-s", "tests", "-p"]
    return (command + [Path(task["test_path"]).name, "-v"],
            command + ["test_*.py", "-v"])


def _check_log(row: dict, raw: bytes, stage: str, task: dict) -> None:
    require(type(row.get("test_count")) is int and row["test_count"] > 0,
            "invalid executed test count")
    require(type(row.get("exit_code")) is int and row.get("timed_out") is False,
            "invalid execution outcome")
    matches = re.findall(rb"\bRan ([1-9][0-9]*) tests? in ", raw)
    require(len(matches) == 1 and int(matches[0]) == row["test_count"],
            "log/test count mismatch")
    require(row.get("log_sha256") == digest(raw), "test log digest mismatch")
    if stage == "baseline":
        require(row["exit_code"] == 1 and task["baseline_failure_marker"].encode() in raw
                and re.search(rb"FAILED \(failures=[1-9][0-9]*\)\s*$", raw),
                "expected baseline assertion failure missing")
    else:
        require(row["exit_code"] == 0 and re.search(rb"\nOK\s*$", raw),
                "candidate test did not pass without skips")


def validate_bundle(task: dict, approved_hash: str, source: dict[str, bytes],
                    artifact_dir: Path) -> tuple[dict, dict[str, bytes], bytes]:
    """Validate bytes against a separately supplied task and pinned source.

    Hashes prove consistency only. This method never supplies review authority.
    """
    validate_task(task, approved_hash)
    receipt = read_json(artifact_dir, "build_receipt.json")
    require(isinstance(receipt, dict) and set(receipt) == BUILD_FIELDS,
            "build receipt fields changed")
    require(receipt["receipt_hash"] == object_hash({k: v for k, v in receipt.items()
                                                   if k != "receipt_hash"}),
            "build receipt digest mismatch")
    for field in ("task_id", "repository", "base_sha"):
        require(receipt[field] == task[field], "build/task identity mismatch")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1,
            "build schema mismatch")
    require(receipt["task_hash"] == approved_hash and receipt["builder_driver"] == task["driver"],
            "build/task approval mismatch")
    require(receipt["status"] == "CANDIDATE_TESTED_AWAITING_INDEPENDENT_REVIEW",
            "unexpected build disposition")
    for field in ("independent_verification", "production_changed", "merge_authorized", "deployment_authorized"):
        require(receipt[field] is False, "artifact cannot grant authority")
    require(type(receipt["model_calls"]) is int and receipt["model_calls"] == 0
            and type(receipt["model_cost_usd"]) in (int, float) and receipt["model_cost_usd"] == 0,
            "deterministic driver cannot claim model usage")
    require(receipt["source_tree_hash"] == tree_hash(source), "source tree mismatch")
    expected = dict(source)
    require(task["test_path"] not in source, "regression must not replace existing tests")
    for edit in task["edits"]:
        raw = source.get(edit["path"])
        require(raw is not None and digest(raw) == edit["source_sha256"], "source content drift")
        text = raw.decode("utf-8")
        require(text.count(edit["before"]) == 1, "edit absent or ambiguous")
        expected[edit["path"]] = text.replace(edit["before"], edit["after"], 1).encode()
    expected[task["test_path"]] = task["test_source"].encode()
    changed = sorted(p for p in expected if expected[p] != source.get(p))
    require(receipt["changed_paths"] == changed and receipt["candidate_tree_hash"] == tree_hash(expected),
            "candidate tree/paths mismatch")
    supplied = read_json(artifact_dir, "candidate_files.json", 1048576)
    require(isinstance(supplied, dict) and set(supplied) == set(changed)
            and all(isinstance(supplied[p], str) and supplied[p].encode() == expected[p] for p in changed),
            "candidate file bytes do not match approved repair")
    patch = read_bytes(artifact_dir, "candidate.patch", MAX_PATCH_BYTES)
    require(bool(patch) and digest(patch) == receipt["patch_sha256"], "patch digest mismatch")
    rows = receipt["tests"]
    require(isinstance(rows, list) and len(rows) == 3, "three measured test stages required")
    acceptance, suite = commands(task)
    for row, stage, argv in zip(rows, STAGES, (acceptance, acceptance, suite)):
        require(isinstance(row, dict) and row.get("stage") == stage and row.get("command") == argv,
                "test stage/command mismatch")
        _check_log(row, read_bytes(artifact_dir, stage + ".log", MAX_LOG), stage, task)
    require(rows[0]["test_count"] == rows[1]["test_count"] <= rows[2]["test_count"],
            "regression/suite count inconsistency")
    return receipt, expected, patch


class GitSandbox:
    """Fresh bare Git object database; candidate code is never executed here."""
    def __init__(self, root: Path, checkout: Path, base: str):
        self.root = root
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(root.parent),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file",
                    "GIT_NO_REPLACE_OBJECTS": "1"}
        result = subprocess.run(["git", "init", "--bare", str(root)], env=self.env,
                                capture_output=True, timeout=15)
        require(result.returncode == 0, "isolated Git initialization failed")
        self.run("fetch", "--no-tags", "--no-write-fetch-head", str(checkout.resolve()), base)
        require(self.run("rev-parse", base + "^{commit}").decode().strip() == base, "base revision mismatch")
        self.run("read-tree", base)

    def run(self, *args: str, stdin: bytes | None = None, env: dict | None = None) -> bytes:
        result = subprocess.run(["git", "--git-dir=" + str(self.root), "-c", "core.hooksPath=" + os.devnull,
                                 *args], env={**self.env, **(env or {})}, input=stdin,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        require(result.returncode == 0, "isolated git operation failed: " + args[0])
        return result.stdout

    def files(self, tree: str) -> tuple[dict[str, bytes], dict[str, str]]:
        rows = self.run("ls-tree", "-rz", tree).split(b"\0")
        entries = []
        for raw in filter(None, rows):
            metadata, path = raw.split(b"\t", 1)
            mode, kind, sha = metadata.decode().split()
            name = safe_path(path.decode(), allow_repository_metadata=True)
            require(mode in {"100644", "100755"} and kind == "blob", "special Git file rejected")
            entries.append((name, mode, sha))
        require(len(entries) == len({row[0] for row in entries}), "duplicate Git path")
        raw = self.run("cat-file", "--batch", stdin="".join(sha + "\n" for _, _, sha in entries).encode())
        pos, files, modes = 0, {}, {}
        for name, mode, sha in entries:
            end = raw.index(b"\n", pos)
            found, kind, size = raw[pos:end].decode().split()
            require(found == sha and kind == "blob", "Git blob identity mismatch")
            start = end + 1; finish = start + int(size)
            require(raw[finish:finish + 1] == b"\n", "truncated Git blob")
            files[name] = raw[start:finish]; modes[name] = mode; pos = finish + 1
        require(pos == len(raw), "unexpected Git object payload")
        return files, modes


def replay_candidate(task: dict, *, approved_hash: str, checkout: Path,
                     artifact_dir: Path, runner: Callable, output_dir: Path) -> dict:
    """Verify actual patch -> clean red/green runs -> real local commit -> VERIFYING.

    The factory handoff is a local snapshot, not a production ledger write.
    A separately authorized submitter/reviewer must still bind provider commit
    identity, independence and policy before remote submission or PR creation.
    """
    require(not output_dir.exists(), "replay output exists; refusing overwrite")
    validate_task(task, approved_hash)
    source = load_snapshot(checkout, task)
    build, expected, patch_bytes = validate_bundle(task, approved_hash, source, artifact_dir)
    repositories = [p for p in policy()["repository_policies"] if p["repository_full_name"] == task["repository"]]
    require(len(repositories) == 1 and repositories[0]["candidate_modify_enabled"] is True,
            "factory repository not onboarded")
    repository = repositories[0]
    with tempfile.TemporaryDirectory(prefix="brain-replay-") as name:
        temp = Path(name); temp.chmod(0o755)
        git = GitSandbox(temp / "objects.git", checkout, task["base_sha"])
        original, modes = git.files(task["base_sha"])
        require(original == source, "Git source differs from pinned snapshot")
        git.run("apply", "--cached", "--check", "--whitespace=nowarn", "-", stdin=patch_bytes)
        git.run("apply", "--cached", "--whitespace=nowarn", "-", stdin=patch_bytes)
        tree = git.run("write-tree").decode().strip()
        actual, actual_modes = git.files(tree)
        require(actual == expected, "applied patch differs from approved candidate")
        require(actual_modes == {**modes, task["test_path"]: "100644"}, "patch changed Git file modes")
        # The ordinary factory packet has no mode field and writes 100644 only.
        require(all(actual_modes[p] == "100644" for p in build["changed_paths"]),
                "factory packet cannot preserve an executable file mode")
        sf = SoftwareFactory(temp / "factory.sqlite3")
        try:
            sf.enqueue(work_id=task["task_id"], project_id=task["project_id"],
                       repository_id=repository["repository_id"], base_sha=task["base_sha"],
                       title=task["task_id"], issue_ref=task["source_ref"], verifier_agent_id="AGT-AUDITOR",
                       provenance_refs=["build-task:" + approved_hash, "builder-receipt:" + build["receipt_hash"]])
            branch_action = sf.claim(task["task_id"], "AGT-ENGINEER")
            running = sf.get(task["task_id"])
            files = [{"path": p, "content_b64": base64.b64encode(actual[p]).decode(),
                      "content_sha256": digest(actual[p])} for p in build["changed_paths"]]
            commit_action = make_commit_action(running, files, "Candidate repair: " + task["task_id"])
            baseline = {**source, task["test_path"]: task["test_source"].encode()}
            before, after = temp / "baseline", temp / "candidate"
            _write_tree(before, baseline); _write_tree(after, actual)
            rows, logs = [], {}
            acceptance, suite = commands(task)
            for stage, root, argv in zip(STAGES, (before, after, after), (acceptance, acceptance, suite)):
                row, raw = _measure(runner, root, argv, task["timeout_seconds"], stage)
                _check_log(row, raw, stage, task)
                row["receipt_hash"] = object_hash(row)
                rows.append(row); logs[stage] = raw
            require([r["test_count"] for r in rows] == [r["test_count"] for r in build["tests"]],
                    "replay test discovery differs from builder")
            for root, frozen in ((before, baseline), (after, actual)):
                paths = list(root.rglob("*"))
                require(not any(p.is_symlink() for p in paths), "replay created symlink")
                observed = {p.relative_to(root).as_posix(): p.read_bytes() for p in paths if p.is_file()}
                require(observed == frozen, "replay mutated source or tests")
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            identity = {"GIT_AUTHOR_NAME": "Portfolio Brain Candidate", "GIT_AUTHOR_EMAIL": "candidate@portfolio-brain.invalid",
                        "GIT_COMMITTER_NAME": "Portfolio Brain Candidate", "GIT_COMMITTER_EMAIL": "candidate@portfolio-brain.invalid",
                        "GIT_AUTHOR_DATE": timestamp, "GIT_COMMITTER_DATE": timestamp}
            commit = git.run("commit-tree", tree, "-p", task["base_sha"],
                             stdin=(commit_action["commit_message"] + "\n").encode(), env=identity).decode().strip()
            commit_body = git.run("cat-file", "commit", commit)
            require(commit_body.startswith(("tree " + tree + "\nparent " + task["base_sha"] + "\n").encode()),
                    "candidate commit is not bound to tested tree and parent")
            sf.record_candidate_commit(task["task_id"], "AGT-ENGINEER", commit_sha=commit,
                                       changed_paths=build["changed_paths"],
                                       test_commands=list(dict.fromkeys(" ".join(r["command"]) for r in rows)),
                                       test_receipt_hashes=[r["receipt_hash"] for r in rows], diff_hash=build["patch_sha256"])
            require(sf.event_chain_valid(), "factory event chain failed")
            work = sf.get(task["task_id"])
            require(work["state"] == "VERIFYING" and work["verification_id"] is None
                    and work["pr_number"] is None, "handoff unexpectedly granted review or PR authority")
            try:
                sf.pr_action(task["task_id"])
            except SoftwareFactoryError:
                pass
            else:
                raise BuildError("factory unexpectedly allowed PR without independent approval")
            git.run("update-ref", "refs/heads/" + work["branch_name"], commit)
            git.run("symbolic-ref", "HEAD", "refs/heads/" + work["branch_name"])
            # Retain source ancestry; an incomplete shallow bundle is not deliverable.
            bundle = temp / "candidate.bundle"
            git.run("bundle", "create", str(bundle), "HEAD", "refs/heads/" + work["branch_name"])
            require(bundle.stat().st_size <= 20 * 1024 * 1024, "candidate bundle too large")
            restored = temp / "bundle-restored.git"
            imported = subprocess.run(["git", "clone", "--bare", str(bundle), str(restored)],
                                      env=git.env, capture_output=True, timeout=20)
            require(imported.returncode == 0, "candidate bundle failed clean import")
            identity_check = subprocess.run(
                ["git", "--git-dir=" + str(restored), "rev-parse", "HEAD", "HEAD^{tree}", "HEAD^"],
                env=git.env, capture_output=True, timeout=10)
            require(identity_check.returncode == 0 and identity_check.stdout.decode().splitlines()
                    == [commit, tree, task["base_sha"]], "imported candidate identity mismatch")
            receipt = {"schema_version": 1, "status": "REPLAY_PASSED_AWAITING_INDEPENDENT_REVIEW",
                       "task_id": task["task_id"], "task_hash": approved_hash,
                       "repository": task["repository"], "base_sha": task["base_sha"],
                       "builder_receipt_hash": build["receipt_hash"], "patch_sha256": build["patch_sha256"],
                       "candidate_commit_sha": commit, "candidate_git_tree_sha": tree,
                       "candidate_tree_hash": tree_hash(actual), "changed_paths": build["changed_paths"],
                       "replay_tests": rows, "factory_work_hash": object_hash(work),
                       "branch_packet_hash": branch_action["action_hash"],
                       "commit_packet_hash": commit_action["action_hash"],
                       "candidate_bundle_sha256": digest(bundle.read_bytes()), "bundle_import_verified": True,
                       "independent_verification": False, "remote_submission_performed": False,
                       "production_changed": False, "delivered_improvements": 0,
                       "model_calls": 0, "model_cost_usd": 0,
                       "merge_authorized": False, "deployment_authorized": False}
            receipt["receipt_hash"] = object_hash(receipt)
            output_dir.mkdir(parents=True)
            for name, value in (("replay_receipt.json", receipt), ("factory_work.json", work),
                                ("factory_branch_action.json", branch_action), ("factory_commit_action.json", commit_action),
                                ("candidate_files.json", {p: actual[p].decode() for p in build["changed_paths"]})):
                (output_dir / name).write_text(json.dumps(value, indent=2) + "\n")
            (output_dir / "candidate.patch").write_bytes(patch_bytes)
            (output_dir / "candidate_commit.txt").write_bytes(commit_body)
            (output_dir / "candidate.bundle").write_bytes(bundle.read_bytes())
            for stage, raw in logs.items():
                (output_dir / (stage + ".log")).write_bytes(raw)
            return receipt
        finally:
            sf.close()
