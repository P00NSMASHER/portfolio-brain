#!/usr/bin/env python3
"""Autonomous portfolio Hunter: gap -> bounded public search -> evidence -> experiment proposal.

Public source content is treated as untrusted data, never as instruction. The v1
executor inspects repository metadata and exact-revision tree structure only; it
does not execute discovered code or copy repository contents.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
class HunterError(RuntimeError): pass

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
        if edge["status"]!="ACTIVE" or edge["edge_type"]!="HAS_CAPABILITY": continue
        source=nodes[edge["source_node_id"]]; target=nodes[edge["target_node_id"]]
        if source["node_type"]=="PROJECT" and target["node_type"]=="CAPABILITY":
            result.setdefault(source["canonical_key"],set()).add(target["canonical_key"])
    return result

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

def _queries(gap,strategy):
    category=" ".join(x.replace("_"," ") for x in gap["categories"][:2]) or gap["project_name"]
    need=gap["capability_key"].replace("capability-coverage:","").replace("-"," ")
    out=[]
    for template in strategy["query_modes"]:
        q=template.format(category=category,need=need)
        if q not in out: out.append(q)
    return out

def select_objectives(state):
    policy=load_policy(); strategies=load_strategies(); gaps=detect_gaps()
    maxn=policy["budgets"]["max_objectives_per_cycle"]
    explore_slots=max(1,round(maxn*policy["budgets"]["exploration_fraction"]))
    exploit_slots=maxn-explore_slots
    exploit_strategies=[s for s in strategies if s["family"]!="EXPLORATION"]
    exploration=next(s for s in strategies if s["family"]=="EXPLORATION")
    objectives=[]
    for idx,gap in enumerate(gaps[:exploit_slots]):
        strategy=exploit_strategies[idx%len(exploit_strategies)]
        queries=_queries(gap,strategy)[:policy["budgets"]["max_queries_per_objective"]]
        penalty=min(5,max((negative_hits(state,gap["gap_id"],strategy["strategy_id"],q) for q in queries),default=0))
        core={"gap_id":gap["gap_id"],"strategy_id":strategy["strategy_id"],"project_ids":gap["project_ids"],"capability_key":gap["capability_key"],"exploration":False}
        oid="HOBJ-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper()
        objectives.append({
          "schema_version":"1.0.0","objective_id":oid,"gap_id":gap["gap_id"],"project_ids":gap["project_ids"],
          "need_type":gap["need_type"],"capability_key":gap["capability_key"],"strategy_id":strategy["strategy_id"],
          "exploration":False,
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
            qs=_queries(gap,exploration)[:policy["budgets"]["max_queries_per_objective"]]
            core={"gap_id":gap["gap_id"],"strategy_id":exploration["strategy_id"],"project_ids":gap["project_ids"],"capability_key":gap["capability_key"],"exploration":True,"cursor":state["exploration_cursor"]+offset}
            oid="HOBJ-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper()
            objectives.append({
              "schema_version":"1.0.0","objective_id":oid,"gap_id":gap["gap_id"],"project_ids":gap["project_ids"],
              "need_type":"EXPLORATION","capability_key":gap["capability_key"],"strategy_id":exploration["strategy_id"],
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
        return [x for x in data.get("items",[]) if x.get("private") is False][:per]
    def inspect(self,candidate):
        full=candidate["full_name"]; branch=candidate.get("default_branch") or "main"
        base=f"https://api.github.com/repos/{full}"
        commit=self._get(base+"/commits/"+urllib.parse.quote(branch,safe=""))
        sha=commit["sha"]; req(isinstance(sha,str) and len(sha)==40,"candidate missing exact revision")
        tree=self._get(base+"/git/trees/"+sha+"?recursive=1")
        paths=[x.get("path") for x in tree.get("tree",[]) if x.get("type")=="blob" and isinstance(x.get("path"),str)]
        maxp=self.policy["budgets"]["max_tree_paths_per_candidate"]
        truncated=bool(tree.get("truncated")) or len(paths)>maxp
        paths=paths[:maxp]
        return {"revision":sha,"tree_sha":tree.get("sha") or sha,"paths":paths,"truncated":truncated}

def structural_inspection(candidate,inspection,objective):
    paths=inspection["paths"]
    lower=[p.casefold() for p in paths]
    source=[p for p in paths if any(p.casefold().endswith(ext) for ext in (".py",".js",".ts",".tsx",".jsx",".go",".rs",".java",".kt",".rb",".cs",".cpp",".c",".h",".lua"))]
    tests=[p for p in paths if any(k in p.casefold() for k in ("test","spec","fixture","regression"))]
    docs=[p for p in paths if any(k in p.casefold() for k in ("readme","docs/","doc/"))]
    tokens=[x for x in re.findall(r"[a-z0-9]+",objective["capability_key"].casefold()) if len(x)>3]
    hits=sum(1 for p in lower if any(t in p for t in tokens))
    sample=sorted(dict.fromkeys((source[:10]+tests[:10]+docs[:5])))[:30]
    return {"tree_sha":inspection["tree_sha"],"path_count":len(paths),"source_path_count":len(source),"test_path_count":len(tests),"docs_path_count":len(docs),"keyword_hit_count":hits,"sample_paths":sample}

def candidate_fingerprint(candidate,revision,objective):
    return digest({"source":"PUBLIC_GITHUB","repository_id":candidate["id"],"revision":revision,"capability_key":objective["capability_key"]})

def experiment_proposal(finding):
    seed={"finding_id":finding["finding_id"],"candidate_fingerprint":finding["candidate_fingerprint"],"gap_id":finding["gap_id"]}
    hid="HEXP-"+hashlib.sha256(canon(seed).encode()).hexdigest()[:20].upper()
    return {
      "schema_version":"1.0.0","proposal_id":hid,"finding_id":finding["finding_id"],"gap_id":finding["gap_id"],
      "project_ids":finding["project_ids"],
      "hypothesis":"The exact-revision public candidate contains a reusable implementation pattern relevant to the mapped portfolio gap.",
      "baseline":"No verified reusable capability is currently linked to this gap in Portfolio Brain.",
      "success_condition":"Independent exact-revision inspection confirms the implementation behavior, meaningful tests/negative controls, lawful reuse terms, and a bounded integration path.",
      "failure_condition":"The candidate is README-only, lacks meaningful tests, does not satisfy the capability need, has incompatible rights, or creates unsafe authority expansion.",
      "evidence_requirements":["Exact source revision","Implementation-level evidence","Meaningful tests or negative controls","License/rights verification","Independent verifier receipt"],
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

def run_cycle(state,provider,*,at=None):
    validate_state(state); policy=load_policy(); at=at or now_iso()
    disabled,reason=killed()
    if disabled:
        return state,{"schema_version":"1.0.0","cycle_id":"disabled","status":"DISABLED","reason":reason,"objectives":[],"findings":[],"experiment_proposals":[],"finished_at":at}
    started=time.monotonic(); objectives=select_objectives(state)
    findings=[]; proposals=[]; total_inspected=0
    for obj in objectives:
        stat=state["strategy_stats"][obj["strategy_id"]]; stat["cycles"]+=1
        objective_retained=0
        for query in obj["queries"]:
            if negative_hits(state,obj["gap_id"],obj["strategy_id"],query)>=policy["learning"]["negative_query_suppression_after"]:
                _record_negative(state,obj,query,"REPEATED_DEAD_END_SUPPRESSED",at); continue
            stat["queries"]+=1
            candidates=provider.search(query); stat["candidates"]+=len(candidates)
            retained_this_query=0
            for cand in candidates:
                if total_inspected>=policy["budgets"]["max_candidates_inspected_per_cycle"]: break
                req(cand.get("private") is False,"Hunter candidate must be public")
                inspection=provider.inspect(cand); total_inspected+=1; stat["inspected"]+=1
                structural=structural_inspection(cand,inspection,obj)
                fp=candidate_fingerprint(cand,inspection["revision"],obj)
                core={"objective_id":obj["objective_id"],"fingerprint":fp}
                fid="HFD-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper()
                disposition="RETAIN"; negative=None
                if fp in state["seen_candidate_fingerprints"]:
                    disposition="DUPLICATE"; negative="EXACT_REVISION_CAPABILITY_DUPLICATE"
                elif structural["source_path_count"]==0:
                    disposition="REJECT"; negative="NO_IMPLEMENTATION_PATHS"
                elif structural["test_path_count"]==0:
                    disposition="REJECT"; negative="NO_TEST_OR_REGRESSION_PATHS"
                elif structural["keyword_hit_count"]==0:
                    disposition="REJECT"; negative="NO_STRUCTURAL_CAPABILITY_SIGNAL"
                finding={
                  "schema_version":"1.0.0","finding_id":fid,"objective_id":obj["objective_id"],"gap_id":obj["gap_id"],
                  "project_ids":obj["project_ids"],"strategy_id":obj["strategy_id"],"candidate_fingerprint":fp,
                  "source":{"source_kind":"PUBLIC_GITHUB","repository_full_name":cand["full_name"],"repository_id":cand["id"],"revision":inspection["revision"],"public":True},
                  "inspection":structural,
                  "capability_hypothesis":f"{cand['full_name']}@{inspection['revision']} may contain a reusable implementation pattern for {obj['capability_key']}; this remains OBSERVED until independent verification.",
                  "evidence_state":"OBSERVED" if disposition=="RETAIN" else "UNKNOWN",
                  "disposition":disposition,
                  "provenance_refs":[f"github:{cand['full_name']}@{inspection['revision']}",f"hunter-objective:{obj['objective_id']}"],
                  "negative_reason":negative,"experiment_proposal_id":None
                }
                if disposition=="RETAIN":
                    proposal=experiment_proposal(finding); finding["experiment_proposal_id"]=proposal["proposal_id"]
                    proposals.append(proposal); retained_this_query+=1; objective_retained+=1
                    stat["retained"]+=1; stat["experiment_proposals"]+=1
                    state["seen_candidate_fingerprints"][fp]={"finding_id":fid,"first_seen":at,"gap_id":obj["gap_id"]}
                findings.append(finding)
            if retained_this_query==0: _record_negative(state,obj,query,"NO_RETAINED_CANDIDATE",at)
        if objective_retained==0:
            pass
    state["sequence"]+=1; state["updated_at"]=at
    state["exploration_cursor"]+=sum(1 for x in objectives if x["exploration"])
    cycle_seed={"sequence_before":state["sequence"]-1,"objectives":[x["objective_id"] for x in objectives],"finding_fingerprints":[x["candidate_fingerprint"] for x in findings]}
    cid="hunt-"+hashlib.sha256(canon(cycle_seed).encode()).hexdigest()[:24]
    receipt={"schema_version":"1.0.0","cycle_id":cid,"status":"PASS","reason":None,"finished_at":at,
             "objectives":objectives,"findings":findings,"experiment_proposals":proposals,
             "api_requests":getattr(provider,"requests",None),"inspected_candidates":total_inspected,
             "objective_function":policy["objective_function"]}
    receipt["receipt_hash"]=digest(receipt)
    state["recent_cycles"]=([*state["recent_cycles"],{"cycle_id":cid,"finished_at":at,"receipt_hash":receipt["receipt_hash"],"retained":sum(1 for x in findings if x["disposition"]=="RETAIN"),"proposals":len(proposals)}])[-20:]
    if time.monotonic()-started>policy["budgets"]["max_runtime_seconds"]: raise HunterError("Hunter runtime budget exceeded")
    validate_state(state)
    return state,receipt

def apply_verified_feedback(state,feedback):
    validate_state(state)
    required={"feedback_id","strategy_id","finding_id","outcome_event_id","evidence_state","value_realized"}
    req(isinstance(feedback,dict) and set(feedback)==required,"feedback fields changed")
    req(feedback["evidence_state"]=="VERIFIED","only VERIFIED feedback may train Hunter value")
    req(feedback["strategy_id"] in state["strategy_stats"],"unknown feedback strategy")
    req(feedback["feedback_id"] not in state["feedback_ids"],"duplicate feedback")
    req(isinstance(feedback["value_realized"],bool),"value_realized must be boolean")
    state["feedback_ids"].append(feedback["feedback_id"])
    if feedback["value_realized"]: state["strategy_stats"][feedback["strategy_id"]]["verified_value_outcomes"]+=1

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
    (out/"experiment_proposals.json").write_text(json.dumps(receipt["experiment_proposals"],indent=2)+"\n")
    total=sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    if total>load_policy()["budgets"]["max_output_bytes"]: raise HunterError("Hunter output byte budget exceeded")
    print(json.dumps({"cycle_id":receipt["cycle_id"],"objectives":len(receipt["objectives"]),"findings":len(receipt["findings"]),"proposals":len(receipt["experiment_proposals"]),"status":receipt["status"]}))
if __name__=="__main__": main()
