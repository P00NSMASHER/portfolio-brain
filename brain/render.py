import html
import json
import os
from pathlib import Path

def write_report(report, output):
    out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    os.chmod(out,0o700)
    raw=json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)
    (out/"report.json").write_text(raw+"\n")
    lines=["# Portfolio Brain", "", f'Status: {report.get("status", "UNKNOWN")}', "", f'Source: {report.get("source_sha", "UNAVAILABLE")}', "", "Read-only research. Structural code evidence is not proof of production usefulness or revenue.", ""]
    for repo in report.get("repositories",[]):
        failed=[x["name"] for x in repo["checks"] if x["conclusion"] not in {"success","neutral",None}]
        lines.append(f'- {repo["repository"]}: `{repo["head_sha"]}`; adverse checks: {", ".join(failed) or "none observed"}; [{repo["source_ref"]}]({repo["source_ref"]})')
    lines.extend(["", "## Reusable code to evaluate", ""])
    for candidate in report.get("reuse_candidates",[])[:10]:
        lines.append(f'- [{candidate["repository"]}/{candidate["path"]}]({candidate["source_ref"]}) — {candidate["target"]}; structural score {candidate["reuse_score"]}; license {candidate["license"]}; {candidate["utility_evidence"]}')
    lines.extend(["", "## Business opportunities", ""])
    for opportunity in report.get("business_opportunities",[]):
        lines.append(f'- {opportunity["target"]}: {opportunity["hypothesis"]} Customer demand {opportunity["customer_demand"]}; revenue {opportunity["revenue"]}.')
    lines.extend(["", "## Experiments", ""])
    for exp in report.get("learning",{}).get("experiments",[]):
        lines.append(f'- {exp["experiment"]}: {exp["dataset_kind"]}, {exp["cases"]} cases, equal outputs, {exp["baseline_operations"]} → {exp["candidate_operations"]} defined operations. {exp["scope"]}')
    (out/"report.md").write_text("\n".join(lines)+"\n")
    (out/"report.html").write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Portfolio Brain</title><style>body{font:16px system-ui;max-width:960px;margin:32px auto;padding:16px;color:#16304b;background:#f3f7fb}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:24px;border-radius:16px}</style><pre>'+html.escape("\n".join(lines))+'</pre>')
    for file in out.iterdir():
        if file.is_file(): os.chmod(file,0o600)
