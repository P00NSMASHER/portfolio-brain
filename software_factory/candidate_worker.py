"""Execute an approved repair recipe and measure it; never merge or deploy.

The first implementation is deliberately deterministic: it applies exact,
preapproved text replacements rather than making unaccounted model calls.
Production test execution requires an already-installed, immutable Docker image.
The runner injection exists for tests; it does not establish independent review.
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from typing import Any, Callable

MAX_SNAPSHOT_BYTES = 20 * 1024 * 1024
MAX_FILES = 2000
MAX_PATCH_BYTES = 262144


class BuildError(ValueError):
    """A build was refused or its evidence was insufficient."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def object_hash(value: Any) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode())


def safe_path(value: str, *, allow_repository_metadata: bool = False) -> str:
    require(isinstance(value, str) and bool(value), "empty path")
    require(not any(c in value for c in "\\:\x00\n\r"), "nonportable path")
    parts = value.split("/")
    require(all(p not in {"", ".", ".."} for p in parts), "unsafe path")
    require(not PurePosixPath(value).is_absolute(), "absolute path")
    require(not any(p.lower() == ".git" or p.lower().startswith(".env")
                    or (p.lower() == ".github" and not allow_repository_metadata)
                    for p in parts), "sensitive path")
    return value


def validate_task(task: dict, approved_hash: str) -> None:
    require(isinstance(task, dict) and object_hash(task) == approved_hash,
            "task does not match separately approved hash")
    require(task.get("schema_version") == 1, "unsupported task schema")
    require(task.get("driver") == "exact-replacement-v1", "unsupported build driver")
    require(re.fullmatch(r"[0-9a-f]{40}", task.get("base_sha", "")) is not None,
            "exact base commit required")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", task.get("repository", ""))
            is not None, "invalid repository")
    for name in ("task_id", "source_ref", "project_id"):
        require(isinstance(task.get(name), str) and 0 < len(task[name]) <= 200,
                "missing task identity")
    require(type(task.get("timeout_seconds")) is int and 1 <= task["timeout_seconds"] <= 45,
            "test timeout must be 1..45 seconds")
    edits = task.get("edits")
    require(isinstance(edits, list) and 1 <= len(edits) <= 8, "bounded edits required")
    paths = []
    for edit in edits:
        require(isinstance(edit, dict), "invalid edit")
        path = safe_path(edit.get("path", ""))
        require(not any(p.lower() in {"tests", "test"} for p in path.split("/"))
                and not Path(path).name.startswith("test_"), "repair cannot edit tests")
        require(isinstance(edit.get("before"), str) and bool(edit["before"]), "empty edit")
        require(isinstance(edit.get("after"), str) and edit["after"] != edit["before"], "no-op edit")
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", edit.get("source_sha256", ""))
                is not None, "source hash required")
        paths.append(path)
    require(len(paths) == len(set(paths)), "duplicate edit path")
    test_path = safe_path(task.get("test_path", ""))
    require(test_path.startswith("tests/test_") and test_path.endswith(".py"),
            "regression must be a new unittest file")
    require(test_path not in paths and isinstance(task.get("test_source"), str)
            and 0 < len(task["test_source"].encode()) <= 65536, "invalid regression source")
    marker = task.get("baseline_failure_marker")
    require(isinstance(marker, str) and 8 <= len(marker) <= 200, "specific failure marker required")
    require(len(json.dumps(task).encode()) <= MAX_PATCH_BYTES, "task too large")


def load_snapshot(checkout: Path, task: dict) -> dict[str, bytes]:
    """Read a pinned commit without checkout, hooks, submodules, or network access."""
    checkout = checkout.resolve(strict=True)
    env = {"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    def git(*args: str) -> bytes:
        result = subprocess.run(["git", "-C", str(checkout), *args], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        require(result.returncode == 0, "git snapshot read failed")
        return result.stdout
    origin = git("remote", "get-url", "origin").decode().strip().removesuffix(".git")
    require(origin in {f"https://github.com/{task['repository']}",
                       f"git@github.com:{task['repository']}"}, "checkout repository mismatch")
    observed = git("rev-parse", "--verify", task["base_sha"] + "^{commit}").decode().strip()
    require(observed == task["base_sha"], "base revision mismatch")
    listing = git("ls-tree", "-r", task["base_sha"])
    require(all(line.split(b" ", 1)[0] in {b"100644", b"100755"} for line in listing.splitlines()),
            "symlinks/submodules/special files are not supported")
    data = git("archive", "--format=tar", task["base_sha"])
    require(len(data) <= MAX_SNAPSHOT_BYTES, "snapshot too large")
    files: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive:
            if member.isdir():
                continue
            require(member.isfile(), "symlinks/submodules/special files are not supported")
            path = safe_path(member.name, allow_repository_metadata=True)
            require(path not in files, "duplicate archive path")
            total += member.size
            require(total <= MAX_SNAPSHOT_BYTES and len(files) < MAX_FILES, "snapshot limit")
            stream = archive.extractfile(member)
            require(stream is not None, "missing archive member")
            files[path] = stream.read()
    return files


class DockerRunner:
    """No network, host credentials, writable source mount, or Docker socket."""
    def __init__(self, image: str):
        require(isinstance(image, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image)
                is not None, "installed immutable Docker image ID required")
        require(shutil.which("docker") is not None, "Docker runtime unavailable")
        self.image = image

    def __call__(self, root: Path, argv: list[str], timeout: int) -> dict:
        name = "brain-build-" + uuid.uuid4().hex
        command = ["docker", "run", "--rm", "--name", name, "--pull=never", "--network=none",
                   "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                   "--pids-limit=64", "--memory=256m", "--cpus=1", "--user=65534:65534",
                   "--tmpfs=/tmp:rw,noexec,nosuid,size=32m", "--workdir=/workspace",
                   "--mount", f"type=bind,src={root.resolve()},dst=/workspace,readonly",
                   "--env=PYTHONDONTWRITEBYTECODE=1", "--env=PYTHONUNBUFFERED=1",
                   "--env=HOME=/tmp", self.image, *argv]
        started = time.monotonic()
        # A bounded log file avoids accumulating arbitrary test output in Python RAM.
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       env={"PATH": os.environ.get("PATH", ""), "HOME": "/tmp"})
            timed_out = False
            oversized = False
            try:
                while process.poll() is None:
                    if time.monotonic() - started > timeout:
                        timed_out = True
                        break
                    if os.fstat(log.fileno()).st_size > 1048576:
                        oversized = True
                        break
                    time.sleep(0.02)
            finally:
                # Also remove a daemon-side container after client timeout/interrupt.
                try:
                    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=10)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
            log.seek(0)
            output = log.read(1048577)
        return {"exit_code": process.returncode, "timed_out": timed_out,
                "output_limit_exceeded": oversized or len(output) > 1048576,
                "output": output, "runtime": "docker", "image_id": self.image}


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    root.mkdir(mode=0o755)
    for path, content in files.items():
        dest = root / safe_path(path, allow_repository_metadata=True)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        dest.write_bytes(content)
        dest.chmod(0o644)


def _measure(runner: Callable, root: Path, argv: list[str], timeout: int, label: str) -> tuple[dict, bytes]:
    result = runner(root, argv, timeout)
    require(isinstance(result, dict) and type(result.get("exit_code")) is int,
            "runner did not return an exit status")
    require(result.get("timed_out") is False, "test timed out")
    require(result.get("output_limit_exceeded") is False, "test output limit exceeded")
    output = result.get("output")
    require(isinstance(output, bytes) and len(output) <= 1048576, "invalid test log")
    text = output.decode("utf-8", errors="replace")
    ran = re.search(r"\bRan ([1-9][0-9]*) tests? in ", text)
    require(ran is not None, "no executed unittest evidence")
    row = {"stage": label, "command": argv, "exit_code": result["exit_code"],
           "test_count": int(ran.group(1)), "log_sha256": digest(output),
           "runtime": result.get("runtime", "injected-test-runner"),
           "image_id": result.get("image_id"), "timed_out": False}
    return row, output


def build_candidate(task: dict, *, approved_hash: str, snapshot: dict[str, bytes],
                    runner: Callable, output_dir: Path) -> dict:
    """Baseline failure -> exact repair -> same regression + suite -> patch artifact.

    The returned evidence is a builder observation, not independent verification.
    The caller must obtain the snapshot from the pinned Git source and must keep
    approved_hash outside the model/task payload. No remote mutation occurs here.
    """
    validate_task(task, approved_hash)
    require(not output_dir.exists(), "output already exists; refusing evidence overwrite")
    require(0 < len(snapshot) <= MAX_FILES and all(isinstance(v, bytes) for v in snapshot.values()),
            "invalid snapshot")
    require(sum(map(len, snapshot.values())) <= MAX_SNAPSHOT_BYTES, "snapshot too large")
    for path in snapshot:
        safe_path(path, allow_repository_metadata=True)
    require(task["test_path"] not in snapshot, "regression path already exists")
    candidate = dict(snapshot)
    for edit in task["edits"]:
        raw = candidate.get(edit["path"])
        require(raw is not None and digest(raw) == edit["source_sha256"], "source content drift")
        old = raw.decode("utf-8")
        require(old.count(edit["before"]) == 1, "edit is absent or ambiguous")
        candidate[edit["path"]] = old.replace(edit["before"], edit["after"], 1).encode()
    regression = task["test_source"].encode()
    baseline = {**snapshot, task["test_path"]: regression}
    candidate[task["test_path"]] = regression
    changed = sorted(p for p in candidate if candidate[p] != snapshot.get(p))
    require(set(changed) == {e["path"] for e in task["edits"]} | {task["test_path"]},
            "candidate changed unexpected paths")
    acceptance = ["python", "-m", "unittest", "discover", "-s", "tests", "-p", Path(task["test_path"]).name, "-v"]
    suite = ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"]
    rows, logs = [], {}
    with tempfile.TemporaryDirectory(prefix="brain-build-") as temp:
        root = Path(temp)
        # Parent traversal must be allowed for Docker's unprivileged UID.
        root.chmod(0o755)
        before, after = root / "baseline", root / "candidate"
        _write_tree(before, baseline)
        _write_tree(after, candidate)
        checks = [("baseline", before, acceptance), ("candidate_regression", after, acceptance),
                  ("candidate_suite", after, suite)]
        for label, tree, command in checks:
            row, output = _measure(runner, tree, command, task["timeout_seconds"], label)
            rows.append(row)
            logs[label] = output
            if label == "baseline":
                require(row["exit_code"] == 1 and task["baseline_failure_marker"].encode() in output
                        and re.search(rb"FAILED \(failures=[1-9][0-9]*\)\s*$", output),
                        "baseline did not reproduce the expected assertion failure")
            else:
                require(row["exit_code"] == 0 and re.search(rb"\nOK\s*$", output),
                        "candidate tests failed")
        # Even an injected trusted test runner cannot silently mutate the candidate.
        for tree, expected in ((before, baseline), (after, candidate)):
            require(not any(p.is_symlink() for p in tree.rglob("*")), "test execution created a symlink")
            actual = {str(p.relative_to(tree)): p.read_bytes() for p in tree.rglob("*") if p.is_file()}
            require(actual == expected, "test execution mutated source or tests")
    patch = "".join("".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        for line in difflib.unified_diff(
        snapshot.get(path, b"").decode().splitlines(keepends=True),
        candidate[path].decode().splitlines(keepends=True),
        fromfile="a/" + path if path in snapshot else "/dev/null", tofile="b/" + path))
        for path in changed).encode()
    require(0 < len(patch) <= MAX_PATCH_BYTES, "invalid patch size")
    receipt = {"schema_version": 1, "task_id": task["task_id"], "task_hash": approved_hash,
               "repository": task["repository"], "base_sha": task["base_sha"],
               "status": "CANDIDATE_TESTED_AWAITING_INDEPENDENT_REVIEW",
               "source_tree_hash": object_hash({p: digest(v) for p, v in sorted(snapshot.items())}),
               "candidate_tree_hash": object_hash({p: digest(v) for p, v in sorted(candidate.items())}),
               "changed_paths": changed, "patch_sha256": digest(patch), "tests": rows,
               "builder_driver": task["driver"], "model_calls": 0, "model_cost_usd": 0,
               "independent_verification": False, "production_changed": False,
               "merge_authorized": False, "deployment_authorized": False}
    receipt["receipt_hash"] = object_hash(receipt)
    output_dir.mkdir(parents=True)
    (output_dir / "candidate.patch").write_bytes(patch)
    (output_dir / "candidate_files.json").write_text(json.dumps(
        {p: candidate[p].decode() for p in changed}, indent=2) + "\n")
    for label, output in logs.items():
        (output_dir / (label + ".log")).write_bytes(output)
    (output_dir / "build_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
