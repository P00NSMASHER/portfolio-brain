"""Narrow, offline admission for bot-authored knowledge-only upgrades."""
import hashlib
import json
import re

REPO = "P00NSMASHER/portfolio-brain"
FILE = "brain/REUSE_KNOWLEDGE.json"
BRANCH = re.compile(r"factory/auto-repair-v2-knowledge-([0-9a-f]{16})")
SHA = re.compile(r"[0-9a-f]{40}")
HEX = re.compile(r"[0-9a-f]{64}")
SCOPE = "STRUCTURAL_REUSE_KNOWLEDGE_NOT_EXECUTED_OR_REVENUE_VERIFIED"


class BotAdmissionError(ValueError):
    pass


def req(predicate, code):
    if not predicate:
        raise BotAdmissionError(code)


def _unique(pairs):
    doc = {}
    for key, value in pairs:
        req(key not in doc, "DUPLICATE_JSON_KEY")
        doc[key] = value
    return doc


def inspect(pr, main, comparison, candidate_bytes, *, number, head_sha):
    req(type(number) is int and 0 < number < 1000000000
        and type(head_sha) is str and SHA.fullmatch(head_sha),
        "UNTRUSTED_REQUEST_IDENTITY")
    req(type(pr) is dict and pr.get("number") == number
        and pr.get("state") == "open" and pr.get("merged") is False
        and pr.get("draft") is False
        and (pr.get("user") or {}).get("login") == "github-actions[bot]",
        "NOT_AN_OPEN_BOT_ONLY_PROPOSAL")
    head, base = pr.get("head") or {}, pr.get("base") or {}
    branch = head.get("ref")
    ref = BRANCH.fullmatch(branch) if type(branch) is str else None
    req(ref is not None and head.get("sha") == head_sha
        and (head.get("repo") or {}).get("full_name") == REPO
        and (base.get("repo") or {}).get("full_name") == REPO
        and base.get("ref") == "main", "WRONG_BOT_BRANCH_OR_TARGET")
    main_sha = (main.get("commit") or {}).get("sha") if type(main) is dict else None
    req(type(main_sha) is str and SHA.fullmatch(main_sha),
        "MAIN_UNVERIFIED")
    files = comparison.get("files") if type(comparison) is dict else None
    req(comparison.get("merge_base_commit", {}).get("sha") == main_sha
        and type(files) is list and len(files) == 1
        and files[0].get("filename") == FILE
        and files[0].get("status") == "modified",
        "PATCH_NOT_EXCLUSIVELY_KNOWLEDGE_DATA_OR_STALE")
    req(type(candidate_bytes) is bytes and 50 <= len(candidate_bytes) <= 120000,
        "KNOWLEDGE_BYTES_BOUNDED")
    try:
        data = json.loads(candidate_bytes.decode("utf-8"),
                          object_pairs_hook=_unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise BotAdmissionError("KNOWLEDGE_JSON_INVALID") from exc
    req(type(data) is dict and set(data) == {
        "schema_version", "scope", "sources", "fingerprint"
    } and data["schema_version"] == 2 and data["scope"] == SCOPE
        and type(data["sources"]) is list and
        3 <= len(data["sources"]) <= 12, "KNOWLEDGE_SCHEMA_INVALID")
    for row in data["sources"]:
        req(type(row) is dict
            and set(row) == {"key", "repository", "head_sha", "path", "blob_sha",
                             "code_sha256", "test_paths", "license", "source_ref",
                             "target", "matched_terms"}
            and type(row["repository"]) is str
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}", row["repository"])
            and type(row["head_sha"]) is str and SHA.fullmatch(row["head_sha"])
            and type(row["blob_sha"]) is str and SHA.fullmatch(row["blob_sha"])
            and type(row["code_sha256"]) is str and HEX.fullmatch(row["code_sha256"])
            and type(row["path"]) is str and
            re.fullmatch(r"[A-Za-z0-9._/-]{1,180}", row["path"])
            and ".." not in row["path"].split("/")
            and row["source_ref"] ==
                f'https://github.com/{row["repository"]}/blob/{row["head_sha"]}/{row["path"]}'
            and type(row["test_paths"]) is list and len(row["test_paths"]) > 0
            and type(row["matched_terms"]) is list and len(row["matched_terms"]) >= 2,
            "UNBOUNDED_KNOWLEDGE_SOURCE")
    fingerprint = hashlib.sha256(json.dumps(
        data["sources"], sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()
    matches = re.findall(r"(?m)^AUTO_REPAIR_FINGERPRINT: ([0-9a-f]{64})$",
                         pr.get("body") or "")
    req(data["fingerprint"] == fingerprint
        and matches == [fingerprint] and ref.group(1) == fingerprint[:16],
        "BOT_BRANCH_AND_SOURCE_FINGERPRINT_MISMATCH")
    return {"status": "EXACT_BOT_DATA_ONLY_ADMITTED",
            "pr_number": number, "head_sha": head_sha,
            "main_sha": main_sha, "fingerprint": fingerprint,
            "separate_independent_review_required": True,
            "released": False}


def foundation_green(checks, sha):
    req(type(checks) is dict and type(checks.get("total_count")) is int
        and 0 <= checks["total_count"] <= 100
        and type(checks.get("check_runs")) is list
        and len(checks["check_runs"]) == checks["total_count"],
        "INCOMPLETE_FOUNDATION_CHECK_PAGE")
    req(any(type(x) is dict and x.get("name") == "validate"
            and x.get("head_sha") == sha
            and (x.get("app") or {}).get("id") == 15368
            and x.get("status") == "completed"
            and x.get("conclusion") == "success"
            for x in checks["check_runs"]),
        "EXACT_HEAD_FOUNDATION_NOT_GREEN")
    return True
