"""Deterministic code repair for safe, source-bound read-only CI defects.

Never executes provider content, talks to GitHub, writes main, deploys,
spends, creates credentials, contacts third parties or self-approves QA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from brain.core import BrainError, require

SHA = re.compile(r"[0-9a-f]{40}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
PATH = re.compile(r"\.github/workflows/[a-z0-9-]*(?:test|tests|ci|qa)[a-z0-9-]*\.ya?ml\Z")
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
NODE = "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
REPOSITORIES = frozenset({
    "P00NSMASHER/github-value-hunt-ledger",
    "P00NSMASHER/x402-product-factory",
    "P00NSMASHER/permitplate-nyc",
})
MAX_BYTES = 24000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source(data, *, repository, path):
    require(type(data) is bytes and 32 <= len(data) <= MAX_BYTES
            and b"\0" not in data and b"\r" not in data,
            "AUTOFIX_SOURCE_SIZE_OR_ENCODING_UNSAFE")
    try:
        source = data.decode("utf-8")
    except UnicodeError as exc:
        raise BrainError("AUTOFIX_SOURCE_NOT_UTF8") from exc
    require(source.startswith("name: ")
            and len(re.findall(r"(?m)^on:\s*$", source)) == 1
            and re.search(r"(?m)^  pull_request:\s*$", source)
            and (re.search(r"(?m)^permissions: \{\}\s*$", source) or
                 re.search(r"(?m)^permissions:\s*\n  contents: read\s*$", source)),
            "AUTOFIX_NOT_READONLY_PULL_REQUEST_TEST")
    banned = (
        "schedule:", "workflow_dispatch:", "repository_dispatch:",
        "pull_request_target:", "workflow_call:", "secrets.",
        "contents: write", "pull-requests: write", "actions: write",
        "id-token: write", "packages: write", "git push", "curl ",
        "deploy", "publish", "permissions: write-all",
    )
    # A reviewed PermitPlate test uses the word "deployment" only in a
    # non-executable display label. No other deploy/publish text is exempt.
    scanned = source
    harmless_title = "      - name: Verify public deployment boundary\n"
    if (repository == "P00NSMASHER/permitplate-nyc"
            and path == ".github/workflows/permitplate-tests.yml"
            and source.count(harmless_title) == 1):
        scanned = source.replace(
            harmless_title, "      - name: Verify public boundary\n", 1)
    require(not any(fragment in scanned.lower() for fragment in banned)
            and source.count("actions/checkout@") == 1
            and "persist-credentials:" not in source,
            "AUTOFIX_PRIVILEGED_OR_COMPLEX_SOURCE_REFUSED")
    return source


def _change(source: str):
    lines = source.splitlines(keepends=True)
    checkout = [i for i, line in enumerate(lines)
                if re.fullmatch(r" {4,10}- uses: actions/checkout@v4\n", line)]
    require(len(checkout) == 1, "AUTOFIX_CHECKOUT_V4_NOT_UNAMBIGUOUS")
    i = checkout[0]
    width = len(lines[i]) - len(lines[i].lstrip(" "))
    require(i + 1 < len(lines)
            and not re.match(r"^ {" + str(width + 2) + r",}with:", lines[i + 1]),
            "AUTOFIX_CUSTOM_CHECKOUT_OPTIONS_REFUSED")
    lines[i] = " " * width + "- uses: " + CHECKOUT + "\n"
    lines.insert(i + 1, " " * (width + 2) + "with:\n")
    lines.insert(i + 2, " " * (width + 4) + "persist-credentials: false\n")
    steps = ["PIN_CHECKOUT_ACTION", "DENY_PERSISTED_CREDENTIALS"]
    nodes = [i for i, line in enumerate(lines)
             if re.fullmatch(r" {4,10}- uses: actions/setup-node@v4\n", line)]
    require(len(nodes) <= 1, "AUTOFIX_NODE_ACTION_AMBIGUOUS")
    if nodes:
        lines[nodes[0]] = lines[nodes[0]].replace("actions/setup-node@v4", NODE)
        steps.append("PIN_SETUP_NODE_ACTION")
    changed = "".join(lines)
    require(changed != source and changed.count(CHECKOUT) == 1
            and changed.count("persist-credentials: false") == 1
            and "actions/checkout@v4" not in changed,
            "AUTOFIX_DID_NOT_CLOSE_ORIGINAL_DEFECT")
    return changed, steps


def _test(path, ident, pin_node):
    require(type(path) is str and PATH.fullmatch(path),
            "AUTOFIX_TEST_TARGET_INVALID")
    test_path = "tests/test_readonly_checkout_" + ident[:16] + ".py"
    node = (
        "        self.assertIn(" + repr(NODE) + ", contents)\n"
        "        self.assertNotIn('actions/setup-node@v4', contents)\n"
        if pin_node else ""
    )
    code = (
        '"""Automatically generated original CI security regression."""\n'
        'from pathlib import Path\nimport unittest\n\n'
        'ROOT = Path(__file__).resolve().parents[1]\n'
        f'WORKFLOW = {tuple(path.split("/"))!r}\n\n'
        'class ReadOnlyCheckoutRegression(unittest.TestCase):\n'
        '    def test_pinned_checkout_has_no_credentials_or_writer_token(self):\n'
        '        contents = ROOT.joinpath(*WORKFLOW).read_text(encoding="utf-8")\n'
        f'        self.assertIn({CHECKOUT!r}, contents)\n'
        '        self.assertIn("persist-credentials: false", contents)\n'
        '        self.assertNotIn("actions/checkout@v4", contents)\n'
        '        self.assertNotIn("contents: write", contents)\n'
        + node +
        '\nif __name__ == "__main__":\n    unittest.main()\n'
    )
    return test_path, code


def generate(request, original: bytes):
    fields = {
        "schema_version", "repository", "source_head_sha", "path",
        "original_sha256", "repair_kind", "independent_gate_required",
    }
    require(type(request) is dict and set(request) == fields
            and request["schema_version"] == 1
            and request["repository"] in REPOSITORIES
            and type(request["source_head_sha"]) is str
            and SHA.fullmatch(request["source_head_sha"])
            and type(request["path"]) is str and PATH.fullmatch(request["path"])
            and type(request["original_sha256"]) is str
            and HASH.fullmatch(request["original_sha256"])
            and request["repair_kind"] == "READONLY_CI_CHECKOUT_HARDENING"
            and request["independent_gate_required"] is True,
            "AUTOFIX_REQUEST_SCOPE_REFUSED")
    require(sha(original) == request["original_sha256"],
            "AUTOFIX_EXACT_SOURCE_HASH_MISMATCH")
    source = _source(original, repository=request["repository"], path=request["path"])
    changed, steps = _change(source)
    ident = sha((request["repository"] + "|" + request["source_head_sha"]
                 + "|" + request["path"] + "|" + request["original_sha256"]
                ).encode())
    test_path, test_code = _test(request["path"], ident,
                                 "PIN_SETUP_NODE_ACTION" in steps)
    return {
        "schema_version": 1, "status": "REVIEWED_REPAIR_AND_REGRESSION_READY",
        "repository": request["repository"], "source_head_sha": request["source_head_sha"],
        "source_path": request["path"],
        "original_sha256": request["original_sha256"],
        "changed_sha256": sha(changed.encode()),
        "changed_content": changed, "test_path": test_path,
        "test_content": test_code, "test_sha256": sha(test_code.encode()),
        "steps": steps, "original_defect_verified": True,
        "corrected_defect_verified": True, "independent_gate_required": True,
        "merge_authority": False, "deployment_authority": False,
        "payment_or_external_contact_authority": False,
    }


def apply_to_isolated_worktree(root: Path, patch):
    """Only local clean exact-head worktrees. No git add/commit/push or shell."""
    require(isinstance(root, Path) and root.is_dir() and not root.is_symlink()
            and type(patch) is dict
            and patch.get("status") == "REVIEWED_REPAIR_AND_REGRESSION_READY"
            and patch.get("repository") in REPOSITORIES
            and type(patch.get("source_head_sha")) is str
            and SHA.fullmatch(patch["source_head_sha"])
            and type(patch.get("source_path")) is str
            and PATH.fullmatch(patch["source_path"])
            and type(patch.get("test_path")) is str
            and re.fullmatch(r"tests/test_readonly_checkout_[0-9a-f]{16}\.py",
                             patch["test_path"])
            and patch.get("merge_authority") is False
            and patch.get("deployment_authority") is False,
            "AUTOFIX_APPLY_UNTRUSTED_SOURCE")
    require(subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True,
        timeout=5).strip() == patch["source_head_sha"],
        "AUTOFIX_LOCAL_GIT_SOURCE_DRIFT")
    require(not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True,
        timeout=5).strip(), "AUTOFIX_WORKTREE_NOT_CLEAN")
    target, test = root / patch["source_path"], root / patch["test_path"]
    require(target.is_file() and not target.is_symlink()
            and test.parent.is_dir() and not test.parent.is_symlink()
            and not test.exists() and not test.is_symlink()
            and sha(target.read_bytes()) == patch.get("original_sha256")
            and type(patch.get("changed_content")) is str
            and type(patch.get("test_content")) is str
            and sha(patch["changed_content"].encode()) == patch.get("changed_sha256")
            and sha(patch["test_content"].encode()) == patch.get("test_sha256"),
            "AUTOFIX_FILE_DRIFT_OR_PATCH_PAYLOAD_INVALID")
    rebuilt = generate({
        "schema_version": 1, "repository": patch["repository"],
        "source_head_sha": patch["source_head_sha"],
        "path": patch["source_path"],
        "original_sha256": patch["original_sha256"],
        "repair_kind": "READONLY_CI_CHECKOUT_HARDENING",
        "independent_gate_required": True,
    }, target.read_bytes())
    require(rebuilt["changed_content"] == patch["changed_content"]
            and rebuilt["test_content"] == patch["test_content"]
            and rebuilt["test_path"] == patch["test_path"],
            "AUTOFIX_PATCH_RECIPE_REPLAY_FAILURE")
    try:
        fd = os.open(test, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(patch["test_content"])
        target.write_text(patch["changed_content"], encoding="utf-8")
    except OSError as exc:
        if test.exists():
            test.unlink()
        raise BrainError("AUTOFIX_ISOLATED_FILE_WRITE_FAILED") from exc
    return {
        "status": "ISOLATED_CODE_AND_TEST_EDITED_AWAITING_CI",
        "source_head_sha": patch["source_head_sha"],
        "paths": [patch["source_path"], patch["test_path"]],
        "merged": False, "deployed": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate bounded offline repair")
    ap.add_argument("--request", required=True, type=Path)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--apply-root", type=Path)
    args = ap.parse_args(argv)
    from brain.repair_followthrough_cli import _safe_json
    from brain.render import write_report
    require(args.source.is_file() and not args.source.is_symlink()
            and 32 <= args.source.stat().st_size <= MAX_BYTES,
            "AUTOFIX_SOURCE_FILE_UNSAFE")
    result = generate(_safe_json(args.request), args.source.read_bytes())
    if args.apply_root:
        root = args.apply_root.resolve()
        destination = args.output.resolve()
        require(root not in destination.parents and destination != root,
                "AUTOFIX_REPORT_MUST_BE_OUTSIDE_WORKTREE")
        result["isolated_apply_receipt"] = apply_to_isolated_worktree(
            root, result,
        )
    write_report(result, args.output)
    print(json.dumps({"status": result["status"],
                      "paths": [result["source_path"], result["test_path"]],
                      "merge_or_deploy": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
