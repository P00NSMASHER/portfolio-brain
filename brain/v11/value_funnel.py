"""Evidence-linked discovery -> review -> release -> live-outcome funnel.

Never infer review, production integration, business value or revenue from a
research candidate, PR description, successful CI, or this ledger's own text.
All joins require pinned source hashes and original provider verification.
"""
from __future__ import annotations

import re

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class FunnelError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise FunnelError(code)


def summarize(knowledge, links, merged_prs, downstream):
    need(type(knowledge) is dict and type(knowledge.get("sources")) is list
         and len(knowledge["sources"]) <= 200
         and type(links) is dict and set(links) == {"schema_version", "links"}
         and links["schema_version"] == 1 and type(links["links"]) is list
         and len(links["links"]) <= 20
         and type(merged_prs) is list and type(downstream) is dict
         and type(downstream.get("results")) is list,
         "FUNNEL_INPUT_SCHEMA")
    sources = {}
    for entry in knowledge["sources"]:
        need(type(entry) is dict
             and type(entry.get("code_sha256")) is str
             and DIGEST.fullmatch(entry["code_sha256"])
             and type(entry.get("source_ref")) is str
             and entry["source_ref"].startswith("https://github.com/")
             and type(entry.get("head_sha")) is str
             and SHA.fullmatch(entry["head_sha"]),
             "FUNNEL_DISCOVERY_PROVENANCE_INVALID")
        key = entry["code_sha256"]
        need(key not in sources, "FUNNEL_DUPLICATE_SOURCE")
        sources[key] = entry
    merged = {}
    for row in merged_prs:
        need(type(row) is dict, "FUNNEL_MERGE_ROW_INVALID")
        if type(row.get("number")) is int:
            merged[row["number"]] = row
    live = {}
    for row in downstream["results"]:
        need(type(row) is dict, "FUNNEL_LIVE_ROW_INVALID")
        key = (row.get("repository"), row.get("pr_number"))
        need(key not in live, "FUNNEL_DUPLICATE_LIVE_TARGET")
        live[key] = row
    linked, protected, delivered, released = [], [], [], []
    seen = set()
    for entry in links["links"]:
        need(type(entry) is dict
             and set(entry) == {"source_code_sha256", "pr_number", "candidate_head_sha"}
             and type(entry["source_code_sha256"]) is str
             and entry["source_code_sha256"] in sources
             and type(entry["pr_number"]) is int and entry["pr_number"] > 0
             and type(entry["candidate_head_sha"]) is str
             and SHA.fullmatch(entry["candidate_head_sha"]),
             "FUNNEL_LINK_UNTRUSTED")
        key = entry["source_code_sha256"]
        need(key not in seen, "FUNNEL_DUPLICATE_LINK")
        seen.add(key)
        linked.append(entry)
        match = merged.get(entry["pr_number"])
        if (match is not None
                and match.get("head_sha") == entry["candidate_head_sha"]
                and match.get("verification") == "VERIFIED_BOTH_APPS"
                and type(match.get("merged_sha")) is str
                and SHA.fullmatch(match["merged_sha"])):
            protected.append(entry)
            released.append({"source_code_sha256": key,
                             "pr_number": entry["pr_number"],
                             "merge_sha": match["merged_sha"]})
            outcome = live.get(("P00NSMASHER/portfolio-brain", entry["pr_number"]))
            if (outcome is not None
                    and outcome.get("status") == "VERIFIED_REAL_WORLD_REPAIR"
                    and outcome.get("candidate_head_sha") == entry["candidate_head_sha"]
                    and outcome.get("merge_main_sha") == match["merged_sha"]):
                delivered.append(entry)
    return {
        "schema_version": 1,
        "source": "PROTECTED_SOURCE_MANIFEST_AND_ORIGINAL_PROVIDER_SAMPLE",
        "discovered_source_revisions": len(sources),
        "operator_linked_review_candidates": len(linked),
        # The review stage needs separately independently verified review
        # evidence; a link written by an operator cannot certify itself.
        "independently_verified_reviews": None,
        "source_linked_protected_merges": len(protected),
        "source_linked_live_behavior_repairs": len(delivered),
        "provider_sample_scope": "RECENT_30_PRS_AND_ONLY_REGISTERED_TARGETS",
        "verified_customer_revenue": None,
        "verified_saved_engineering_hours": None,
        "unlinked_sources_not_released": len(sources) - len(linked),
        "release_evidence": released,
        "provider_writes": 0,
    }
