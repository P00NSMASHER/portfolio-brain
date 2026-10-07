"""Noninteractive CLI. Runtime needs Python stdlib and authorized GitHub reads only."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
from pathlib import Path
from brain.core import Store, BrainError, require, utcnow, digest, timestamp
from brain.adapters import GitHub, event, policy
from brain.experiments import invoice_dedup_experiment
from brain.render import write_report

ROOT=Path(__file__).resolve().parents[1]

def source_sha(expected=None):
    sha=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    require(expected is None or sha==expected, "EXACT_SHA_MISMATCH")
    # Include tracked + untracked active source; no dirty code gets exact-SHA credit.
    dirty=subprocess.check_output(["git","status","--porcelain","--","brain","examples","tests/test_brain*",".github/workflows/brain-cycle.yml"],cwd=ROOT,text=True)
    require(not dirty.strip(), "DIRTY_SOURCE: commit reviewed source before exact-SHA evidence")
    return sha

def persist(store, items, sha, output):
    if items:
        store.submit(items)
    store.drain()
    result=store.report(sha)
    write_report(result,output)
    return result

def monitor(store, sha, output, *, api=None, repositories=None):
    api=api or GitHub(private=store.visibility=="PRIVATE")
    repositories=repositories or policy()["repositories"]
    require(0<len(repositories)<=4, "monitor repository bound exceeded")
    errors=[]
    for repo in repositories:
        try:
            payload,private=api.observe(repo)
            store.submit([event("repository",repo,payload,sha,private=private)])
            store.drain()
        except (BrainError,KeyError,UnicodeError,TypeError) as exc:
            errors.append({"repository":repo,"error_class":type(exc).__name__,"error":str(exc)[:300]})
    report=store.report(sha)
    report["operation"]={"name":"monitor","requests":api.requests,"required_repositories":repositories,"errors":errors}
    if errors:
        report["status"]="FAIL"
    write_report(report,output)
    store.attempt("monitor","FAIL" if errors else "PASS", "SOURCE_FAILURE" if errors else None,source_sha=sha,details={"repositories":repositories})
    require(not errors, "MONITOR_INCOMPLETE: see sanitized operation errors; useful observations retained")
    return report

def research(store, sha, output, *, api=None, repository=None):
    api=api or GitHub(private=store.visibility=="PRIVATE")
    targets=policy()["research_targets"]
    # Fair rotation persists in analytical history, rather than a second scheduler.
    previous=store.db.execute("SELECT count(*) FROM attempts WHERE operation='research' AND status='PASS'").fetchone()[0]
    target=dict(targets[previous%len(targets)])
    # Protected knowledge upgrades improve retrieval using measured source terms;
    # inspected facts remain in SQLite, not inferred from the shipped knowledge file.
    knowledge=json.loads((ROOT/'brain/REUSE_KNOWLEDGE.json').read_text())
    support={}
    for item in knowledge['sources']:
        if item['target']==target['project']:
            for term in item['matched_terms']:
                if term in target['terms']:
                    support[term]=support.get(term,0)+1
    if support:
        strongest=sorted(support,key=lambda term:(-support[term],term))[0]
        if strongest not in target['query'].lower():
            target['query']+=' '+strongest
    found=api.discover(target,repository=repository)
    items=[event("candidate",p["repository"]+":"+p["path"],p,sha,private=private) for p,private in found]
    report=persist(store,items,sha,output)
    report["operation"]={"name":"research","requests":api.requests,"target":target["project"],"candidates_observed":len(items),"result":"OBSERVED" if items else "NO_MATCHES","license_filter_applied":False}
    write_report(report,output)
    store.attempt("research","PASS",source_sha=sha)
    return report

def experiment(store, sha, output):
    payload=invoice_dedup_experiment(1000)
    item=event("experiment",payload["experiment"],payload,sha,data_kind="SIMULATED")
    report=persist(store,[item],sha,output)
    store.attempt("experiment","PASS",source_sha=sha)
    return report

def doctor(store, sha, output):
    report=store.read_report(sha)
    last={}
    for row in store.db.execute("SELECT * FROM attempts ORDER BY id"):
        fresh=0<=(timestamp(utcnow())-timestamp(row["created_at"])).total_seconds()<=7200
        last[row["operation"]]=row if row["source_sha"]==sha and fresh else None
    mandatory={name:last[name]['status'] if last.get(name) is not None else "MISSING_OR_STALE" for name in ("monitor","research","experiment")}
    monitor_attempt=last.get('monitor')
    require(monitor_attempt is not None and set(json.loads(monitor_attempt['details']).get('repositories',[]))==set(policy()['repositories']), 'OPERATIONAL_DOCTOR_FAIL: current monitor did not cover full configured scope')
    require(all(last.get(name) is not None and last[name]['id']>monitor_attempt['id'] for name in ('research','experiment')), 'OPERATIONAL_DOCTOR_FAIL: current monitor needs its own research/experiment continuation')
    require(all(x=="PASS" for x in mandatory.values()), "OPERATIONAL_DOCTOR_FAIL: mandatory current workloads missing/failed")
    required=set(policy()["repositories"])
    observed={x["repository"] for x in report["repositories"]}
    require(required<=observed, "OPERATIONAL_DOCTOR_FAIL: required source coverage missing")
    result={"schema_version":2,"status":"PASS","scope":"INDEPENDENT_V2_STATE_ONLY","source_sha":sha,"state_sequence":report["state_sequence"],"canonical_hash":report["canonical_hash"],"pending_events":store.pending(),"verified_canonical_state":True,"mandatory_workloads":mandatory,"workflow_delivery":"NOT_TESTED_BY_LOCAL_DOCTOR","legacy_orphan_status":"EXTERNAL_RECORD_UNRESOLVED_NOT_READ_BY_V2","soak_started":False,"production_accepted":False,"checked_at":utcnow()}
    write_report(result,output)
    return result

def preflight(output, expected=None):
    sha=source_sha(expected)
    from brain.validate import validate_policy
    validate_policy()
    test=subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-p","test_brain*.py","-v"],cwd=ROOT,capture_output=True,text=True,timeout=60)
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    (out/"tests.txt").write_text(test.stdout+test.stderr)
    require(test.returncode==0, "PREFLIGHT_TEST_FAILURE: inspect tests.txt before retry")
    require("Ran 0 tests" not in test.stderr and "\nOK\n" in test.stderr,"PREFLIGHT_TEST_EVIDENCE_MISSING")
    # Preflight is a deterministic product test, never a substitute for live delivery/soak.
    result={"schema_version":2,"phase":"EXACT_SHA_PREFLIGHT","status":"PASS","source_sha":sha,"mandatory_workloads":{"state_integrity":"PASS","replay":"PASS","adversarial_regressions":"PASS","code_retrieval":"PASS","experiment_correctness":"PASS","reporting":"PASS"},"live_sources":"NOT_TESTED","workflow_delivery":"NOT_TESTED","soak_started":False,"production_accepted":False,"checked_at":utcnow()}
    write_report(result,output)
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(description="Read-only autonomous business portfolio intelligence")
    parser.add_argument("command",choices=["init","ingest","cycle","monitor","research","experiment","doctor","preflight","backup","service","feedback","evolve"])
    parser.add_argument("--db",default="brain-local/state.sqlite")
    parser.add_argument("--output",default="brain-local/report")
    parser.add_argument("--input")
    parser.add_argument("--expected-sha")
    parser.add_argument("--private",action="store_true",help="Explicit private local state; existing token required for GitHub reads; never publish this database")
    parser.add_argument("--repository",action="append",help="Authorized existing repository; max4 monitoring,1 research")
    parser.add_argument("--interval",type=int,default=3600)
    parser.add_argument("--cycles",type=int,default=0,help="0 means service continues until stop file/signal")
    args=parser.parse_args(argv)
    store=None
    try:
        if args.command=="preflight":
            result=preflight(args.output,args.expected_sha)
        else:
            sha=source_sha(args.expected_sha)
            store=Store(args.db,visibility="PRIVATE" if args.private else "PUBLIC")
            store.drain()
            if args.command=="init":
                result={"status":"PASS","scope":"EMPTY_STATE_BOOTSTRAP_NOT_OPERATIONAL","pending_events":store.pending(),"source_sha":sha}
                write_report(result,args.output)
            elif args.command in {"ingest","cycle","feedback"}:
                require(args.input is not None, "--input required")
                require(Path(args.input).stat().st_size<=2_000_000,"input too large")
                items=json.loads(Path(args.input).read_text())
                require(type(items) is list,"input must be explicit event list")
                result=persist(store,items,sha,args.output)
            elif args.command=="monitor":
                result=monitor(store,sha,args.output,repositories=args.repository)
            elif args.command=="research":
                require(args.repository is None or len(args.repository)==1,"research accepts one authorized repository")
                result=research(store,sha,args.output,repository=args.repository[0] if args.repository else None)
            elif args.command=="experiment":
                result=experiment(store,sha,args.output)
            elif args.command=="evolve":
                from brain.upgrades import evolve
                try:
                    result=evolve(store,sha)
                except (BrainError,urllib.error.HTTPError,OSError,KeyError,TypeError) as exc:
                    store.attempt('evolve','FAIL',type(exc).__name__,source_sha=sha)
                    result={'status':'BLOCKED','operation':'evolve','error_class':type(exc).__name__,'source_sha':sha,'independent_review':'NOT_STARTED','authority_widened':False}
                write_report(result,args.output)
            elif args.command=="doctor":
                result=doctor(store,sha,args.output)
            elif args.command=="backup":
                result={"status":"PASS","backup_sha256":store.backup(args.output),"source_sha":sha}
            else:
                require(900<=args.interval<=86400 and args.cycles>=0,"service interval/cycles invalid")
                count=0
                while not (Path(args.db).parent/"STOP").exists():
                    source_sha(sha)
                    for name,fn in (("monitor",monitor),("research",research),("experiment",experiment),("doctor",doctor)):
                        try:
                            store.drain()
                            fn(store,sha,Path(args.output)/name)
                        except (BrainError,KeyError,TypeError,UnicodeError) as exc:
                            store.attempt(name,"FAIL",type(exc).__name__,source_sha=sha)
                            write_report({"status":"FAIL","operation":name,"error_class":type(exc).__name__,"source_sha":sha},Path(args.output)/name)
                    from brain.upgrades import evolve
                    try:
                        upgrade=evolve(store,sha)
                        write_report(upgrade,Path(args.output)/'upgrade')
                    except (BrainError,urllib.error.HTTPError,OSError,KeyError,TypeError) as exc:
                        store.attempt('evolve','FAIL',type(exc).__name__,source_sha=sha)
                        write_report({'status':'BLOCKED','operation':'evolve','error_class':type(exc).__name__},Path(args.output)/'upgrade')
                    count+=1
                    if args.cycles and count>=args.cycles: break
                    # Interruptible process. Hosting/restart is the operator's existing service manager.
                    for _ in range(args.interval):
                        if (Path(args.db).parent/"STOP").exists(): break
                        time.sleep(1)
                result={"status":"STOPPED","cycles":count,"source_sha":sha,"soak_completed":False}
        print(json.dumps({k:result[k] for k in ("status","source_sha","pending_events","state_sequence","phase") if k in result},sort_keys=True))
        return 0
    except (BrainError,KeyError,TypeError,UnicodeError,json.JSONDecodeError) as exc:
        if store:
            store.attempt(args.command,"FAIL",type(exc).__name__,source_sha=locals().get("sha"))
        write_report({"status":"FAIL","error_class":type(exc).__name__,"error":str(exc)[:500],"operation":args.command,"soak_completed":False},Path(args.output)/"failure")
        print(f'{type(exc).__name__}: {str(exc)[:500]}',file=sys.stderr)
        return 1
    finally:
        if store: store.close()

if __name__=="__main__":
    raise SystemExit(main())
