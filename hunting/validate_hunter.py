#!/usr/bin/env python3
"""Static/cross-file Step 9 Autonomous Hunter validator."""
from __future__ import annotations
import json
from pathlib import Path
from hunting.autonomous_hunter import _queries, detect_gaps, load_policy, load_query_concepts, load_seed_state, load_strategies, run_cycle, search_concepts_for_gap, select_objectives, validate_state
from hunting.calibration import run_calibration
from hunting.controlled_proof import load_cases as load_controlled_cases
from hunting.proposal_state import load_seed_state as load_proposal_seed, validate_state as validate_proposal_state
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
    req(policy["repository_count_reward"]==0,"repository count must not be rewarded")
    req(policy["learning"]["verified_outcomes_only_for_value_credit"] is True,"Hunter value training must require verified outcomes")
    req(policy["learning"]["exploration_floor_fraction"]>=0.20,"exploration floor weakened")
    req(policy["learning"]["verified_outcome_strategy_priority"] is True,"verified Hunter outcome priority disabled")
    req(policy["learning"]["verified_outcome_priority_mode"]=="ORDER_EXPLOIT_STRATEGIES_BY_VERIFIED_VALUE_OUTCOMES","Hunter feedback priority mode drifted")
    req(policy["learning"]["unverified_activity_cannot_increase_strategy_priority"] is True,"unverified Hunter activity may increase priority")
    query_policy=policy["query_generation"]
    req(query_policy["taxonomy_file"]=="hunting/QUERY_CONCEPTS.json","Hunter query taxonomy path drifted")
    req(query_policy["repository_search_mode"]=="METADATA_FIRST_THEN_EXACT_REVISION_STRUCTURAL_INSPECTION","Hunter repository search semantics drifted")
    req(query_policy["portfolio_brand_names_default"] is False,"Hunter query generation reverted to portfolio brand names")
    req(query_policy["rotate_queries_by_state_sequence"] is True and query_policy["prefer_lowest_negative_hits"] is True,"Hunter dead-end query rotation disabled")
    req(query_policy["structural_ranking_uses_semantic_concepts"] is True,"Hunter structural ranking lost semantic concepts")
    req(policy["budgets"]["max_candidates_inspected_per_query"]==2,"Hunter per-query inspection fairness cap drifted")
    failure_policy=policy["inspection_failure_handling"]
    req(failure_policy["candidate_disposition"]=="UNAVAILABLE_NOT_REJECTED","Hunter inspection failures became candidate rejection")
    req(failure_policy["reason_code"]=="EXACT_REVISION_INSPECTION_UNAVAILABLE","Hunter inspection failure reason drifted")
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
    priority_probe["strategy_stats"][target]["verified_value_outcomes"]=2
    priority_objectives=[x for x in select_objectives(priority_probe) if not x["exploration"]]
    req(priority_objectives and priority_objectives[0]["strategy_id"]==target,"verified Hunter outcome did not affect exploit strategy order")
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
    proposal_seed=load_proposal_seed();validate_proposal_state(proposal_seed)
    req(proposal_seed["proposals"]==[] and proposal_seed["findings"]==[],"Hunter proposal seed invented findings")
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
    wf=(ROOT/".github/workflows/hunter-autonomous-cycle.yml").read_text()
    for s in ["contents: read","actions: read","timeout-minutes: 5","PORTFOLIO_HUNTER_DISABLED","47 */6 * * *","cancel-in-progress: false","actions/upload-artifact@v4","python -m hunting.calibration --output hunting/out/calibration_report.json",".github/triggers/hunter-autonomous-now.txt"]:
        req(s in wf,f"Hunter workflow missing {s}")
    req(wf.index("concurrency:")>wf.index("hunt:"),"Hunter cost concurrency must be job-level so cancelled queued jobs remain rerunnable")
    req("portfolio-hunter-proposal-state" in wf and "hunting/out/hunter_proposal_state.json" in wf,"Hunter workflow does not persist proposal inbox")
    trigger=(ROOT/".github/triggers/hunter-autonomous-now.txt").read_text()
    req("authority=OBSERVE" in trigger and "model-calls=0" in trigger,"Hunter on-demand trigger widened authority/cost")
    runtime_event=(ROOT/".github/workflows/runtime-event-observe.yml").read_text()
    req('".github/triggers/hunter-autonomous-now.txt"' in runtime_event and '".github/workflows/hunter-autonomous-cycle.yml"' in runtime_event,"Hunter proof trigger is not isolated from runtime-event churn")
    proof_wf=(ROOT/".github/workflows/hunter-controlled-proof.yml").read_text()
    for s in ["contents: read","actions: read","timeout-minutes: 5","hunting/TRIGGER_CONTROLLED_PROOF","python -m hunting.controlled_proof --output hunting/out/controlled_proof.json","portfolio-hunter-controlled-proof"]:
        req(s in proof_wf,f"controlled Hunter proof workflow missing {s}")
    req("portfolio-cost-governed-autonomy" not in proof_wf,"controlled proof must not compete for persistent autonomous-state concurrency")
    low=(wf+"\n"+proof_wf).lower()
    for forbidden in ["contents: write","pull-requests: write","issues: write","id-token: write","git push","gh pr","openai","anthropic"]:
        req(forbidden not in low,f"forbidden Hunter workflow capability: {forbidden}")
    return {"pinned_components":len(expected),"strategies":len(strategies),"detected_gaps":len(gaps),"selected_objectives":len(objectives),"exploration_objectives":sum(1 for x in objectives if x["exploration"]),"hard_reject_reasons":evaluation["hard_reject_reasons"],"soft_signals_do_not_reject":evaluation["soft_signals_do_not_reject"],"ranking_max_score":ranking["max_score"],"rejection_funnel_reconciled":True,"query_outcomes":len(probe_receipt["query_outcomes"]),"calibration_cases":calibration["case_count"],"calibration_positive_retained":calibration["positive_retained"],"calibration_negative_rejected":calibration["negative_rejected"],"calibration_ambiguous_matched":calibration["ambiguous_matched"],"calibration_rank_bands":calibration["rank_band_counts"],"controlled_proof_cases":len(controlled["cases"]),"controlled_proof_min_retained":controlled["completion_gate"]["min_retained_candidates"],"controlled_proof_min_strategies":controlled["completion_gate"]["min_distinct_strategies"],"verified_outcome_strategy_priority":True,"semantic_query_taxonomy":concepts["taxonomy_id"],"semantic_query_categories":len(concepts["category_concepts"]),"per_query_inspection_cap":policy["budgets"]["max_candidates_inspected_per_query"],"proposal_min_rank":proposal_gate["minimum_rank_band"],"proposal_cycle_cap":proposal_gate["max_experiment_proposals_per_cycle"],"proposal_artifact":proposal_persistence["artifact_name"],"proposal_seed_sequence":proposal_seed["sequence"],"inspection_failure_mode":failure_policy["cycle_behavior"],"inspection_failure_reason":failure_policy["reason_code"],"model_calls":0,"downstream_writes":0,"external_actions":0}
if __name__=="__main__":print("portfolio-brain Step 9 Hunter: PASS",json.dumps(validate_hunter(),sort_keys=True))
