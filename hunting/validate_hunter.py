#!/usr/bin/env python3
"""Static/cross-file Step 9 Autonomous Hunter validator."""
from __future__ import annotations
from legacy.workflow_archive import legacy_workflow_path
import json
from pathlib import Path
from hunting.autonomous_hunter import CandidateInspectionError, HunterError, _queries, detect_gaps, load_policy, load_query_concepts, load_seed_state, load_strategies, run_cycle, search_concepts_for_gap, select_objectives, strategy_priority_maturity, validate_state
from hunting.calibration import run_calibration
from hunting.controlled_proof import load_cases as load_controlled_cases
from hunting.rights_gate import build_rights_record, validate_rights_record
from hunting.proposal_state import load_seed_state as load_proposal_seed, validate_state as validate_proposal_state
from hunting.proposal_review_state import load_seed_state as load_proposal_review_seed, validate_state as validate_proposal_review_state
from hunting.lifecycle import STAGES as HUNTER_LIFECYCLE_STAGES
from hunting.downstream_lifecycle import (
    APPROVAL_CODE as HUNTER_ACCEPTANCE_APPROVAL_CODE,
    ARTIFACT_NAME as HUNTER_LIFECYCLE_ARTIFACT,
    load_seed_state as load_lifecycle_seed,
    validate_state as validate_lifecycle_state,
)
ROOT=Path(__file__).resolve().parents[1]
class HunterValidationError(ValueError): pass
def req(ok,msg):
    if not ok: raise HunterValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())
def validate_hunter():
    state=load("PORTFOLIO_BUILD_STATE.json"); pin=load("hunting/AI_BUSINESS_OS_HUNTER_PIN.json")
    policy=load_policy(); seed=load_seed_state(); validate_state(seed); strategies=load_strategies()
    req(state["repositories"]["REPO-001"]["last_inspected_sha"]==pin["source_revision"],"Hunter source cursor drifted")
    req(pin["copied_source_code"] is False,"canonical Hunter source must not be copied")
    req(pin["source_revision"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","unexpected Hunter source revision")
    expected={
      "business_os_bridge":"185866871c1e3eaa9d8d3aadc700c11c05babc0c",
      "seed_compiler":"6ab65a4f5593601d21d58e9d3a2d771fb070e3bb",
      "allocator":"7832c10f16925d35b6446c24a999b9cef5e212b5",
      "adaptive_policy":"fcb7193202e7a5ac68ff5c205653db4a73631c81",
      "learning_report":"562ec2cc880924a366e3ec45c5e053c555c22a36",
      "run_ingest":"844337f7f87991282d20b6862e4d82553bc6d14e"
    }
    for k,v in expected.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(policy["authority_class"]=="OBSERVE","Hunter authority changed")
    req(policy["model_calls_allowed"]==0 and policy["downstream_writes_allowed"]==0 and policy["external_actions_allowed"]==0,"Hunter authority widened")
    req(policy["source_allowlist"]==["PUBLIC_GITHUB"],"Hunter source allowlist widened")
    separation=policy["signal_separation"]
    req(separation["supply_sensor"]=="PUBLIC_GITHUB","Hunter supply sensor drifted")
    req(separation["demand_sensor"]=="PORTFOLIO_SANITIZED_MARKET_EVIDENCE","Hunter demand sensor drifted")
    req(separation["github_supply_is_demand"] is False,"GitHub supply was allowed to masquerade as demand")
    req(separation["supply_only_can_authorize_commercial_build"] is False,"supply-only discovery can authorize commercial build")
    req(separation["demand_evidence_classes"]==["MARKET_VERIFIED","REVENUE_VERIFIED"],"Hunter demand evidence classes drifted")
    lifecycle=policy["downstream_lifecycle"]
    req(tuple(lifecycle["stages"])==HUNTER_LIFECYCLE_STAGES,"Hunter downstream lifecycle stages drifted")
    req(lifecycle["review_can_self_authorize_work"] is False and lifecycle["explicit_acceptance_receipt_required"] is True,"Hunter review can self-authorize downstream work")
    req(lifecycle["implementation_mode"]=="ISOLATED_REIMPLEMENTATION_NO_SOURCE_COPY","Hunter downstream implementation mode widened")
    req(lifecycle["automatic_merge_authority_granted"] is False and lifecycle["automatic_deployment_authority_granted"] is False,"Hunter lifecycle granted merge/deploy authority")
    req(lifecycle["technical_evidence_can_claim_market_value"] is False and lifecycle["technical_evidence_can_claim_revenue_value"] is False,"technical evidence can masquerade as market/revenue value")
    req(lifecycle["market_evidence_kind"]=="MARKET_OUTCOME" and lifecycle["revenue_evidence_kind"]=="REVENUE_OUTCOME","external value evidence classes drifted")
    req(lifecycle["new_state_journal_domain_required"] is False,"Hunter lifecycle created an unnecessary duplicate state-journal domain")
    req(lifecycle["bridge_module"]=="hunting/downstream_lifecycle.py","Hunter downstream bridge module drifted")
    req(lifecycle["persistence_artifact_name"]==HUNTER_LIFECYCLE_ARTIFACT,"Hunter lifecycle artifact identity drifted")
    req(lifecycle["seed_file"]=="hunting/HUNTER_LIFECYCLE_STATE_SEED.json","Hunter lifecycle seed path drifted")
    req(lifecycle["acceptance_approval_code"]==HUNTER_ACCEPTANCE_APPROVAL_CODE,
        "Hunter work acceptance approval code drifted")
    req(lifecycle["acceptance_source_binding"]=="EXACT_REVIEW_ID_AND_REVIEW_HASH",
        "Hunter work acceptance lost exact review binding")
    req(lifecycle["production_target_scope"]=="CURRENT_WRITE_ENABLED_REPOSITORY_ONLY",
        "Hunter downstream factory target scope widened")
    req(lifecycle["recurring_bridge_workflow"]==".github/workflows/portfolio-autonomous-scheduler.yml",
        "Hunter downstream recurring bridge workflow drifted")
    req(lifecycle["scheduler_work_type"]=="IMPLEMENTATION",
        "Hunter accepted work no longer enters the implementation scheduler lane")
    scopes=lifecycle["implementation_target_prefixes_by_repository"]
    req(scopes.get("REPO-008") and len(scopes["REPO-008"])==len(set(scopes["REPO-008"])),
        "Hunter implementation target scope missing or duplicated")
    req(isinstance(lifecycle["implementation_regression_requirement"],str)
        and "regression" in lifecycle["implementation_regression_requirement"].lower(),
        "Hunter implementation regression requirement missing")
    req(lifecycle["acceptance_milestone_binding"]==
        "CURRENT_VALUE_LOOP_CLOSEST_EXTERNAL_MILESTONE_AS_ROUTING_CONTEXT_NOT_VALUE_PROOF",
        "Hunter milestone routing/value-proof separation drifted")

    lifecycle_seed=load_lifecycle_seed();validate_lifecycle_state(lifecycle_seed)
    req(lifecycle_seed["records"]==[] and lifecycle_seed["sequence"]==0,
        "Hunter lifecycle seed invented accepted downstream work")
    rights_policy=load("hunting/RIGHTS_GATE_POLICY.json")
    req(rights_policy["mode"]=="FAIL_CLOSED_NO_REUSE_AUTHORITY_FROM_DISCOVERY","Hunter rights gate mode weakened")
    req(rights_policy["automatic_reuse_authority_granted"] is False,"Hunter discovery may not grant reuse authority")
    commercial=policy.get("commercial_speculation",{})
    req(policy["objective_function"]=="DISCOVER_VERIFIABLE_ENGINEERING_IMPROVEMENTS_FOR_ACTIVE_PROJECTS_WITH_ZERO_COMMERCIAL_SPECULATION_WEIGHT","Hunter objective function is not engineering-first")
    req(commercial.get("enabled") is False,"Hunter commercial speculation re-enabled")
    req(commercial.get("expected_future_revenue_usd")==0,"Hunter assigned future revenue to retired businesses")
    req(commercial.get("priority_weight")==0,"Hunter commercial speculation retained priority weight")
    req(commercial.get("new_business_ideas_allowed") is False and commercial.get("marketplace_demand_hunting_allowed") is False and commercial.get("outreach_idea_generation_allowed") is False,"Hunter can generate replacement commercial speculation")
    req(all(gap["external_validation_value"]==0 for gap in detect_gaps()),"Hunter active gaps retain commercial validation weighting")
    req(policy["repository_count_reward"]==0,"repository count must not be rewarded")
    req(policy["learning"]["verified_outcomes_only_for_value_credit"] is True,"Hunter value training must require verified outcomes")
    req(policy["learning"]["exploration_floor_fraction"]>=0.20,"exploration floor weakened")
    req(policy["learning"]["verified_outcome_strategy_priority"] is True,"verified Hunter outcome priority disabled")
    req(policy["learning"]["verified_outcome_priority_mode"]=="ORDER_EXPLOIT_STRATEGIES_BY_VERIFIED_VALUE_OUTCOMES","Hunter feedback priority mode drifted")
    req(policy["learning"]["unverified_activity_cannot_increase_strategy_priority"] is True,"unverified Hunter activity may increase priority")
    req(policy["learning"]["minimum_verified_outcomes_before_strategy_priority"]>=2,"Hunter verified-outcome maturity gate too weak")
    req(policy["learning"]["verified_outcome_priority_requires_existing_activity_maturity"] is True,"Hunter strategy priority bypasses activity maturity")
    query_policy=policy["query_generation"]
    req(query_policy["taxonomy_file"]=="hunting/QUERY_CONCEPTS.json","Hunter query taxonomy path drifted")
    req(query_policy["repository_search_mode"]=="METADATA_FIRST_THEN_EXACT_REVISION_STRUCTURAL_INSPECTION","Hunter repository search semantics drifted")
    req(query_policy["portfolio_brand_names_default"] is False,"Hunter query generation reverted to portfolio brand names")
    req(query_policy["rotate_queries_by_state_sequence"] is True and query_policy["prefer_lowest_negative_hits"] is True,"Hunter dead-end query rotation disabled")
    req(query_policy["structural_ranking_uses_semantic_concepts"] is True,"Hunter structural ranking lost semantic concepts")
    req(policy["budgets"]["max_candidates_inspected_per_query"]==2,"Hunter per-query inspection fairness cap drifted")
    failure_policy=policy["inspection_failure_handling"]
    req(failure_policy["candidate_disposition"]=="UNAVAILABLE_NOT_REJECTED","Hunter inspection failures became candidate rejection")
    req(failure_policy["reason_code"]=="CANDIDATE_INSPECTION_UNAVAILABLE","Hunter inspection failure reason drifted")
    req(failure_policy["counts_against_inspection_budget"] is True,"Hunter inspection errors escaped budget accounting")
    req(failure_policy["records_negative_query_knowledge"] is False,"Hunter transient inspection errors may train dead-end knowledge")
    req(failure_policy["cycle_behavior"]=="CONTINUE_BOUNDED","Hunter inspection failures may abort the whole cycle")
    concepts=load_query_concepts()
    req(concepts["schema_version"]=="1.0.0" and concepts["taxonomy_id"]=="portfolio-hunter-query-concepts-v1","Hunter query concept taxonomy identity drifted")
    req(concepts["max_concepts_per_gap"]>=3,"Hunter query concept breadth too narrow")
    req("business" in concepts["generic_categories"] and "product" in concepts["generic_categories"],"generic Hunter categories not filtered")
    req(len(concepts["category_concepts"])>=10,"Hunter semantic concept coverage too narrow")
    priority_probe=load_seed_state()
    target="STRAT:fail-open-boundary-archaeology"
    learning=policy["learning"]
    priority_probe["strategy_stats"][target]["cycles"]=learning["minimum_cycles_before_strategy_adjustment"]
    priority_probe["strategy_stats"][target]["inspected"]=learning["minimum_inspections_before_strategy_adjustment"]
    priority_probe["strategy_stats"][target]["verified_value_outcomes"]=learning["minimum_verified_outcomes_before_strategy_priority"]
    maturity=strategy_priority_maturity(priority_probe,target,policy)
    req(maturity["mature"] is True,"Hunter strategy did not satisfy configured maturity gate")
    priority_objectives=[x for x in select_objectives(priority_probe) if not x["exploration"]]
    req(priority_objectives and priority_objectives[0]["strategy_id"]==target,"mature verified Hunter outcome did not affect exploit strategy order")
    warmup=load_seed_state()
    warmup["strategy_stats"][target]["cycles"]=learning["minimum_cycles_before_strategy_adjustment"]
    warmup["strategy_stats"][target]["inspected"]=learning["minimum_inspections_before_strategy_adjustment"]
    warmup["strategy_stats"][target]["verified_value_outcomes"]=1
    req(strategy_priority_maturity(warmup,target,policy)["mature"] is False,"single Hunter value outcome incorrectly became mature")
    warmup_objectives=[x for x in select_objectives(warmup) if not x["exploration"]]
    req(warmup_objectives and warmup_objectives[0]["strategy_id"]!=target,"warmup Hunter feedback improperly reordered exploit strategy")
    evaluation=policy["candidate_evaluation"]
    req(evaluation["hard_reject_reasons"]==["NO_IMPLEMENTATION_PATHS"],"Hunter structural hard-reject surface widened")
    req(evaluation["terminal_duplicate_reason"]=="EXACT_REVISION_CAPABILITY_DUPLICATE","Hunter duplicate terminal reason drifted")
    req(evaluation["soft_signals_do_not_reject"] is True,"Hunter soft signals became hard gates")
    ranking=evaluation["ranking"]
    req(sum(ranking["weights"].values())==ranking["max_score"],"Hunter ranking weights/max score mismatch")
    req(ranking["bands"]["HIGH"]["min_score"]>ranking["bands"]["MEDIUM"]["min_score"]>ranking["bands"]["LOW"]["min_score"],"Hunter ranking bands invalid")
    req(ranking["value_credit_source"]=="VERIFIED_OUTCOMES_ONLY","Hunter ranking may not create value credit")
    proposal_gate=evaluation["proposal_gate"]
    req(proposal_gate["minimum_rank_band"]=="MEDIUM","Hunter proposal quality floor weakened")
    req(1<=proposal_gate["max_experiment_proposals_per_cycle"]<=policy["budgets"]["max_candidates_inspected_per_cycle"],"Hunter proposal cycle cap invalid")
    req(proposal_gate["low_rank_disposition"]=="RETAIN_OBSERVED_WITHOUT_PROPOSAL","low-rank Hunter candidates are not kept as observed near misses")
    req(proposal_gate["value_credit_source"]=="VERIFIED_OUTCOMES_ONLY","Hunter proposal gate may not create value credit")
    proposal_persistence=policy["proposal_persistence"]
    req(proposal_persistence["artifact_name"]=="portfolio-hunter-proposal-state","Hunter proposal artifact identity drifted")
    req(proposal_persistence["seed_file"]=="hunting/HUNTER_PROPOSAL_STATE_SEED.json","Hunter proposal seed path drifted")
    req(proposal_persistence["sanitized_only"] is True and proposal_persistence["downstream_authority"]=="OBSERVE","Hunter proposal persistence widened data/authority")
    req(6<=proposal_persistence["max_backlog_proposals"]<=256,"Hunter proposal backlog cap invalid")
    req(proposal_persistence["carry_forward_prior_proposals"] is True,"Hunter proposal carry-forward disabled")
    req(proposal_persistence["origin_metadata_required"] is True,"Hunter proposal origin provenance disabled")
    req(proposal_persistence["compaction_policy"]=="DROP_OLDEST_LAST_SEEN_ONLY_AFTER_BACKLOG_CAP","Hunter proposal backlog compaction policy drifted")
    proposal_seed=load_proposal_seed();validate_proposal_state(proposal_seed)
    req(proposal_seed["proposals"]==[] and proposal_seed["findings"]==[] and proposal_seed["origins"]=={},"Hunter proposal seed invented findings")
    review_persistence=policy["proposal_review_persistence"]
    req(review_persistence["artifact_name"]=="portfolio-hunter-proposal-review-state","Hunter proposal review artifact identity drifted")
    req(review_persistence["seed_file"]=="hunting/HUNTER_PROPOSAL_REVIEW_STATE_SEED.json","Hunter proposal review seed path drifted")
    req(review_persistence["sanitized_only"] is True and review_persistence["authority_class"]=="OBSERVE","Hunter proposal review persistence widened data/authority")
    req(review_persistence["rights_resolution"]=="NONE","Hunter proposal review persistence may resolve reuse rights")
    proposal_review_seed=load_proposal_review_seed();validate_proposal_review_state(proposal_review_seed)
    req(proposal_review_seed["reviews"]==[] and proposal_review_seed["applied_execution_ids"]==[],"Hunter proposal review seed invented evidence")
    req(len(strategies)==4 and any(x["family"]=="EXPLORATION" for x in strategies),"strategy set/exploration missing")
    gaps=detect_gaps(); objectives=select_objectives(seed)
    req(len(gaps)>=1,"no structural portfolio gaps detected")
    req(1<=len(objectives)<=policy["budgets"]["max_objectives_per_cycle"],"objective generation out of bounds")
    req(any(x["exploration"] for x in objectives),"exploration objective missing")
    req(all(x["authority_class"]=="OBSERVE" for x in objectives),"objective authority widened")
    req(all(x.get("search_concepts") for x in objectives),"Hunter objectives missing semantic search concepts")
    capture=next(g for g in gaps if g["project_name"]=="CaptureBrief")
    exact=next(x for x in strategies if x["family"]=="EXACT_IMPLEMENTATION")
    capture_queries=_queries(capture,exact,seed)
    req(capture_queries and all("capturebrief" not in q.casefold() for q in capture_queries),"Hunter queries leaked portfolio brand name into repository search")
    req(any("government contract proposal" in q.casefold() or "rfp proposal" in q.casefold() for q in capture_queries),"Hunter semantic govcon query coverage missing")
    req("government contract proposal" in search_concepts_for_gap(capture),"Hunter CaptureBrief concept translation missing")
    class NoResultProvider:
        requests=0
        def search(self,query):
            self.requests+=1
            return []
        def inspect(self,candidate):
            raise AssertionError("zero-result provider must never inspect")
    _,probe_receipt=run_cycle(load_seed_state(),NoResultProvider(),at="2026-09-25T18:00:00Z")
    funnel=probe_receipt["rejection_funnel"]
    req(funnel["candidate_accounting_reconciled"] is True,"Hunter candidate funnel does not reconcile")
    req(funnel["disposition_accounting_reconciled"] is True,"Hunter disposition funnel does not reconcile")
    req(funnel["queries_executed"]>0 and funnel["queries_zero_results"]>0,"Hunter zero-result funnel evidence missing")
    req(funnel["inspection_errors"]==0 and funnel["inspection_succeeded"]==0,"zero-result probe inspection accounting drifted")
    req(len(probe_receipt["query_outcomes"])>0,"Hunter per-query rejection trace missing")
    class CandidateUnavailableThenUsable:
        requests=0
        def search(self,query):
            self.requests+=1
            return [
              {"id":1,"full_name":"public/unavailable","default_branch":"main","private":False},
              {"id":2,"full_name":"public/usable","default_branch":"main","private":False},
            ]
        def inspect(self,candidate):
            self.requests+=1
            if candidate["id"]==1:
                raise CandidateInspectionError("synthetic candidate unavailable")
            return {"revision":"a"*40,"tree_sha":"b"*40,"paths":["src/recovery.py","tests/test_recovery.py"],"truncated":False}
    _,failure_receipt=run_cycle(load_seed_state(),CandidateUnavailableThenUsable(),at="2026-09-25T18:00:00Z")
    req(failure_receipt["status"]=="PASS","single unavailable Hunter candidate aborted cycle")
    req(failure_receipt["rejection_funnel"]["inspection_errors"]>0,"Hunter inspection failure telemetry missing")
    req(failure_receipt["rejection_funnel"]["inspection_succeeded"]>0,"Hunter did not continue after unavailable candidate")
    req(failure_receipt["rejection_funnel"]["inspection_attempted"]==failure_receipt["rejection_funnel"]["inspection_errors"]+failure_receipt["rejection_funnel"]["inspection_succeeded"],"Hunter inspection budget accounting drifted")
    retained_rights=[x.get("rights") for x in failure_receipt["findings"] if x.get("disposition")=="RETAIN"]
    req(retained_rights and all(isinstance(x,dict) for x in retained_rights),"Hunter retained findings missing rights records")
    for rights in retained_rights:
        validate_rights_record(rights)
        req(rights["automatic_reuse_authority_granted"] is False,"Hunter discovery granted reuse authority")
        req(rights["source_revision_sha"]=="a"*40,"Hunter rights record lost exact-revision binding")
    class ControlPlaneFailure:
        requests=0
        def search(self,query):
            self.requests+=1
            return [{"id":1,"full_name":"public/control-plane","default_branch":"main","private":False}]
        def inspect(self,candidate):
            raise HunterError("Hunter API request budget exceeded")
    try:
        run_cycle(load_seed_state(),ControlPlaneFailure(),at="2026-09-25T18:00:00Z")
    except HunterError:
        pass
    else:
        raise HunterValidationError("Hunter control-plane inspection failure did not fail closed")
    calibration=run_calibration()
    req(calibration["status"]=="PASS","Hunter calibration corpus failed")
    req(calibration["positive_cases"]>=10 and calibration["positive_retained"]==calibration["positive_cases"],"Hunter positive controls do not all retain")
    req(calibration["negative_cases"]>=10 and calibration["negative_rejected"]==calibration["negative_cases"],"Hunter negative controls do not all reject")
    req(calibration["ambiguous_cases"]>=3 and calibration["ambiguous_matched"]==calibration["ambiguous_cases"],"Hunter ambiguous controls drifted")
    req(calibration["rank_band_counts"]["HIGH"]>0 and calibration["rank_band_counts"]["MEDIUM"]>0 and calibration["rank_band_counts"]["LOW"]>0,"Hunter calibration does not exercise all rank bands")
    req(calibration["soft_signal_case_count"]>0,"Hunter calibration does not exercise soft ranking signals")
    req(calibration["network_calls"]==0 and calibration["state_mutations"]==0,"Hunter calibration widened authority")
    controlled=load_controlled_cases()
    req(controlled["authority_class"]=="OBSERVE","controlled Hunter proof authority widened")
    req(controlled["completion_gate"]["min_retained_candidates"]>=3,"controlled Hunter proof retained gate too weak")
    req(controlled["completion_gate"]["min_distinct_strategies"]>=2,"controlled Hunter proof strategy gate too weak")
    req(len({x["strategy_id"] for x in controlled["cases"]})>=2,"controlled Hunter proof lacks strategy diversity")
    hunter_source=(ROOT/"hunting/autonomous_hunter.py").read_text()
    req("build_hunter_signal_snapshot" in hunter_source and "hunter_supply_demand_signals.json" in hunter_source,"Hunter does not emit separated supply/demand evidence")
    signal_source=(ROOT/"hunting/signal_router.py").read_text()
    req('"github_supply_creates_demand":False' in signal_source and '"commercial_build_authorized_by_supply_only":False' in signal_source,"Hunter signal router weakened supply/demand boundary")
    wf=(legacy_workflow_path(ROOT/".github/workflows/hunter-autonomous-cycle.yml")).read_text()
    for s in ["contents: read","actions: read","timeout-minutes: 10","PORTFOLIO_HUNTER_DISABLED","47 */6 * * *","cancel-in-progress: false","actions/upload-artifact@v4","python -m hunting.calibration --output hunting/out/calibration_report.json",".github/triggers/hunter-autonomous-now.txt"]:
        req(s in wf,f"Hunter workflow missing {s}")
    req(wf.index("concurrency:",wf.index("hunt:"))>wf.index("hunt:"),"Hunter shared-state mutex must cover the writer job")
    req("portfolio-hunter-proposal-state" in wf and "hunting/out/hunter_proposal_state.json" in wf,"Hunter workflow does not persist proposal inbox")
    req("python -m state_journal.production_reader --domain proposals --output hunting/live/hunter_proposal_state.json" in wf,"Hunter workflow does not restore canonical proposal backlog")
    trigger=(ROOT/".github/triggers/hunter-autonomous-now.txt").read_text()
    req("authority=OBSERVE" in trigger and "model-calls=0" in trigger,"Hunter on-demand trigger widened authority/cost")
    runtime_event=(legacy_workflow_path(ROOT/".github/workflows/runtime-event-observe.yml")).read_text()
    req('".github/triggers/hunter-autonomous-now.txt"' in runtime_event and '".github/workflows/hunter-autonomous-cycle.yml"' in runtime_event,"Hunter proof trigger is not isolated from runtime-event churn")
    proof_wf=(legacy_workflow_path(ROOT/".github/workflows/hunter-controlled-proof.yml")).read_text()
    for s in ["contents: read","actions: read","timeout-minutes: 5","hunting/TRIGGER_CONTROLLED_PROOF","python -m hunting.controlled_proof --output hunting/out/controlled_proof.json","portfolio-hunter-controlled-proof"]:
        req(s in proof_wf,f"controlled Hunter proof workflow missing {s}")
    req("portfolio-cost-governed-autonomy" not in proof_wf,"controlled proof must not compete for persistent autonomous-state concurrency")
    low=(wf+"\n"+proof_wf).lower()
    for forbidden in ["contents: write","pull-requests: write","issues: write","id-token: write","git push","gh pr","openai","anthropic"]:
        req(forbidden not in low,f"forbidden Hunter workflow capability: {forbidden}")
    return {"pinned_components":len(expected),"strategies":len(strategies),"detected_gaps":len(gaps),"selected_objectives":len(objectives),"exploration_objectives":sum(1 for x in objectives if x["exploration"]),"hard_reject_reasons":evaluation["hard_reject_reasons"],"soft_signals_do_not_reject":evaluation["soft_signals_do_not_reject"],"ranking_max_score":ranking["max_score"],"rejection_funnel_reconciled":True,"query_outcomes":len(probe_receipt["query_outcomes"]),"calibration_cases":calibration["case_count"],"calibration_positive_retained":calibration["positive_retained"],"calibration_negative_rejected":calibration["negative_rejected"],"calibration_ambiguous_matched":calibration["ambiguous_matched"],"calibration_rank_bands":calibration["rank_band_counts"],"controlled_proof_cases":len(controlled["cases"]),"controlled_proof_min_retained":controlled["completion_gate"]["min_retained_candidates"],"controlled_proof_min_strategies":controlled["completion_gate"]["min_distinct_strategies"],"verified_outcome_strategy_priority":True,"strategy_priority_min_verified_outcomes":learning["minimum_verified_outcomes_before_strategy_priority"],"semantic_query_taxonomy":concepts["taxonomy_id"],"semantic_query_categories":len(concepts["category_concepts"]),"per_query_inspection_cap":policy["budgets"]["max_candidates_inspected_per_query"],"proposal_min_rank":proposal_gate["minimum_rank_band"],"proposal_cycle_cap":proposal_gate["max_experiment_proposals_per_cycle"],"proposal_artifact":proposal_persistence["artifact_name"],"proposal_seed_sequence":proposal_seed["sequence"],"proposal_backlog_cap":proposal_persistence["max_backlog_proposals"],"proposal_carry_forward":proposal_persistence["carry_forward_prior_proposals"],"proposal_review_artifact":review_persistence["artifact_name"],"proposal_review_seed_sequence":proposal_review_seed["sequence"],"inspection_failure_mode":failure_policy["cycle_behavior"],"inspection_failure_reason":failure_policy["reason_code"],"model_calls":0,"downstream_writes":0,"external_actions":0}
if __name__=="__main__":print("portfolio-brain Step 9 Hunter: PASS",json.dumps(validate_hunter(),sort_keys=True))