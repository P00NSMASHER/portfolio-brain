"""Active runtime contract. Legacy validators are offline historical regressions."""
import hashlib
import json
from pathlib import Path
from brain.core import require
from brain.adapters import policy

ROOT=Path(__file__).resolve().parents[1]

def validate_policy():
    p=policy()
    require(p["schema_version"]==2 and p["active_runtime"]=="brain", "active runtime/schema changed")
    require(p["state_branch"]=="brain-state-v2" and p["cron"]=="7,27,47 * * * *" and p["watchdog_cron"]=="16,36,56 * * * *", "state namespace/schedule invalid")
    require(p["paid_calls"]==0 and p["max_requests_per_operation"]==24 and p["request_timeout_seconds"]==10 and p["max_transient_retries"]==1, "cost/timeout/retry contract changed")
    require(p["max_source_age_seconds"]==172800, "freshness contract changed")
    for name in ("downstream_write_authority","trading_authority","external_message_authority","discovered_code_execution","license_discovery_filter","public_state_accepts_private_inputs"):
        require(p[name] is False, "forbidden authority/filter: "+name)
    workflow_dir=ROOT/".github/workflows"
    expected={"foundation-ci.yml","portfolio-independent-verifier.yml","x402-gateway-ci.yml","x402-render-gateway-smoke.yml","brain-cycle.yml","brain-clock.yml"}
    require({x.name for x in workflow_dir.iterdir() if x.suffix in {".yml",".yaml"}}==expected, "active workflow inventory changed")
    from operations.validate_operating_mode import scheduled_workflow_inventory
    require(scheduled_workflow_inventory(workflow_dir)=={"brain-cycle":[p["cron"]], "brain-clock":[p["watchdog_cron"]]}, "only reviewed native Brain execution and watchdog may recur")
    source=(workflow_dir/"brain-cycle.yml").read_text()
    for fragment in ("group: brain-v2-state", "cancel-in-progress: false", "timeout-minutes: 5", "ref: brain-state-v2", "--expected-sha", "STATE_CONFLICT", "STATE_DELIVERY_UNVERIFIED", "MAIN_DRIFT", "soak_completed", "persist-credentials: false", "inputs.watchdog_run_id", "python -m brain.watchdog verify", "COMPETING_CLOCK_INPUTS", "python -m brain.cloudflare_clock", "inputs.cloudflare_attestation", "inputs.cloudflare_signature", "COMPETING_SCHEDULER_ORIGINS"):
        require(fragment in source, "missing workflow guarantee: "+fragment)
    require("force" not in source.replace("without force", "") and "portfolio-state-writer" not in source, "unsafe publication or legacy lock")
    clock=(workflow_dir/"brain-clock.yml").read_text()
    for fragment in ("branches: [brain-clock-v2]", "paths: [clock/pulse.json]", "timeout-minutes: 2", "actions: write", "contents: read", "python -m brain.clock", "-f ref=main", "inputs[clock_commit]", "steps.source.outputs.sha", "persist-credentials: false", "python -m brain.watchdog decide", "github.event_name == 'schedule'", "inputs[watchdog_run_id]"):
        require(fragment in clock, "missing bounded clock guarantee: "+fragment)
    require("contents: write" not in clock and "pull-requests: write" not in clock and "schedule:" in clock, "clock must remain read-only with only scoped Actions dispatch authority")
    require("python -m brain.clock" in source and "inputs.clock_commit" in source, "core must independently validate clock provenance")
    require((ROOT/"brain/cloudflare-clock-public.pem").read_text().startswith("-----BEGIN PUBLIC KEY-----"), "external clock public trust anchor missing")
    manifest=json.loads((ROOT/"legacy/WORKFLOW_ARCHIVE_MANIFEST.json").read_text())
    # Archive manifest has its own independently verified source hash inventory.
    entries=manifest.get("workflows",manifest.get("files",{}))
    if isinstance(entries,list):
        for entry in entries:
            path=entry.get("archive") or entry.get("archive_path") or entry.get("archived_path")
            require(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==entry["sha256"], "archive workflow altered: "+path)
    knowledge=json.loads((ROOT/'brain/REUSE_KNOWLEDGE.json').read_text())
    require(set(knowledge)=={'schema_version','scope','sources','fingerprint'} and knowledge['schema_version']==2,'knowledge contract changed')
    require(knowledge['scope']=='STRUCTURAL_REUSE_KNOWLEDGE_NOT_EXECUTED_OR_REVENUE_VERIFIED' and type(knowledge['sources']) is list and len(knowledge['sources'])<=12,'knowledge scope/bound changed')
    from brain.core import digest
    require(knowledge['fingerprint']==digest(knowledge['sources']) if knowledge['sources'] else knowledge['fingerprint'] is None,'knowledge fingerprint invalid')
    for item in knowledge['sources']:
        require(set(item)=={'key','repository','head_sha','path','blob_sha','code_sha256','test_paths','license','source_ref','target','matched_terms'},'knowledge fields invalid')
        from brain.intelligence import REPO,SHA
        require(REPO.fullmatch(item['repository']) and SHA.fullmatch(item['head_sha']) and SHA.fullmatch(item['blob_sha']),'knowledge exact identity invalid')
        require(item['source_ref']==f"https://github.com/{item['repository']}/blob/{item['head_sha']}/{item['path']}",'knowledge provenance invalid')
        require(item['target'] in {t['project'] for t in p['research_targets']} and set(item['matched_terms'])<=set(next(t['terms'] for t in p['research_targets'] if t['project']==item['target'])),'knowledge target/terms outside approved research')
        require(item['test_paths'] and len(item['matched_terms'])>=2,'knowledge minimum structural evidence missing')
    return {"status":"PASS","scope":"POLICY_VALIDATION_ONLY_NOT_LIVE_READINESS","components":3,"recurring_workflows":2,"paid_calls":0,"read_only_discovery":True,"production_accepted":False,"soak_started":False}
