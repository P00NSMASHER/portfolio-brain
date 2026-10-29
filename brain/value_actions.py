"""Reviewable evidence-to-action plans for two owner-priority projects.

Every item is pinned to an actually observed PR and its exact commit. Nothing
here executes third-party code, modifies a downstream repo, contacts a customer,
claims revenue, or authorizes RETALLY formation/production deployment.
"""
from __future__ import annotations

import re

from brain.core import require
from brain.pr_intelligence import FOCUS_REPOSITORIES

SHA = re.compile("[0-9a-f]{40}")

# Explicit, falsifiable project-specific experiments. These *describe* tests
# to run in the target repo; this module never claims to have performed them.
CONTRACTS = {
    "retally": {
        "FIRST_CUSTOMER_CONTROLS": {
            "next_change": "Reduce first-customer review errors without changing the money authority boundary.",
            "measurement": "incorrect_recovery_recommendations_per_100_labeled_invoices",
            "test_plan": [
                "Freeze a source-hashed synthetic invoice/charge fixture with independent labels.",
                "Compare duplicate and fee suggestions against those same labels before and after the candidate.",
                "Rehearse the declared 30-percent contingency only on supported synthetic recovered-fund events; verify no fee on rejected or merely proposed findings.",
                "Independently inspect engagement amendments, operator roles, restricted database scope, and fail-closed hosted financial switches.",
            ],
            "required_gate": "Issue 323 genuine buyer-specific controls, reviewer appointment, restricted runtime access, and later legal identity/contracts/insurance.",
            "proof_artifact": "pinned_fixture_and_negative_fee_replay_receipts",
        },
        "RECOVERY_ACCURACY": {
            "next_change": "Validate cross-shipment invoice-reference and charge-duplication review with zero automatic recovery claims.",
            "measurement": "incorrect_recovery_recommendations_per_100_labeled_invoices",
            "test_plan": [
                "Build labeled distinct-shipment repeats, legitimate same identifiers, changed buyers/carriers/currency and malformed invoice samples.",
                "Compare reference-review false positives and missed duplicates against the existing first-party detector without suppressing negatives.",
                "Verify every new uncertain match is REVIEW only, with independently traceable proof IDs and zero validated/recovered dollars.",
            ],
            "required_gate": "Independent invoice-level judgment and customer consent before using findings in disputes or commercial calculations.",
            "proof_artifact": "source_bound_confusion_matrix_with_false_positives",
        },
        "SECURITY_CONTINUITY": {
            "next_change": "Prove restore and journal replay controls fail closed under adversarial file and signing changes.",
            "measurement": "unblocked_adversarial_restore_paths",
            "test_plan": [
                "Replay source-pinned signed-checkpoint negative suites against copy, swap, rollback, stale witnesses and crash gaps.",
                "Verify original journal continuity and independently credentialed witness checks in isolated disposable test state.",
                "Compare known adversarial outcomes to the previous exact-source baseline without rewriting original evidence.",
            ],
            "required_gate": "Independent restricted-role infrastructure and human restore authority, not just local synthetic CI.",
            "proof_artifact": "source_pinned_restore_negative_controls",
        },
        "MARKETING_EVIDENCE": {
            "next_change": "Measure source-verifiable inbound interest, not impressions or simulated leads.",
            "measurement": "consented_real_buyer_inquiries",
            "test_plan": [
                "Check exact landing-page links, brand identity, inquiry consent and privacy safeguards.",
                "Keep platform engagement and owner-reported replies distinct from qualified actual buyer requests.",
            ],
            "required_gate": "No real inquiry processing or unsolicited contact until legal/privacy and activation conditions are satisfied.",
            "proof_artifact": "source_bound_link_and_consent_checks",
        },
    },
    "product-factory": {
        "IDEA_TO_DEPLOYMENT": {
            "next_change": "Turn high-novelty evidence-backed concepts into source-pinned app builds and private deployment rehearsals.",
            "measurement": "independently_rehearsed_differentiated_app_candidates",
            "test_plan": [
                "Check original source references, dated context, novelty and duplicate mechanics for candidate ideas.",
                "Rebuild accepted packages from exact draft SHA, independently verifying all native desktop/mobile role-separated flows.",
                "Reboot each app twice with private persisted SQLite, hostile Host/Origin, authentication and CSP controls.",
                "Keep fabricated demand, actual buyer commitments and collected revenue explicitly unknown until genuine independent evidence exists.",
            ],
            "required_gate": "Approved hosting/security/privacy review and separately consented buyer validation before any public app or paid service.",
            "proof_artifact": "source_and_native_browser_bound_build_rehearsal_receipts",
        },
        "BUYER_VALIDATION": {
            "next_change": "Separate actual independent buyer evaluations from synthetic pilots and operator-reported demand.",
            "measurement": "buyer_confirmed_pilot_workflow_completions",
            "test_plan": [
                "Document a specific target buyer job, existing substitute and interview disconfirmation question for every selected app.",
                "Verify opt-in pilot activation and committed first outcome without replay inflation or cross-tenant data exposure.",
                "Keep simulated workflows, owner attestations and separately authenticated external buyer evidence in distinct ledgers.",
            ],
            "required_gate": "Buyer consent, privacy review, owner approval and independent external evidence before any revenue or adoption claim.",
            "proof_artifact": "consented_external_pilot_outcome_receipts",
        },
        "DEPLOYMENT_READINESS": {
            "next_change": "Validate package restore, unauthorized-access rejection and private live-like app startup.",
            "measurement": "source_pinned_successful_private_deployment_rehearsals",
            "test_plan": [
                "Audit exact candidate source and package digests across cold start and clean restart.",
                "Exercise native app interfaces on desktop/mobile and deny hostile cross-origin or unauthenticated requests.",
                "Retain crash and failed-run receipts rather than replacing them with simulated green events.",
            ],
            "required_gate": "External public hosting, TLS, credentials, buyer data and billing remain separately unapproved.",
            "proof_artifact": "private_launch_rehearsal_and_security_receipts",
        },
        "IDEA_QUALITY": {
            "next_change": "Rank novel buyer problems by independently checked sources and explicit falsification criteria.",
            "measurement": "nonduplicated_source_grounded_testable_ideas",
            "test_plan": [
                "Use original dated primary sources and reject identical workflow mechanics or untestable novelty claims.",
                "Attach a unique buyer job, trigger, failure consequence and invalidating interview question to every candidate.",
                "Do not infer commercial validation from sources that only describe regulations or technical context.",
            ],
            "required_gate": "External buyer interviews or opt-in pilots before claiming demand.",
            "proof_artifact": "distinct_source_checked_idea_decision_records",
        },
        "AUTOMATION_RELIABILITY": {
            "next_change": "Make missed autonomous manufacturing recoveries idempotent and restart-safe.",
            "measurement": "verified_distinct_app_cycles_without_duplicate_builds",
            "test_plan": [
                "Replay backlog/restart transitions across independent runners and durable checkpoint restore.",
                "Reject duplicate packages, source drift and missing receipts with bounded retries.",
                "Verify source-pinned artifacts contain runnable applications, not fixture-only demonstrations.",
            ],
            "required_gate": "No unreviewed schedule/hosting/external payments and no production deployment from simulated CI alone.",
            "proof_artifact": "source_pinned_cross_runner_cycle_integrity_receipts",
        },
        "APPLICATION_DEPTH": {
            "next_change": "Verify complete tenant-safe data workflows and distinct use cases before manufacturing additional variants.",
            "measurement": "independently_accepted_distinct_full_stack_workflows",
            "test_plan": [
                "Compare behavior and real storage models rather than names and marketing copy.",
                "Run separate operator/reviewer desktop/mobile tests with cold restart and negative authorization cases.",
            ],
            "required_gate": "No buyer, production-host or payment claim without separate evidence.",
            "proof_artifact": "source_pinned_distinct_app_acceptance_receipts",
        },
    },
}


def _contract(project, theme):
    mapping = CONTRACTS[project]
    if theme not in mapping:
        return {
            "next_change": "Inspect the draft against a defined project metric before proposing a change.",
            "measurement": ("incorrect_recovery_recommendations_per_100_labeled_invoices"
                            if project == "retally" else
                            "buyer_confirmed_pilot_workflow_completions"),
            "test_plan": ["Find a source-pinned before/after fixture and an adversarial counterexample.",
                          "Run project CI and seek an independent project owner review."],
            "required_gate": "No release or buyer-value claim without independently verified evidence.",
            "proof_artifact": "exact_source_review_and_measurement_receipt",
        }
    return mapping[theme]


def build_action_packets(priority_improvements):
    """Deterministic candidate-specific review work, never a shipping decision."""
    require(type(priority_improvements) is list
            and len(priority_improvements) == 2
            and {row.get("project_id") for row in priority_improvements}
            == set(CONTRACTS), "ACTION_PRIORITY_CONTRACT_INVALID")
    packet = []
    for project in priority_improvements:
        pid = project["project_id"]
        expected_repo = dict(FOCUS_REPOSITORIES)[pid]
        require(project.get("repository") == expected_repo,
                "ACTION_WRONG_REPOSITORY")
        evidence = project.get("active_pr_review") or {}
        ranked = evidence.get("ranked_opportunities", [])
        require(type(ranked) is list and len(ranked) <= 4,
                "ACTION_RANKED_SOURCE_INVALID")
        selected = evidence.get("pr_number")
        item_list = []
        unique = set()
        for candidate in ranked[:3]:
            require(type(candidate) is dict
                    and type(candidate.get("pr_number")) is int
                    and candidate["pr_number"] not in unique
                    and type(candidate.get("head_sha")) is str
                    and SHA.fullmatch(candidate["head_sha"])
                    and candidate.get("pr_url") ==
                    f"https://github.com/{expected_repo}/pull/{candidate['pr_number']}"
                    and type(candidate.get("heuristic_relevance")) is int
                    and 0 <= candidate["heuristic_relevance"] <= 100
                    and type(candidate.get("opportunity_theme")) is str
                    and type(candidate.get("draft")) is bool,
                    "ACTION_PR_PROVENANCE_INVALID")
            unique.add(candidate["pr_number"])
            theme = candidate["opportunity_theme"]
            contract = _contract(pid, theme)
            ci = (evidence.get("checks", {}).get("status")
                  if selected == candidate["pr_number"] else "NOT_CHECKED_IN_PRIORITY_SAMPLE")
            require(type(ci) is str, "ACTION_CI_INVALID")
            if ci == "ADVERSE_CHECKS_OBSERVED":
                gate = "REPAIR_EXACT_SOURCE_CI_BEFORE_TESTING"
            elif ci in {"SKIPPED_CHECKS_NOT_ACCEPTANCE", "INCOMPLETE_CHECKS_OBSERVED",
                        "NOT_CHECKED_IN_PRIORITY_SAMPLE", "NO_CHECK_RUNS_OBSERVED"}:
                gate = "EXACT_SOURCE_CI_AND_PROVENANCE_REQUIRED"
            elif ci == "CHECKS_GREEN_NOT_RELEASE_OR_BUSINESS_ACCEPTANCE":
                gate = ("STACK_DEPENDENCY_REVIEW_REQUIRED"
                        if candidate.get("base_ref") != "main" else
                        "INDEPENDENT_BEFORE_AFTER_TEST_REQUIRED")
            else:
                gate = "EVIDENCE_REVIEW_REQUIRED"
            item_list.append({
                "priority_within_project": len(item_list) + 1,
                "source_repository": expected_repo,
                "source_pr_number": candidate["pr_number"],
                "source_pr_url": candidate["pr_url"],
                "source_head_sha": candidate["head_sha"],
                "theme": theme,
                "heuristic_relevance": candidate["heuristic_relevance"],
                "relevance_not_verified_value": True,
                "candidate_draft": candidate["draft"],
                "base_branch": candidate.get("base_ref"),
                "source_ci_status": ci,
                "action_gate": gate,
                "next_reviewable_change": contract["next_change"],
                "target_metric": contract["measurement"],
                "verification_steps": list(contract["test_plan"]),
                "required_release_gate": contract["required_gate"],
                "required_proof_artifact": contract["proof_artifact"],
                "before_value": None,
                "after_value": None,
                "measured_improvement": None,
                "buyer_value_verified": False,
                "production_release_approved": False,
                "downstream_mutation_authority": False,
                "external_message_or_payment_authority": False,
            })
        packet.append({
            "project_id": pid,
            "repository": expected_repo,
            "source_default_branch_revision": project.get("observed_source_sha"),
            "selected_source_pr": selected if type(selected) is int else None,
            "candidate_count": len(ranked),
            "actionable_review_packets": item_list,
            "missing_evidence": (
                "NEEDS_SOURCE_PINNED_CANDIDATES" if not item_list else
                "PROJECT_SPECIFIC_MEASUREMENT_AND_INDEPENDENT_REVIEW_PENDING"
            ),
            "measurement_claim": "NONE_ESTABLISHED",
            "verified_revenue": None,
        })
    return packet
