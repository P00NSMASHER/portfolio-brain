"""Offline verification of original RETALLY and App Factory CI evidence bundles.

Input provider metadata is operator supplied; matching its digest is not proof
the provider metadata itself is authentic. All source, buyer and financial
claims remain strictly narrower than successful synthetic technical checks.
No network, credentials, customer records, execution, approval or writes to governed project state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import zipfile

from brain.core import BrainError, require
from brain.render import write_report

SOURCES = {
    "retally": ("P00NSMASHER/github-value-hunt-ledger", "retally-synthetic-review.json"),
    "product-factory": ("P00NSMASHER/x402-product-factory", "factory-buyer-review.json"),
}
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
SLUG = re.compile(r"[a-z][a-z0-9-]{1,75}")
MAX_ZIP = 2_000_000
MAX_UNCOMPRESSED = 300_000
MAX_MANIFEST = 15_000
FAMILIES = ("document-workflow", "quote-to-order", "inventory-control")
CLASSES = ("REVIEW_SCENARIO", "NONMATCH_CONTROL", "KNOWN_BENIGN_SYNTHETIC_TRUTH")


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "EVIDENCE_DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _read_json(raw):
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise BrainError("EVIDENCE_JSON_INVALID") from exc
    require(type(data) is dict, "EVIDENCE_JSON_OBJECT_REQUIRED")
    return data


def _read_private_file(path, max_size):
    require(type(path) is str and Path(path).is_absolute(),
            "EVIDENCE_ABSOLUTE_PATH_REQUIRED")
    target = Path(path)
    require(not target.is_symlink() and target.is_file(),
            "EVIDENCE_FILE_PATH_UNSAFE")
    require(not any(parent.is_symlink() for parent in target.parents),
            "EVIDENCE_PARENT_SYMLINK")
    info = target.stat()
    require(info.st_nlink == 1 and 0 < info.st_size <= max_size,
            "EVIDENCE_FILE_SIZE_OR_ALIAS_INVALID")
    return target.read_bytes()


def _source_metadata(item, project):
    require(type(item) is dict and set(item) == {
        "repository", "head_sha", "run_id", "artifact_id", "artifact_name",
        "zip_sha256", "zip_path",
    }, "EVIDENCE_SOURCE_METADATA_INVALID")
    expected_repo, _ = SOURCES[project]
    require(item["repository"] == expected_repo,
            "EVIDENCE_SOURCE_REPOSITORY_MISMATCH")
    sha = item["head_sha"]
    require(type(sha) is str and HEX40.fullmatch(sha),
            "EVIDENCE_SOURCE_SHA_INVALID")
    require(type(item["run_id"]) is int and 0 < item["run_id"] < 2**63,
            "EVIDENCE_RUN_ID_INVALID")
    require(type(item["artifact_id"]) is int and 0 < item["artifact_id"] < 2**63,
            "EVIDENCE_ARTIFACT_ID_INVALID")
    if project == "retally":
        name = f'retally-review-{sha}-{item["run_id"]}'
    else:
        name = f'buyer-review-agenda-{item["run_id"]}'
    require(item["artifact_name"] == name,
            "EVIDENCE_ARTIFACT_NAME_SOURCE_UNBOUND")
    require(type(item["zip_sha256"]) is str
            and HEX64.fullmatch(item["zip_sha256"]),
            "EVIDENCE_ARCHIVE_SHA_INVALID")
    return item


def _read_exact_artifact(source, project):
    raw = _read_private_file(source["zip_path"], MAX_ZIP)
    require(hashlib.sha256(raw).hexdigest() == source["zip_sha256"],
            "EVIDENCE_ORIGINAL_ZIP_DIGEST_MISMATCH")
    expected = SOURCES[project][1]
    try:
        with zipfile.ZipFile(Path(source["zip_path"])) as archive:
            members = archive.infolist()
            require(len(members) == 1 and members[0].filename == expected,
                    "EVIDENCE_ZIP_MEMBER_ALLOWLIST")
            item = members[0]
            require(not item.is_dir() and not (item.flag_bits & 1)
                    and 0 < item.file_size <= MAX_UNCOMPRESSED
                    and item.compress_size <= MAX_ZIP
                    and not stat.S_ISLNK(item.external_attr >> 16),
                    "EVIDENCE_ZIP_FILE_UNSAFE")
            require(archive.testzip() is None, "EVIDENCE_ZIP_CRC_FAILURE")
            content = archive.read(item)
            require(len(content) == item.file_size,
                    "EVIDENCE_ZIP_FILE_LENGTH_MISMATCH")
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise BrainError("EVIDENCE_ORIGINAL_ZIP_INVALID") from exc
    return _read_json(content)


def _validate_retally(doc):
    require(doc.get("schema_version") == 1
            and doc.get("evidence_kind") == "SYNTHETIC_FIRST_PARTY_COMPARISON"
            and doc.get("production_deployed") is False
            and doc.get("real_customer_outcome") == "NOT_MEASURED"
            and doc.get("human_time_saved") is None
            and doc.get("verified_revenue") is None
            and type(doc.get("validated_recovery_cents")) is int
            and doc["validated_recovery_cents"] == 0,
            "EVIDENCE_RETALLY_FINANCIAL_OR_REAL_WORLD_OVERCLAIM")
    require(type(doc.get("source_base_sha")) is str
            and HEX40.fullmatch(doc["source_base_sha"]),
            "EVIDENCE_RETALLY_BASE_SHA_INVALID")
    codes = doc.get("source_sha256")
    require(type(codes) is dict and set(codes) == {
        "contracts.py", "finding_factory.py", "duplicate_charge_review.py",
        "reviewer_cockpit.py", "brain_review_measurement.py",
    } and all(type(x) is str and HEX64.fullmatch(x) for x in codes.values()),
            "EVIDENCE_RETALLY_SOURCE_CODE_HASHES_INVALID")
    rows = doc.get("cases")
    require(type(rows) is list and len(rows) == 12,
            "EVIDENCE_RETALLY_CASE_COUNT_INVALID")
    counts = {key: {"cases": 0, "baseline_cases_flagged": 0,
                    "candidate_cases_flagged": 0} for key in CLASSES}
    seen = set()
    for row in rows:
        require(type(row) is dict and type(row.get("case_id")) is str
                and SLUG.fullmatch(row["case_id"])
                and row["case_id"] not in seen and
                row.get("truth_class") in counts,
                "EVIDENCE_RETALLY_CASE_IDENTITY_INVALID")
        seen.add(row["case_id"])
        require(all(type(row.get(key)) is str and HEX64.fullmatch(row[key])
                    for key in ("population_hash", "input_hash",
                                "baseline_batch_hash", "candidate_queue_hash")),
                "EVIDENCE_RETALLY_CASE_PROOF_HASH_INVALID")
        before, after = row.get("baseline_reviews"), row.get("candidate_reviews")
        require(type(before) is int and type(after) is int and
                0 <= before <= 50 and 0 <= after <= 50,
                "EVIDENCE_RETALLY_CASE_REVIEW_COUNT_INVALID")
        hashes = row.get("candidate_case_hashes")
        require(type(hashes) is list and len(hashes) == after
                and all(type(h) is str and HEX64.fullmatch(h) for h in hashes),
                "EVIDENCE_RETALLY_CANDIDATE_CASE_HASH_INVALID")
        for key in ("baseline_runtime_ns_single_sample",
                    "candidate_runtime_ns_single_sample"):
            require(type(row.get(key)) is int and row[key] >= 0,
                    "EVIDENCE_RETALLY_RUNTIME_SAMPLE_INVALID")
        tally = counts[row["truth_class"]]
        tally["cases"] += 1
        tally["baseline_cases_flagged"] += int(before > 0)
        tally["candidate_cases_flagged"] += int(after > 0)
    require(doc.get("summary") == counts,
            "EVIDENCE_RETALLY_SUMMARY_NOT_REPLAYED_FROM_CASES")
    # Require a real negative-control group and visible legitimate-review cost.
    require(counts["REVIEW_SCENARIO"]["cases"] == 5
            and counts["NONMATCH_CONTROL"]["cases"] == 5
            and counts["KNOWN_BENIGN_SYNTHETIC_TRUTH"]["cases"] == 2,
            "EVIDENCE_RETALLY_CONTROL_GROUPS_INVALID")
    positive = counts["REVIEW_SCENARIO"]
    benign = counts["KNOWN_BENIGN_SYNTHETIC_TRUTH"]
    negative = counts["NONMATCH_CONTROL"]
    return {
        "status": "DESIGNED_SYNTHETIC_REVIEW_TRADEOFF_REPLAYED",
        "designed_review_cases": positive["cases"],
        "baseline_designed_cases_flagged": positive["baseline_cases_flagged"],
        "candidate_designed_cases_flagged": positive["candidate_cases_flagged"],
        "additional_designed_cases_flagged":
            positive["candidate_cases_flagged"] - positive["baseline_cases_flagged"],
        "known_benign_review_cases": benign["cases"],
        "additional_known_benign_review_burden":
            benign["candidate_cases_flagged"] - benign["baseline_cases_flagged"],
        "nonmatch_cases": negative["cases"],
        "candidate_nonmatch_cases_flagged": negative["candidate_cases_flagged"],
        "ground_truth": "DEVELOPER_LABELED_NONREPRESENTATIVE_SYNTHETIC",
        "real_customer_accuracy": None,
        "reviewer_minutes_saved": None,
        "real_money_recovered": None,
        "recommended_next_step":
            "INDEPENDENT_LABELING_AND_REVIEW_BURDEN_VALIDATION_BEFORE_ADOPTION",
    }


def _validate_factory(doc):
    require(doc.get("kind") == "unified-operator-buyer-evidence-review"
            and doc.get("independentExternalBuyerEvidence") is False
            and doc.get("measuredRealBuyerPain") is None
            and doc.get("realCustomers") is None
            and doc.get("collectedRevenue") is None
            and doc.get("externalMessagesSent") == 0
            and doc.get("paymentsSent") == 0
            and doc.get("publicDeploymentEnabled") is False
            and doc.get("autoApprove") is False
            and doc.get("releaseApproved") is False,
            "EVIDENCE_FACTORY_BUSINESS_OR_RELEASE_OVERCLAIM")
    rows = doc.get("packets")
    require(type(rows) is list and 1 <= len(rows) <= 30
            and type(doc.get("totalReviewPackets")) is int
            and doc["totalReviewPackets"] == len(rows),
            "EVIDENCE_FACTORY_REVIEW_PACKET_COUNT_INVALID")
    tally = {family: 0 for family in FAMILIES}
    unique = set()
    for row in rows:
        require(type(row) is dict and type(row.get("id")) is str
                and SLUG.fullmatch(row["id"]) and row["id"] not in unique
                and row.get("family") in tally
                and type(row.get("sourceDigest")) is str
                and HEX64.fullmatch(row["sourceDigest"]),
                "EVIDENCE_FACTORY_SOURCE_IDENTITY_INVALID")
        unique.add(row["id"])
        urls = row.get("sourceUrls")
        require(type(urls) is list and len(urls) == 2
                and all(type(u) is str and u.startswith("https://")
                        and len(u) <= 500 for u in urls),
                "EVIDENCE_FACTORY_PUBLIC_CONTEXT_UNVERIFIED")
        require(row.get("existingBuyerEvidence") == "NOT_COLLECTED"
                and row.get("confirmedConversations") is None
                and row.get("verifiedWorkflowCompletions") is None
                and row.get("verifiedRevenue") is None
                and row.get("buyerDemandValidated") is False
                and row.get("deploymentApproved") is False
                and row.get("externalContactPermitted") is False
                and row.get("consentRequiredForAnyRealEvaluation") is True,
                "EVIDENCE_FACTORY_UNSUPPORTED_BUYER_OR_AUTHORITY_CLAIM")
        tally[row["family"]] += 1
    require(doc.get("familyCounts") == tally,
            "EVIDENCE_FACTORY_FAMILY_COUNTS_INCONSISTENT")
    return {
        "status": "SOURCE_DIGESTED_BUYER_RESEARCH_AGENDA_VERIFIED",
        "unverified_hypotheses": len(rows),
        "family_counts": tally,
        "verified_buyers": None,
        "buyer_interviews": None,
        "independent_demand": False,
        "collected_revenue": None,
        "recommended_next_step":
            "CONSENTED_EXTERNAL_BUYER_DISCOVERY_BEFORE_MORE_BUILD_VARIANTS",
    }


def verify_original_project_artifacts(manifest):
    require(type(manifest) is dict and set(manifest) == {
        "schema_version", "scope", "sources",
    } and manifest["schema_version"] == 1
            and manifest["scope"] == "EXACT_SOURCE_GITHUB_ARTIFACT_REVIEW"
            and type(manifest["sources"]) is dict
            and set(manifest["sources"]) == set(SOURCES),
            "EVIDENCE_MANIFEST_SCHEMA_INVALID")
    source = {}
    for name in SOURCES:
        row = _source_metadata(manifest["sources"][name], name)
        raw = _read_exact_artifact(row, name)
        outcome = _validate_retally(raw) if name == "retally" else _validate_factory(raw)
        source[name] = {
            "repository": row["repository"],
            "source_head_sha": row["head_sha"],
            "workflow_run_id": row["run_id"],
            "artifact_id": row["artifact_id"],
            "artifact_zip_sha256": row["zip_sha256"],
            "source_workflow_url":
                f'https://github.com/{row["repository"]}/actions/runs/{row["run_id"]}',
            "outcome": outcome,
            "release_approved": False,
            "buyer_value_verified": False,
        }
    return {
        "schema_version": 1,
        "status": "PASS",
        "scope": "SOURCE_HASHED_SYNTHETIC_TECHNICAL_ONLY_NOT_COMMERCIAL_VALUE",
        "projects": source,
        "original_zip_digest_and_crc_verified": True,
        "provider_metadata_authenticity":
            "EXPECTED_DIGESTS_OPERATOR_SUPPLIED_VERIFY_AGAINST_ORIGINAL_PROVIDER",
        "technical_outcomes_verified_against_developer_fixture": True,
        "independently_adjudicated_customer_outcomes": None,
        "verified_revenue": None,
        "authority_to_merge_deploy_or_contact": False,
        "next_priority": (
            "RETALLY_INDEPENDENT_INVOICE_LABELS_AND_REVIEW_COST;"
            "FACTORY_CONSENTED_BUYER_INTERVIEWS"
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline original project artifact checks")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    doc = _read_json(_read_private_file(args.manifest, MAX_MANIFEST))
    result = verify_original_project_artifacts(doc)
    write_report(result, args.output)
    print(json.dumps({
        "status": result["status"],
        "scope": result["scope"],
        "zip_digest_and_crc_verified": True,
        "buyer_outcomes_verified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
