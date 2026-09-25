#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile
from pathlib import Path
from software_factory.software_factory import SoftwareFactory,identify_work
ROOT=Path(__file__).resolve().parents[1]
class FactoryValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise FactoryValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())
def validate_factory():
    pin=load("software_factory/AI_BUSINESS_OS_SOFTWARE_FACTORY_PIN.json");p=load("software_factory/FACTORY_POLICY.json");ledger=load("software_factory/SOFTWARE_FACTORY_LEDGER.json")
    req(pin["source_revision"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","factory source revision mismatch")
    blobs={"governed_factory":"70baa5a71ea568c3041664fa397e4c09c9c9511f","factory_contract":"b71a6c7b6efd907e900bbbe80e6c250939be24bf","factory_tests":"a3d020a42c4f54587811430c6671543528f112c3","verification":"556b809feb98554c05c158c93a0b9d98ef2919e1","verification_tests":"3b194771fe0b72a21fecf934e57d8f6cfefbe0d2","governance":"40d278e479830d6f76aca7da22b6893f5d0060a7","governance_tests":"3a1429ec8d81e92d1043e89c55a7868b226a6fd4"}
    for k,v in blobs.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(pin["copied_source_code"] is False,"canonical software factory copied")
    req(p["mode"]=="ISOLATED_BRANCH_PR_ONLY","factory mode changed");req(set(p["executor_operations"])=={"CREATE_BRANCH","COMMIT_CANDIDATE","CREATE_PR"},"executor operations changed")
    req({"MERGE_PR","DEPLOY","UPDATE_DEFAULT_BRANCH","CHANGE_SECRETS"}<=set(p["absent_operations"]),"forbidden executor operations missing")
    enabled=[r for r in p["repository_policies"] if r["candidate_modify_enabled"]];req(len(enabled)==1 and enabled[0]["repository_id"]=="REPO-008","downstream candidate writes unexpectedly enabled")
    req(all(not r["candidate_modify_enabled"] for r in p["repository_policies"] if r["repository_id"]!="REPO-008"),"downstream write boundary weakened")
    req(p["allowed_builder_agent_ids"]==["AGT-ENGINEER"],"builder role widened");req(set(p["allowed_verifier_agent_ids"])=={"AGT-TESTER","AGT-AUDITOR","AGT-RED-TEAM"},"factory verifier set changed")
    req(ledger["work_items"]==[],"checked-in factory ledger fabricated work")
    alloc=__import__("allocator.portfolio_allocator",fromlist=["build_allocation_snapshot"]).build_allocation_snapshot()
    exps=__import__("experiments.experiment_engine",fromlist=["build_experiment_portfolio"]).build_experiment_portfolio(__import__("uncertainty.highest_value_uncertainty",fromlist=["build_snapshot"]).build_snapshot())
    req(identify_work(alloc,exps)==[],"current HOLD engineering allocation should produce no factory work")
    with tempfile.TemporaryDirectory() as td:
        sf=SoftwareFactory(Path(td)/"factory.sqlite3");req(sf.event_chain_valid(),"fresh factory event chain invalid");sf.close()
    workflow=(ROOT/".github/workflows/software-factory-candidate.yml").read_text().lower()
    req("contents: write" in workflow and "pull-requests: write" in workflow,"candidate executor permissions missing")
    for forbidden in ["deployments: write","id-token: write","packages: write","actions: write"]:
        req(forbidden not in workflow,f"forbidden factory workflow permission: {forbidden}")
    req("merge" not in (ROOT/"software_factory/github_executor.py").read_text().lower(),"GitHub executor contains merge surface")
    return {"executor_operations":3,"candidate_write_repositories":1,"downstream_write_repositories":0,"seed_work_items":0,"identified_current_work":0}
if __name__=="__main__":print("portfolio-brain Step 16 factory: PASS",json.dumps(validate_factory(),sort_keys=True))
