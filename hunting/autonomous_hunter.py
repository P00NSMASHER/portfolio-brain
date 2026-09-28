#!/usr/bin/env python3
"""Autonomous portfolio Hunter: gap -> bounded public search -> evidence -> experiment proposal.

Public source content is treated as untrusted data, never as instruction. The v1
executor inspects repository metadata and exact-revision tree structure only; it
does not execute discovered code or copy repository contents.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hunting.rights_gate import build_rights_record, validate_rights_record

ROOT=Path(__file__).resolve().parents[1]
class HunterError(RuntimeError): pass
class CandidateInspectionError(HunterError): pass

def req(ok,msg):
    if not ok: raise HunterError(msg)
def load(path): return json.loads((ROOT/path).read_text(encoding="utf-8"))
def canon(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def digest(value):
    return "sha256:"+hashlib.sha256(canon(value).encode()).hexdigest()
def now_iso(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def slug(text):
    return re.sub(r"[^a-z0-9]+","-",text.lower()).strip("-") or "gap"

def load_policy(): return load("hunting/HUNTER_POLICY.json")
def load_strategies(): return load("hunting/SEARCH_STRATEGIES.json")["strategies"]
def load_query_concepts(): return load("hunting/QUERY_CONCEPTS.json")
def load_seed_state(): return load("hunting/HUNTER_STATE_SEED.json")

def validate_state(state):
    required={"schema_version","state_id","sequence","updated_at","seen_candidate_fingerprints","negative_knowledge","strategy_stats","exploration_cursor","feedback_ids","recent_cycles"}
    req(isinstance(state,dict) and set(state)==required,"hunter state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]=="portfolio-hunter-state","hunter state identity mismatch")
    req(isinstance(state["sequence"],int) and state["sequence"]>=0,"hunter sequence invalid")
    req(isinstance(state["seen_candidate_fingerprints"],dict),"seen fingerprint state invalid")
    req(isinstance(state["negative_knowledge"],list),"negative knowledge invalid")
    req(isinstance(state["strategy_stats"],dict),"strategy stats invalid")
    req(isinstance(state["exploration_cursor"],int) and state["exploration_cursor"]>=0,"exploration cursor invalid")
    req(isinstance(state["feedback_ids"],list) and len(state["feedback_ids"])==len(set(state["feedback_ids"])),"feedback ids invalid")
    req(isinstance(state["recent_cycles"],list) and len(state["recent_cycles"])<=20,"recent cycle history invalid")

def killed():
    file=load("hunting/KILL_SWITCH.json")
    if file.get("disabled") is True: return True,file.get("reason") or "file kill switch"
    if os.environ.get("PORTFOLIO_HUNTER_DISABLED","").strip().lower()=="true":
        return True,"repository/environment kill switch"
    return False,None

def _project_capability_map():
    ledger=load("graph/UNIVERSAL_GRAPH_LEDGER.json")
    nodes={n["node_id"]:n for n in ledger["nodes"]}
    result={}
    for edge in ledger["edges"]:
        if edge["status"]!="ACTIVE" or edge["edge_type"]!="HAS_CAPABILITY" or edge["verification_state"]!="VERIFIED": continue
        source=nodes[edge["source_node_id"]]; target=nodes[edge["target_node_id"]]
        if source["node_type"]=="PROJECT" and target["node_type"]=="CAPABILITY" and target["verification_state"]=="VERIFIED":
            result.setdefault(source["canonical_key"],set()).add(target["canonical_key"])
    return result

def search_concepts_for_gap(gap):
    cfg=load_query_concepts()
    generic=set(cfg["generic_categories"])
    mapping=cfg["category_concepts"]
    out=[]
    for category in gap["categories"]:
        for concept in mapping.get(category,[]):
            if concept not in out:
                out.append(concept)
        if category not in generic and category not in mapping:
            concept=category.replace("_"," ").strip()
            if concept and concept not in out:
                out.append(concept)
    if not out:
        out=["software architecture"]
    return out[:cfg["max_concepts_per_gap"]]

def detect_gaps():
    projects=load("registry/projects.json")["projects"]
    mapped=_project_capability_map()
    gaps=[]
    for p in projects:
        if p["registration_state"]!="REGISTERED" or p["lifecycle_status"] in {"RETIRED","PAUSED"}: continue
        existing=sorted(mapped.get(p["project_id"],set()))
        if existing: continue
        categories=p["categories"]
        key="capability-coverage:"+p["slug"]
        gid="HGAP-"+hashlib.sha256(key.encode()).hexdigest()[:20].upper()
        gaps.append({
          "gap_id":gid,"project_ids":[p["project_id"]],
          "need_type":"UNMAPPED_CAPABILITY_COVERAGE",
          "capability_key":key,
          "project_name":p["canonical_name"],
          "categories":categories,
          "evidence_refs":[f"registry:project:{p['project_id']}","graph:no-HAS_CAPABILITY-edge"],
          "importance":5 if p["project_type"] in {"BUSINESS","PRODUCT"} else 4,
          "uncertainty":5,"downstream_reuse":4 if p["project_type"]!="PORTFOLIO" else 5,
          "external_validation_value":4 if p["project_type"] in {"BUSINESS","PRODUCT"} else 3,
        })
    gaps.sort(key=lambda g:(-g["importance"],-g["external_validation_value"],g["gap_id"]))
    return gaps

def negative_hits(state,gap_id,strategy_id,query):
    norm=" ".join(query.casefold().split())
    return sum(int(x.get("hits",1)) for x in state["negative_knowledge"]
               if x.get("gap_id")==gap_id and x.get("strategy_id")==strategy_id and x.get("normalized_query")==norm)

def _queries(gap,strategy,state=None):
    concepts=search_concepts_for_gap(gap)
    out=[]
    for concept in concepts:
        for template in strategy["query_modes"]:
            q=" ".join(template.format(concept=concept).split())
            if q not in out:
                out.append(q)
    if not out:
        return []
    if state is None:
        return out
    offset_seed=hashlib.sha256((gap["gap_id"]+"|"+strategy["strategy_id"]).encode()).hexdigest()
    offset=(state["sequence"]+int(offset_seed[:8],16))%len(out)
    rotated=out[offset:]+out[:offset]
    return sorted(
      rotated,
      key=lambda q:negative_hits(state,gap["gap_id"],strategy["strategy_id"],q)
    )

def strategy_priority_maturity(state,strategy_id,policy=None):
    policy=policy or load_policy()
    learning=policy["learning"]
    stats=state["strategy_stats"][strategy_id]
    requirements={
      "minimum_cycles":int(learning["minimum_cycles_before_strategy_adjustment"]),
      "minimum_inspections":int(learning["minimum_inspections_before_strategy_adjustment"]),
      "minimum_verified_value_outcomes":int(learning.get("minimum_verified_outcomes_before_strategy_priority",1)),
    }
    req(all(v>=1 for v in requirements.values()),"Hunter strategy maturity requirements invalid")
    mature=(
      stats["cycles"]>=requirements["minimum_cycles"]
      and stats["inspected"]>=requirements["minimum_inspections"]
      and stats["verified_value_outcomes"]>=requirements["minimum_verified_value_outcomes"]
    )
    return {
      "status":"MATURE" if mature else "WARMUP",
      "mature":mature,
      "requirements":requirements,
      "observed":{
        "cycles":stats["cycles"],
        "inspected":stats["inspected"],
        "verified_value_outcomes":stats["verified_value_outcomes"],
      },
    }

def select_objectives(state):
    policy=load_policy(); strategies=load_strategies(); gaps=detect_gaps()
    maxn=policy["budgets"]["max_objectives_per_cycle"]
    explore_slots=max(1,round(maxn*policy["budgets"]["exploration_fraction"]))
    exploit_slots=maxn-explore_slots
    exploit_strategies=[s for s in strategies if s["family"]!="EXPLORATION"]
    if policy["learning"].get("verified_outcome_strategy_priority") is True:
        indexed=list(enumerate(exploit_strategies))
        exploit_strategies=[
          strategy for _,strategy in sorted(
            indexed,
            key=lambda item:(
              -int(strategy_priority_maturity(state,item[1]["strategy_id"],policy)["mature"]),
              -(
                state["strategy_stats"][item[1]["strategy_id"]]["verified_value_outcomes"]
                if strategy_priority_maturity(state,item[1]["strategy_id"],policy)["mature"]
                else 0
              ),
              item[0],
            )
          )
        ]
    exploration=next(s for s in strategies if s["family"]=="EXPLORATION")
    objectives=[]
    for idx,gap in enumerate(gaps[:exploit_slots]):
        strategy=exploit_strategies[idx%len(exploit_strategies)]
        queries=_queries(gap,strategy,state)[:policy["budgets"]["max_queries_per_objective"]]
        penalty=min(5,max((negative_hits(state,gap["gap_id"],strategy["strategy_id"],q) for q in queries),default=0))
        core={"gap_id":gap["gap_id"],"strategy_id":strategy["strategy_id"],"project_ids":gap["project_ids"],"capability_key":gap["capability_key"],"exploration":False}
        oid="HOBJ-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper()
        objectives.append({
          "schema_version":"1.0.0","objective_id":oid,"gap_id":gap["gap_id"],"project_ids":gap["project_ids"],
          "need_type":gap["need_type"],"capability_key":gap["capability_key"],"search_concepts":search_concepts_for_gap(gap),"strategy_id":strategy["strategy_id"],
          "exploration":False,
          "strategy_verified_value_outcomes":state["strategy_stats"][strategy["strategy_id"]]["verified_value_outcomes"],
          "strategy_priority_maturity":strategy_priority_maturity(state,strategy["strategy_id"],policy),
          "strategy_selection_basis":(
            "MATURE_VERIFIED_OUTCOME_PRIORITY_THEN_CONFIGURED_ORDER"
            if policy["learning"].get("verified_outcome_strategy_priority") is True
            and strategy_priority_maturity(state,strategy["strategy_id"],policy)["mature"]
            else "WARMUP_CONFIGURED_ORDER"
          ),
          "priority_components":{"importance":gap["importance"],"uncertainty":gap["uncertainty"],"downstream_reuse":gap["downstream_reuse"],"external_validation_value":gap["external_validation_value"],"dead_end_penalty":penalty},
          "queries":queries,
          "acceptance_target":"Retain only an exact public repository revision with structural implementation and test evidence relevant to the portfolio gap; discovery alone does not establish reuse rights or verified capability.",
          "stop_conditions":["Use public GitHub only.","Do not execute discovered code.","Do not inspect or retain secrets/private data.","Do not contact external parties or modify downstream systems.","README or popularity alone is insufficient."],
          "authority_class":"OBSERVE"
        })
    if gaps and explore_slots:
        start=state["exploration_cursor"]%len(gaps)
        for offset in range(min(explore_slots,len(gaps))):
            gap=gaps[(start+offset)%len(gaps)]
            qs=_queries(gap,exploration,state)[:policy["budgets"]["max_queries_per_objective"]]
            core={"gap_id":gap["gap_id"],"strategy_id":exploration["strategy_id"],"project_ids":gap["project_ids"],"capability_key":gap["capability_key"],"exploration":True,"cursor":state["exploration_cursor"]+offset}
            oid="HOBJ-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper()
            objectives.append({
              "schema_version":"1.0.0","objective_id":oid,"gap_id":gap["gap_id"],"project_ids":gap["project_ids"],
              "need_type":"EXPLORATION","capability_key":gap["capability_key"],"search_concepts":search_concepts_for_gap(gap),"strategy_id":exploration["strategy_id"],
              "exploration":True,
              "priority_components":{"importance":gap["importance"],"uncertainty":5,"downstream_reuse":5,"external_validation_value":gap["external_validation_value"],"dead_end_penalty":0},
              "queries":qs,
              "acceptance_target":"Find an unusual exact-revision public implementation pattern that creates a testable new capability hypothesis; novelty without a downstream experiment path is not retained.",
              "stop_conditions":["Preserve the exploration budget.","Use public GitHub only.","Do not execute discovered code.","Do not treat novelty or repository count as value."],
              "authority_class":"OBSERVE"
            })
    return objectives[:maxn]

class GitHubPublicProvider:
    def __init__(self,token=None,policy=None):
        self.token=token; self.policy=policy or load_policy(); self.requests=0
    def _get(self,url):
        b=self.policy["budgets"]; last=None
        for attempt in range(b["retry_limit"]+1):
            if self.requests>=b["max_api_requests_per_cycle"]: raise HunterError("Hunter API request budget exceeded")
            self.requests+=1
            headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-hunter/1.0"}
            if self.token: headers["Authorization"]=f"Bearer {self.token}"
            reqq=urllib.request.Request(url,headers=headers,method="GET")
            try:
                with urllib.request.urlopen(reqq,timeout=20) as resp: return json.loads(resp.read().decode())
            except Exception as exc:
                last=exc
                if attempt<b["retry_limit"]: time.sleep(b["retry_backoff_seconds"]*(attempt+1))
        raise HunterError(f"public GitHub read failed after bounded retries: {last}")
    def search(self,query):
        per=self.policy["budgets"]["max_search_results_per_query"]
        q=urllib.parse.quote(query+" fork:false archived:false")
        data=self._get(f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={per}")
        return [
          x for x in data.get("items",[])
          if x.get("private") is False and int(x.get("size") or 0)>0
        ][:per]
    def repository_metadata(self,full_name):
        data=self._get("https://api.github.com/repos/"+urllib.parse.quote(full_name,safe="/"))
        req(data.get("private") is False,"Hunter controlled candidate must be public")
        return data
    def _candidate_get(self,url):
        try:
            return self._get(url)
        except HunterError as exc:
            message=str(exc)
            if message.startswith("public GitHub read failed after bounded retries:") and re.search(r"HTTP Error (404|409|410|422)\b",message):
                raise CandidateInspectionError(message) from exc
            raise
    def inspect_revision(self,candidate,revision):
        full=candidate["full_name"]
        req(isinstance(revision,str) and len(revision)==40 and all(c in "0123456789abcdef" for c in revision),"candidate exact revision invalid")
        base=f"https://api.github.com/repos/{full}"
        tree=self._candidate_get(base+"/git/trees/"+revision+"?recursive=1")
        paths=[x.get("path") for x in tree.get("tree",[]) if x.get("type")=="blob" and isinstance(x.get("path"),str)]
        maxp=self.policy["budgets"]["max_tree_paths_per_candidate"]
        truncated=bool(tree.get("truncated")) or len(paths)>maxp
        paths=paths[:maxp]
        return {"revision":revision,"tree_sha":tree.get("sha") or revision,"paths":paths,"truncated":truncated}
    def inspect(self,candidate):
        full=candidate["full_name"]; branch=candidate.get("default_branch") or "main"
        base=f"https://api.github.com/repos/{full}"
        commit=self._candidate_get(base+"/commits/"+urllib.parse.quote(branch,safe=""))
        sha=commit["sha"]; req(isinstance(sha,str) and len(sha)==40,"candidate missing exact revision")
        return self.inspect_revision(candidate,sha)

    def rights_evidence(self,candidate,inspection):
        """Fetch only the exact-revision repository license file, when present.

        Raw license text is used transiently for hashing/classification and is not
        persisted by Hunter.
        """
        names={"license","license.md","license.txt","copying","copying.md","copying.txt","unlicense"}
        candidates=[
          p for p in inspection.get("paths",[])
          if Path(p).name.casefold() in names
        ]
        if not candidates:
            return {}
        license_path=sorted(candidates,key=lambda p:(p.count("/"),len(p),p.casefold()))[0]
        full=candidate["full_name"]; revision=inspection["revision"]
        url=(
          f"https://api.github.com/repos/{full}/contents/"
          +urllib.parse.quote(license_path,safe="/")
          +"?ref="+urllib.parse.quote(revision,safe="")
        )
        try:
            data=self._candidate_get(url)
        except CandidateInspectionError:
            return {"license_path":license_path}
        raw=data.get("content")
        if not isinstance(raw,str):
            return {"license_path":license_path}
        if data.get("encoding")=="base64":
            try:
                text=base64.b64decode(raw).decode("utf-8",errors="replace")
            except Exception:
                return {"license_path":license_path}
        else:
            text=raw
        return {"license_path":license_path,"license_text":text}

def structural_inspection(candidate,inspection,objective):
    paths=inspection["paths"]
    lower=[p.casefold() for p in paths]
    code=[p for p in paths if any(p.casefold().endswith(ext) for ext in (".py",".js",".ts",".tsx",".jsx",".go",".rs",".java",".kt",".rb",".cs",".cpp",".c",".h",".lua"))]
    tests=[p for p in paths if any(k in p.casefold() for k in ("test","spec","fixture","regression"))]
    source=[p for p in code if p not in tests]
    docs=[p for p in paths if any(k in p.casefold() for k in ("readme","docs/","doc/"))]
    search_text=" ".join([*objective.get("search_concepts",[]),objective["capability_key"]])
    stop={"business","product","research","infrastructure","coverage","capability","software","architecture","platform","system","framework","engine","testing","tests"}
    tokens=sorted({
      x for x in re.findall(r"[a-z0-9]+",search_text.casefold())
      if len(x)>3 and x not in stop
    })
    def hit_count(items):
        return sum(1 for p in items if any(t in p.casefold() for t in tokens))
    source_hits=hit_count(source)
    test_hits=hit_count(tests)
    docs_hits=hit_count(docs)
    hits=sum(1 for p in lower if any(t in p for t in tokens))
    sample=sorted(dict.fromkeys((source[:10]+tests[:10]+docs[:5])))[:30]
    return {
      "tree_sha":inspection["tree_sha"],
      "tree_truncated":bool(inspection.get("truncated",False)),
      "path_count":len(paths),
      "source_path_count":len(source),
      "test_path_count":len(tests),
      "docs_path_count":len(docs),
      "keyword_hit_count":hits,
      "source_keyword_hit_count":source_hits,
      "test_keyword_hit_count":test_hits,
      "docs_keyword_hit_count":docs_hits,
      "sample_paths":sample,
    }

def candidate_fingerprint(candidate,revision,objective):
    return digest({"source":"PUBLIC_GITHUB","repository_id":candidate["id"],"revision":revision,"capability_key":objective["capability_key"]})

def rank_candidate(structural,policy=None):
    policy=policy or load_policy()
    cfg=policy["candidate_evaluation"]["ranking"]
    w=cfg["weights"]
    components={
      "implementation_presence":w["implementation_presence"] if structural["source_path_count"]>0 else 0,
      "source_capability_signal":w["source_capability_signal"] if structural["source_keyword_hit_count"]>0 else 0,
      "test_presence":w["test_presence"] if structural["test_path_count"]>0 else 0,
      "test_capability_signal":w["test_capability_signal"] if structural["test_keyword_hit_count"]>0 else 0,
      "docs_capability_signal":w["docs_capability_signal"] if structural["docs_keyword_hit_count"]>0 else 0,
    }
    score=sum(components.values())
    req(0<=score<=cfg["max_score"],"Hunter ranking score outside configured bounds")
    bands=cfg["bands"]
    if score>=bands["HIGH"]["min_score"]:
        band="HIGH"
    elif score>=bands["MEDIUM"]["min_score"]:
        band="MEDIUM"
    else:
        band="LOW"
    soft=[]
    if structural["test_path_count"]==0:
        soft.append("NO_TEST_OR_REGRESSION_PATHS")
    if structural["source_keyword_hit_count"]==0:
        soft.append("NO_SOURCE_CAPABILITY_SIGNAL")
    if structural["keyword_hit_count"]==0:
        soft.append("NO_STRUCTURAL_CAPABILITY_SIGNAL")
    elif structural["source_keyword_hit_count"]==0:
        soft.append("CAPABILITY_SIGNAL_ONLY_OUTSIDE_SOURCE")
    if structural["tree_truncated"]:
        soft.append("TRUNCATED_TREE_REQUIRES_DEEPER_VALIDATION")
    return {
      "score":score,
      "max_score":cfg["max_score"],
      "band":band,
      "components":components,
      "soft_signal_codes":soft,
      "value_credit_source":cfg["value_credit_source"],
    }

def proposal_eligible(ranking,policy=None):
    policy=policy or load_policy()
    gate=policy["candidate_evaluation"]["proposal_gate"]
    order={"LOW":0,"MEDIUM":1,"HIGH":2}
    req(gate["minimum_rank_band"] in order,"Hunter proposal minimum rank invalid")
    req(ranking["band"] in order,"Hunter candidate rank band invalid")
    return order[ranking["band"]]>=order[gate["minimum_rank_band"]]

def classify_candidate(state,fp,structural,policy=None):
    policy=policy or load_policy()
    evaluation=policy["candidate_evaluation"]
    ranking=rank_candidate(structural,policy)
    disposition="RETAIN"; negative=None; hard_gate_status="PASS"
    if fp in state["seen_candidate_fingerprints"]:
        disposition="DUPLICATE"; negative=evaluation["terminal_duplicate_reason"]; hard_gate_status="DUPLICATE"
    elif structural["source_path_count"]==0:
        disposition="REJECT"; negative="NO_IMPLEMENTATION_PATHS"; hard_gate_status="REJECT"
    req(negative is None or negative in set(evaluation["hard_reject_reasons"]+[evaluation["terminal_duplicate_reason"]]),"Hunter hard rejection reason is not policy-authorized")
    return disposition,negative,{
      "reason_code":negative or "HARD_GATES_PASSED",
      "hard_gate_status":hard_gate_status,
      "hard_reject_reasons":evaluation["hard_reject_reasons"],
      "implementation_path_gate":structural["source_path_count"]>0,
      "duplicate_gate":fp in state["seen_candidate_fingerprints"],
      "soft_signals_do_not_reject":evaluation["soft_signals_do_not_reject"],
      "ranking":ranking,
    }

def experiment_proposal(finding):
    seed={"finding_id":finding["finding_id"],"candidate_fingerprint":finding["candidate_fingerprint"],"gap_id":finding["gap_id"]}
    hid="HEXP-"+hashlib.sha256(canon(seed).encode()).hexdigest()[:20].upper()
    rights_classification=finding.get("rights",{}).get("rights_classification","NO_LICENSE_NO_REUSE")
    return {
      "schema_version":"1.0.0","proposal_id":hid,"finding_id":finding["finding_id"],"gap_id":finding["gap_id"],
      "project_ids":finding["project_ids"],
      "candidate_rank_score":finding.get("ranking",{}).get("score"),
      "candidate_rank_band":finding.get("ranking",{}).get("band"),
      "candidate_soft_signals":finding.get("ranking",{}).get("soft_signal_codes",[]),
      "hypothesis":"The exact-revision public candidate contains a reusable implementation pattern relevant to the mapped portfolio gap.",
      "baseline":"No verified reusable capability is currently linked to this gap in Portfolio Brain.",
      "success_condition":"Independent exact-revision inspection confirms the implementation behavior, meaningful tests/negative controls, lawful reuse terms, and a bounded integration path.",
      "failure_condition":"The candidate is README-only, lacks meaningful tests, does not satisfy the capability need, has incompatible rights, or creates unsafe authority expansion.",
      "evidence_requirements":["Exact source revision","Implementation-level evidence","Meaningful tests or negative controls","License/rights verification",f"Discovery rights classification: {rights_classification}; no reuse authority is granted by discovery.","Independent verifier receipt"],
      "cost_boundary":"Observation and bounded isolated validation only; no downstream modification.",
      "rollback":"No rollback required because this proposal performs no downstream change."
    }

def _record_negative(state,objective,query,reason,at):
    norm=" ".join(query.casefold().split())
    for item in state["negative_knowledge"]:
        if item["gap_id"]==objective["gap_id"] and item["strategy_id"]==objective["strategy_id"] and item["normalized_query"]==norm and item["reason_code"]==reason:
            item["hits"]+=1; item["last_seen"]=at; return
    state["negative_knowledge"].append({
      "gap_id":objective["gap_id"],"strategy_id":objective["strategy_id"],"normalized_query":norm,
      "query_fingerprint":digest({"strategy":objective["strategy_id"],"query":norm}),
      "reason_code":reason,"hits":1,"first_seen":at,"last_seen":at
    })
    state["negative_knowledge"]=state["negative_knowledge"][-500:]

def _new_rejection_funnel():
    return {
      "raw_search_results":0,
      "normalized_candidates":0,
      "inspection_attempted":0,
      "inspection_succeeded":0,
      "inspection_errors":0,
      "inspection_error_reasons":{},
      "inspection_budget_deferred":0,
      "retained":0,
      "duplicates":0,
      "rejected":0,
      "queries_executed":0,
      "queries_zero_results":0,
      "queries_suppressed":0,
      "rejection_reasons":{},
      "soft_signal_counts":{},
      "ranking_band_counts":{"HIGH":0,"MEDIUM":0,"LOW":0},
      "candidate_accounting_reconciled":True,
      "disposition_accounting_reconciled":True,
    }

def _bump_reason(funnel,reason,count=1):
    funnel["rejection_reasons"][reason]=funnel["rejection_reasons"].get(reason,0)+count

def _record_ranking(funnel,ranking):
    funnel["ranking_band_counts"][ranking["band"]]+=1
    for code in ranking["soft_signal_codes"]:
        funnel["soft_signal_counts"][code]=funnel["soft_signal_counts"].get(code,0)+1

def _finalize_rejection_funnel(funnel):
    funnel["candidate_accounting_reconciled"] = (
        funnel["normalized_candidates"] ==
        funnel["inspection_attempted"] + funnel["inspection_budget_deferred"]
    )
    funnel["disposition_accounting_reconciled"] = (
        funnel["inspection_attempted"] ==
        funnel["retained"] + funnel["duplicates"] + funnel["rejected"] + funnel["inspection_errors"]
    )
    req(
        funnel["inspection_succeeded"] ==
        funnel["retained"] + funnel["duplicates"] + funnel["rejected"],
        "Hunter successful-inspection disposition accounting drift"
    )
    req(funnel["candidate_accounting_reconciled"],"Hunter candidate funnel accounting drift")
    req(funnel["disposition_accounting_reconciled"],"Hunter disposition funnel accounting drift")
    return funnel

def run_cycle(state,provider,*,at=None):
    validate_state(state); policy=load_policy(); at=at or now_iso()
    disabled,reason=killed()
    if disabled:
        funnel=_finalize_rejection_funnel(_new_rejection_funnel())
        return state,{"schema_version":"1.0.0","cycle_id":"disabled","status":"DISABLED","reason":reason,"objectives":[],"findings":[],"experiment_proposals":[],"query_outcomes":[],"rejection_funnel":funnel,"finished_at":at}
    started=time.monotonic(); objectives=select_objectives(state)
    findings=[]; proposals=[]; query_outcomes=[]; total_inspected=0
    funnel=_new_rejection_funnel()
    for obj in objectives:
        stat=state["strategy_stats"][obj["strategy_id"]]; stat["cycles"]+=1
        objective_retained=0
        for query in obj["queries"]:
            query_fp=digest({"strategy_id":obj["strategy_id"],"gap_id":obj["gap_id"],"query":" ".join(query.casefold().split())})
            qout={
              "objective_id":obj["objective_id"],"gap_id":obj["gap_id"],"strategy_id":obj["strategy_id"],
              "query":query,"query_fingerprint":query_fp,"status":"PENDING",
              "raw_results":0,"normalized_candidates":0,"inspection_attempted":0,"inspected":0,
              "inspection_errors":0,"inspection_error_reasons":{},"deferred_due_inspection_budget":0,
              "retained":0,"duplicates":0,"rejected":0,"rejection_reasons":{},
              "ranking_band_counts":{"HIGH":0,"MEDIUM":0,"LOW":0},"soft_signal_counts":{}
            }
            if negative_hits(state,obj["gap_id"],obj["strategy_id"],query)>=policy["learning"]["negative_query_suppression_after"]:
                _record_negative(state,obj,query,"REPEATED_DEAD_END_SUPPRESSED",at)
                qout["status"]="SUPPRESSED_REPEAT_DEAD_END"
                qout["rejection_reasons"]["REPEATED_DEAD_END_SUPPRESSED"]=1
                funnel["queries_suppressed"]+=1
                _bump_reason(funnel,"REPEATED_DEAD_END_SUPPRESSED")
                query_outcomes.append(qout)
                continue
            stat["queries"]+=1; funnel["queries_executed"]+=1
            candidates=provider.search(query)
            qout["status"]="EXECUTED"
            qout["raw_results"]=len(candidates); qout["normalized_candidates"]=len(candidates)
            funnel["raw_search_results"]+=len(candidates); funnel["normalized_candidates"]+=len(candidates)
            stat["candidates"]+=len(candidates)
            if not candidates: funnel["queries_zero_results"]+=1
            retained_this_query=0
            per_query_cap=policy["budgets"]["max_candidates_inspected_per_query"]
            req(type(per_query_cap) is int and per_query_cap>=1,"Hunter per-query inspection cap invalid")
            for idx,cand in enumerate(candidates):
                if qout["inspection_attempted"]>=per_query_cap or total_inspected>=policy["budgets"]["max_candidates_inspected_per_cycle"]:
                    deferred=len(candidates)-idx
                    qout["deferred_due_inspection_budget"]+=deferred
                    funnel["inspection_budget_deferred"]+=deferred
                    break
                req(cand.get("private") is False,"Hunter candidate must be public")
                total_inspected+=1
                qout["inspection_attempted"]+=1
                funnel["inspection_attempted"]+=1
                try:
                    inspection=provider.inspect(cand)
                except CandidateInspectionError:
                    cfg=policy["inspection_failure_handling"]
                    req(cfg["candidate_disposition"]=="UNAVAILABLE_NOT_REJECTED","Hunter inspection failure disposition widened")
                    req(cfg["counts_against_inspection_budget"] is True,"Hunter inspection failures must remain budgeted")
                    req(cfg["records_negative_query_knowledge"] is False,"Hunter inspection failures may not train dead-end knowledge")
                    req(cfg["cycle_behavior"]=="CONTINUE_BOUNDED","Hunter inspection failure cycle behavior widened")
                    reason=cfg["reason_code"]
                    qout["inspection_errors"]+=1
                    qout["inspection_error_reasons"][reason]=qout["inspection_error_reasons"].get(reason,0)+1
                    funnel["inspection_errors"]+=1
                    funnel["inspection_error_reasons"][reason]=funnel["inspection_error_reasons"].get(reason,0)+1
                    continue
                stat["inspected"]+=1
                qout["inspected"]+=1
                funnel["inspection_succeeded"]+=1
                structural=structural_inspection(cand,inspection,obj)
                rights_evidence=provider.rights_evidence(cand,inspection) if callable(getattr(provider,"rights_evidence",None)) else {}
                rights=build_rights_record(cand,inspection,rights_evidence)
                validate_rights_record(rights)
                fp=candidate_fingerprint(cand,inspection["revision"],obj)
                core={"objective_id":obj["objective_id"],"fingerprint":fp}
                fid="HFD-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper()
                disposition,negative,classification_trace=classify_candidate(state,fp,structural,policy)
                ranking=classification_trace["ranking"]
                decision_reason=classification_trace["reason_code"]
                _record_ranking(funnel,ranking)
                qout["ranking_band_counts"][ranking["band"]]+=1
                for code in ranking["soft_signal_codes"]:
                    qout["soft_signal_counts"][code]=qout["soft_signal_counts"].get(code,0)+1
                finding={
                  "schema_version":"1.0.0","finding_id":fid,"objective_id":obj["objective_id"],"gap_id":obj["gap_id"],
                  "project_ids":obj["project_ids"],"strategy_id":obj["strategy_id"],"candidate_fingerprint":fp,
                  "source":{"source_kind":"PUBLIC_GITHUB","repository_full_name":cand["full_name"],"repository_id":cand["id"],"revision":inspection["revision"],"public":True},
                  "inspection":structural,
                  "rights":rights,
                  "capability_hypothesis":f"{cand['full_name']}@{inspection['revision']} may contain a reusable implementation pattern for {obj['capability_key']}; this remains OBSERVED until independent verification.",
                  "evidence_state":"OBSERVED" if disposition=="RETAIN" else "UNKNOWN",
                  "disposition":disposition,
                  "provenance_refs":[f"github:{cand['full_name']}@{inspection['revision']}",f"hunter-objective:{obj['objective_id']}"],
                  "negative_reason":negative,
                  "ranking":ranking,
                  "proposal_eligibility":"ELIGIBLE" if disposition=="RETAIN" and proposal_eligible(ranking,policy) else ("DEFER_LOW_RANK" if disposition=="RETAIN" else "NOT_APPLICABLE"),
                  "decision_trace":{
                    **classification_trace,
                    "public_source_gate":cand.get("private") is False,
                    "exact_revision_gate":isinstance(inspection.get("revision"),str) and len(inspection.get("revision",""))==40,
                    "rights_classification":rights["rights_classification"],
                    "allowed_integration_mode":rights["allowed_integration_mode"],
                    "automatic_reuse_authority_granted":rights["automatic_reuse_authority_granted"],
                  },
                  "experiment_proposal_id":None
                }
                if disposition=="RETAIN":
                    retained_this_query+=1; objective_retained+=1
                    stat["retained"]+=1
                    state["seen_candidate_fingerprints"][fp]={"finding_id":fid,"first_seen":at,"gap_id":obj["gap_id"]}
                    qout["retained"]+=1; funnel["retained"]+=1
                elif disposition=="DUPLICATE":
                    qout["duplicates"]+=1; funnel["duplicates"]+=1
                    qout["rejection_reasons"][negative]=qout["rejection_reasons"].get(negative,0)+1
                    _bump_reason(funnel,negative)
                else:
                    qout["rejected"]+=1; funnel["rejected"]+=1
                    qout["rejection_reasons"][negative]=qout["rejection_reasons"].get(negative,0)+1
                    _bump_reason(funnel,negative)
                findings.append(finding)
            if qout["inspection_errors"]>0:
                qout["status"]="EXECUTED_WITH_INSPECTION_ERRORS"
            if retained_this_query==0 and qout["inspection_errors"]==0:
                _record_negative(state,obj,query,"NO_RETAINED_CANDIDATE",at)
            query_outcomes.append(qout)
        if objective_retained==0:
            pass
    funnel=_finalize_rejection_funnel(funnel)
    proposal_gate=policy["candidate_evaluation"]["proposal_gate"]
    eligible_findings=[
      finding for finding in findings
      if finding["disposition"]=="RETAIN" and proposal_eligible(finding["ranking"],policy)
    ]
    eligible_findings.sort(key=lambda x:(-x["ranking"]["score"],x["finding_id"]))
    selected_findings=eligible_findings[:proposal_gate["max_experiment_proposals_per_cycle"]]
    selected_ids={finding["finding_id"] for finding in selected_findings}
    for finding in eligible_findings:
        if finding["finding_id"] not in selected_ids:
            finding["proposal_eligibility"]="DEFER_CYCLE_PROPOSAL_CAP"
    for finding in selected_findings:
        proposal=experiment_proposal(finding)
        finding["experiment_proposal_id"]=proposal["proposal_id"]
        finding["proposal_eligibility"]="SELECTED"
        proposals.append(proposal)
        state["strategy_stats"][finding["strategy_id"]]["experiment_proposals"]+=1
    proposals.sort(key=lambda x:(-(x.get("candidate_rank_score") or 0),x["proposal_id"]))
    for idx,proposal in enumerate(proposals,start=1):
        proposal["candidate_rank_order"]=idx
    state["sequence"]+=1; state["updated_at"]=at
    state["exploration_cursor"]+=sum(1 for x in objectives if x["exploration"])
    cycle_seed={"sequence_before":state["sequence"]-1,"objectives":[x["objective_id"] for x in objectives],"finding_fingerprints":[x["candidate_fingerprint"] for x in findings]}
    cid="hunt-"+hashlib.sha256(canon(cycle_seed).encode()).hexdigest()[:24]
    receipt={"schema_version":"1.0.0","cycle_id":cid,"status":"PASS","reason":None,"finished_at":at,
             "objectives":objectives,"findings":findings,"experiment_proposals":proposals,
             "query_outcomes":query_outcomes,"rejection_funnel":funnel,
             "proposal_ordering":"QUALITY_GATED_RANK_DESCENDING",
             "proposal_gate":{
               "minimum_rank_band":proposal_gate["minimum_rank_band"],
               "max_experiment_proposals_per_cycle":proposal_gate["max_experiment_proposals_per_cycle"],
               "eligible_findings":len(eligible_findings),
               "selected_proposals":len(proposals),
               "deferred_low_rank":sum(1 for x in findings if x.get("proposal_eligibility")=="DEFER_LOW_RANK"),
               "deferred_cycle_cap":sum(1 for x in findings if x.get("proposal_eligibility")=="DEFER_CYCLE_PROPOSAL_CAP"),
             },
             "api_requests":getattr(provider,"requests",None),"inspected_candidates":total_inspected,
             "objective_function":policy["objective_function"]}
    receipt["receipt_hash"]=digest(receipt)
    state["recent_cycles"]=([*state["recent_cycles"],{
      "cycle_id":cid,"finished_at":at,"receipt_hash":receipt["receipt_hash"],
      "retained":funnel["retained"],"proposals":len(proposals),
      "rejection_funnel":{
        "raw_search_results":funnel["raw_search_results"],
        "normalized_candidates":funnel["normalized_candidates"],
        "inspection_attempted":funnel["inspection_attempted"],
        "inspection_succeeded":funnel["inspection_succeeded"],
        "inspection_errors":funnel["inspection_errors"],
        "inspection_error_reasons":funnel["inspection_error_reasons"],
        "inspection_budget_deferred":funnel["inspection_budget_deferred"],
        "retained":funnel["retained"],"duplicates":funnel["duplicates"],"rejected":funnel["rejected"],
        "queries_executed":funnel["queries_executed"],"queries_zero_results":funnel["queries_zero_results"],
        "queries_suppressed":funnel["queries_suppressed"],
        "rejection_reasons":funnel["rejection_reasons"],
        "soft_signal_counts":funnel["soft_signal_counts"],
        "ranking_band_counts":funnel["ranking_band_counts"],
        "candidate_accounting_reconciled":funnel["candidate_accounting_reconciled"],
        "disposition_accounting_reconciled":funnel["disposition_accounting_reconciled"],
      }
    }])[-20:]
    if time.monotonic()-started>policy["budgets"]["max_runtime_seconds"]: raise HunterError("Hunter runtime budget exceeded")
    validate_state(state)
    return state,receipt

def apply_verified_feedback(state,feedback,*,task_contract,outcome):
    """Credit a controlled proof only after its outcome and source lineage validate.

    The caller must independently verify the provider receipts before calling this
    function; the shared state mutation also enforces the outcome's own contract.
    """
    from value_proof.feedback_loop import validate_value_outcome

    validate_state(state)
    required={"feedback_id","strategy_id","finding_id","outcome_event_id","evidence_state","value_realized"}
    req(isinstance(feedback,dict) and set(feedback)==required,"feedback fields changed")
    validate_value_outcome(outcome)
    source=task_contract["source_candidate"]
    matching=[case for case in load("hunting/CONTROLLED_PROOF_CASES.json")["cases"] if (
        "HFD-CONTROLLED-"+case["case_id"]==source["finding_id"]
        and case["repository_full_name"]==source["repository_full_name"]
        and case["expected_repository_id"]==source["repository_id"]
        and set(case["project_ids"])==set(task_contract["project_ids"])
    )]
    req(len(matching)==1,"controlled Hunter source lineage mismatch")
    req(feedback["finding_id"]==source["finding_id"] and feedback["strategy_id"]==matching[0]["strategy_id"],"feedback finding/strategy lineage mismatch")
    req(outcome["task_id"]==task_contract["task_id"],"feedback task lineage mismatch")
    req(outcome["hunter_finding_id"]==source["finding_id"] and outcome["hunter_experiment_proposal_id"]==source["experiment_proposal_id"],"feedback proposal lineage mismatch")
    req(outcome["repository_full_name"]==source["repository_full_name"] and outcome["revision"]==source["revision"],"feedback revision lineage mismatch")
    req(set(outcome["project_ids"])==set(task_contract["project_ids"]),"feedback project lineage mismatch")
    req(source["capability_key"]==matching[0]["capability_key"],"feedback capability lineage mismatch")
    req(isinstance(outcome["outcome_id"],str) and bool(outcome["outcome_id"].strip()),"feedback outcome identity invalid")
    req(feedback["outcome_event_id"]==outcome["outcome_id"],"feedback outcome lineage mismatch")
    req(feedback["feedback_id"]=="HFB-"+hashlib.sha256(outcome["outcome_id"].encode()).hexdigest()[:24].upper(),"feedback id must be derived from outcome identity")
    req(feedback["evidence_state"]=="VERIFIED","only VERIFIED feedback may train Hunter value")
    req(feedback["strategy_id"] in state["strategy_stats"],"unknown feedback strategy")
    req(feedback["feedback_id"] not in state["feedback_ids"],"duplicate feedback")
    req(feedback["value_realized"] is True,"verified useful outcome must realize technical value")
    state["feedback_ids"].append(feedback["feedback_id"])
    state["strategy_stats"][feedback["strategy_id"]]["verified_value_outcomes"]+=1

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--state",default="hunting/live/hunter_state.json"); ap.add_argument("--output-dir",default="hunting/out")
    args=ap.parse_args(); state_path=Path(args.state); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    state=json.loads(state_path.read_text()) if state_path.exists() else load_seed_state()
    provider=GitHubPublicProvider(os.environ.get("PORTFOLIO_GITHUB_TOKEN"))
    state,receipt=run_cycle(state,provider)
    (out/"hunter_state.json").write_text(json.dumps(state,indent=2)+"\n")
    (out/"hunt_cycle_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    (out/"hunt_objectives.json").write_text(json.dumps(receipt["objectives"],indent=2)+"\n")
    (out/"hunt_findings.json").write_text(json.dumps(receipt["findings"],indent=2)+"\n")
    (out/"hunter_rejection_funnel.json").write_text(json.dumps({
      "cycle_id":receipt["cycle_id"],
      "query_outcomes":receipt.get("query_outcomes",[]),
      "rejection_funnel":receipt.get("rejection_funnel",{}),
    },indent=2)+"\n")
    (out/"experiment_proposals.json").write_text(json.dumps(receipt["experiment_proposals"],indent=2)+"\n")
    from hunting.proposal_state import backlog_summary, build_proposal_state
    prior_proposal_path=Path("hunting/live/hunter_proposal_state.json")
    prior_proposal_state=json.loads(prior_proposal_path.read_text()) if prior_proposal_path.exists() else None
    proposal_state=build_proposal_state(state,receipt,prior_state=prior_proposal_state)
    proposal_summary=backlog_summary(proposal_state)
    (out/"hunter_proposal_state.json").write_text(json.dumps(proposal_state,indent=2,sort_keys=True)+"\n")
    (out/"hunter_proposal_backlog_summary.json").write_text(json.dumps(proposal_summary,indent=2,sort_keys=True)+"\n")
    total=sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    if total>load_policy()["budgets"]["max_output_bytes"]: raise HunterError("Hunter output byte budget exceeded")
    print(json.dumps({
      "cycle_id":receipt["cycle_id"],
      "objectives":len(receipt["objectives"]),
      "findings":len(receipt["findings"]),
      "proposals":len(receipt["experiment_proposals"]),
      "backlog_proposals":proposal_summary["backlog_proposals"],
      "carried_forward_proposals":proposal_summary["carried_forward_proposals"],
      "originated_latest_cycle":proposal_summary["originated_latest_cycle"],
      "distinct_origin_cycles":proposal_summary["distinct_origin_cycles"],
      "status":receipt["status"],
    },sort_keys=True))
if __name__=="__main__": main()
