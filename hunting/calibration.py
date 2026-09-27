#!/usr/bin/env python3
"""Deterministic Hunter calibration corpus runner.

This module exercises the same structural classifier used by live Hunter cycles
against checked-in synthetic repository trees. It performs no network calls,
grants no reuse rights, and does not mutate Hunter continuation state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import (
    candidate_fingerprint,
    classify_candidate,
    digest,
    load_seed_state,
    structural_inspection,
)

ROOT=Path(__file__).resolve().parents[1]
CORPUS_PATH=ROOT/"hunting"/"CALIBRATION_CORPUS.json"

class CalibrationError(ValueError):
    pass

def req(ok: bool,msg: str) -> None:
    if not ok:
        raise CalibrationError(msg)

def load_corpus(path: Path=CORPUS_PATH) -> dict[str,Any]:
    doc=json.loads(path.read_text(encoding="utf-8"))
    req(set(doc)=={"schema_version","corpus_id","purpose","cases"},"calibration corpus top-level fields changed")
    req(doc["schema_version"]=="1.0.0","calibration corpus schema mismatch")
    req(doc["corpus_id"]=="portfolio-hunter-calibration-v1","calibration corpus identity mismatch")
    req(isinstance(doc["cases"],list),"calibration cases must be a list")
    ids=[x.get("case_id") for x in doc["cases"]]
    req(all(isinstance(x,str) and x for x in ids),"calibration case id missing")
    req(len(ids)==len(set(ids)),"duplicate calibration case id")
    classes={"POSITIVE":0,"NEGATIVE":0,"AMBIGUOUS":0}
    for case in doc["cases"]:
        req(case.get("case_class") in classes,f"invalid calibration class: {case.get('case_class')}")
        classes[case["case_class"]]+=1
        req(isinstance(case.get("capability_key"),str) and case["capability_key"].startswith("capability-coverage:"),"invalid capability key")
        req(isinstance(case.get("paths"),list) and all(isinstance(x,str) and x for x in case["paths"]),"invalid calibration paths")
        if case["case_class"]=="AMBIGUOUS":
            req(isinstance(case.get("allowed_dispositions"),list) and case["allowed_dispositions"],"ambiguous case needs allowed dispositions")
            req(isinstance(case.get("ambiguity"),str) and case["ambiguity"],"ambiguous case needs rationale")
        else:
            req(case.get("expected_disposition") in {"RETAIN","REJECT"},"gold case expected disposition invalid")
        req(isinstance(case.get("expected_reason"),str) and case["expected_reason"],"expected reason missing")
    req(classes["POSITIVE"]>=10,"calibration corpus needs at least 10 positive controls")
    req(classes["NEGATIVE"]>=10,"calibration corpus needs at least 10 negative controls")
    req(classes["AMBIGUOUS"]>=3,"calibration corpus needs at least 3 ambiguous controls")
    return doc

def _revision(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]

def evaluate_case(case: dict[str,Any],index: int) -> dict[str,Any]:
    candidate={
      "id":10000+index,
      "full_name":f"calibration/{case['case_id'].lower()}",
      "default_branch":"main",
      "private":False,
    }
    objective={"capability_key":case["capability_key"]}
    inspection={
      "revision":_revision("revision:"+case["case_id"]),
      "tree_sha":_revision("tree:"+case["case_id"]),
      "paths":list(case["paths"]),
      "truncated":False,
    }
    structural=structural_inspection(candidate,inspection,objective)
    fp=candidate_fingerprint(candidate,inspection["revision"],objective)
    state=load_seed_state()
    if case.get("duplicate") is True:
        state["seen_candidate_fingerprints"][fp]={
          "finding_id":"HFD-CALIBRATION",
          "first_seen":"2026-01-01T00:00:00Z",
          "gap_id":"HGAP-CALIBRATION",
        }
    disposition,reason,trace=classify_candidate(state,fp,structural)
    reason=reason or "STRUCTURAL_GATES_PASSED"
    allowed=case.get("allowed_dispositions") or [case["expected_disposition"]]
    disposition_match=disposition in allowed
    reason_match=reason==case["expected_reason"]
    return {
      "case_id":case["case_id"],
      "case_class":case["case_class"],
      "allowed_dispositions":allowed,
      "expected_reason":case["expected_reason"],
      "actual_disposition":disposition,
      "actual_reason":reason,
      "disposition_match":disposition_match,
      "reason_match":reason_match,
      "passed":bool(disposition_match and reason_match),
      "structural":structural,
      "decision_trace":trace,
      "ambiguity":case.get("ambiguity"),
    }

def run_calibration(corpus: dict[str,Any] | None=None) -> dict[str,Any]:
    corpus=corpus or load_corpus()
    results=[evaluate_case(case,i) for i,case in enumerate(corpus["cases"])]
    positives=[x for x in results if x["case_class"]=="POSITIVE"]
    negatives=[x for x in results if x["case_class"]=="NEGATIVE"]
    ambiguous=[x for x in results if x["case_class"]=="AMBIGUOUS"]
    positive_retained=sum(x["actual_disposition"]=="RETAIN" for x in positives)
    negative_rejected=sum(x["actual_disposition"]=="REJECT" for x in negatives)
    ambiguous_matched=sum(x["passed"] for x in ambiguous)
    failed=[x["case_id"] for x in results if not x["passed"]]
    status="PASS" if (
        positive_retained==len(positives)
        and negative_rejected==len(negatives)
        and ambiguous_matched==len(ambiguous)
        and not failed
    ) else "FAIL"
    report={
      "schema_version":"1.0.0",
      "calibration_id":"portfolio-hunter-calibration-run-v1",
      "corpus_id":corpus["corpus_id"],
      "corpus_hash":digest(corpus),
      "authority_class":"OBSERVE",
      "network_calls":0,
      "state_mutations":0,
      "status":status,
      "case_count":len(results),
      "positive_cases":len(positives),
      "positive_retained":positive_retained,
      "negative_cases":len(negatives),
      "negative_rejected":negative_rejected,
      "ambiguous_cases":len(ambiguous),
      "ambiguous_matched":ambiguous_matched,
      "failed_case_ids":failed,
      "results":results,
    }
    report["report_hash"]=digest(report)
    return report

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    report=run_calibration()
    if args.output is not None:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
      "status":report["status"],
      "cases":report["case_count"],
      "positive_retained":f"{report['positive_retained']}/{report['positive_cases']}",
      "negative_rejected":f"{report['negative_rejected']}/{report['negative_cases']}",
      "ambiguous_matched":f"{report['ambiguous_matched']}/{report['ambiguous_cases']}",
      "report_hash":report["report_hash"],
    },sort_keys=True))
    if report["status"]!="PASS":
        raise SystemExit(1)

if __name__=="__main__":
    main()
