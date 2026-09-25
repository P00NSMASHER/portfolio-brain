#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os
from pathlib import Path

TITLES={
"COST_HARD_STOP":"Portfolio cost hard stop",
"HUMAN_APPROVAL_QUEUE":"Human approval queue needs review",
"OPEN_HUMAN_BLOCKERS":"Open governance decisions need review",
"AUTONOMOUS_WORK_FAILURE":"Autonomous work failure requires review",
"VERIFIED_NEGATIVE_OUTCOME":"Verified negative outcome",
"VERIFIED_POSITIVE_OUTCOME":"Verified positive outcome",
"PORTFOLIO_STATE_CHANGED":"Portfolio decision state changed",
}
def _message(a):
    projects=",".join(a.get("project_ids") or ["PORTFOLIO"])
    entities=",".join(a.get("entity_refs",[])[:8])
    return f"severity={a['severity']} projects={projects} entities={entities} evidence_refs={len(a.get('evidence_refs',[]))}"
def emit(alerts):
    summary=["# Portfolio Brain alerts",""]
    for a in alerts:
        title=TITLES.get(a["kind"],a["kind"]);msg=_message(a)
        level="error" if a["severity"]=="CRITICAL" else "warning" if a["severity"]=="HIGH" else "notice"
        print(f"::{level} title={title}::{msg}")
        summary.append(f"- **{a['severity']} — {title}** — {msg}")
    if not alerts:summary.append("- No alerts emitted this cycle.")
    path=os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path,"a",encoding="utf-8") as h:h.write("\n".join(summary)+"\n")
    return len(alerts)
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--alerts",required=True);a=ap.parse_args();alerts=json.loads(Path(a.alerts).read_text());print(json.dumps({"emitted":emit(alerts)}))
if __name__=="__main__":main()
