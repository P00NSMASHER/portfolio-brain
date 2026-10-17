"""One-shot, fail-closed, independently collected V8 terminal acceptance proof.

Reads only original GitHub provider records and a pinned protected-source
SQLite archive. It never calls a write API, changes a branch, or releases V8.
Temporary CI evidence adapter: remove from draft after proof is captured.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime

OWNER_REPO = 'P00NSMASHER/portfolio-brain'
SOURCE = '98cce23ac031ccf9ffa7008a83e9a9b25571d568'
TERMINAL_STATE = '302a0b1b7f365f89ca320e6f516884ef4cb10c66'
SEQUENCE = 2516
CHAIN = 'dde2880655f055eaa4eda134450b8277e3fe9461619132ca235e9a0058d4c40e'
ORIGINAL_SOURCE_START = 'd1379be62822854985056b9ad748b2845cbdec38'
TRIGGER_MARKER = 'V8_TERMINAL_ACCEPTANCE_ONESHOT_710'
# Immutable original provider IDs, verified ZIP digests and successive state children.
CENSUS = (
 (38976214502,'4ef0a8e453b98cbecfb3a22ed0013155e741af9c3d7ca005a734c3ae331424a8','e2ff9c6c008d5a54fb3d8a995fda492fe8430ff7'),
 (38979091412,'e46991a20e4f92329c177f5ab20eb3d789a2871be26f249500cee1bdb0bcbe40','5330f1cd33fd46e1334703d3f413cd79bcc0681b'),
 (38981469874,'a74ae6779c20553f6529bf516dec31592367c58a3441d4f0201ead6beb055618','ea1f699dc154728a9ea9787ecfce5b7118f4e4fb'),
 (38984359246,'3b517b5eb7b6d07108c2b889edb16e3c1dd6137da75e465fd6b4399d8a737868','4497e11d0382a90884f958cc56d3a92869485d17'),
 (38986729888,'bcff789a223f56098d4dd0e9408e2886a0c02c94baa946d4824aae1dc2d8607d','78f9a9e4d2a1bd03eae100f968b2cad2a6e2d6cc'),
 (38989007623,'120ebf88843ecf330c56147c91e8175394bab0e075b3c5bf3d04b05c93caf145','eb2cefc83e2c0a058cf6c5af495ff6455bdd0c34'),
 (38990679044,'987ef58e31872cbd816ce4a0a848a7aa25af545e1097608b5f99f422bcafd2b4','ad5537354e2bae907fcf1c62a79e312d3ead98e6'),
 (38992570149,'df20556df867ed80f20908c0e00f7ae1c14feec62f54465123064afe8908b50d','e7319782465069b43c18dd65ac0b57068b394378'),
 (38994569858,'28f6c7f53e5886e6faad3807a148ce3f48726c7e322ed5405393fc0947445fde','87dceb2e17498b89a44b4ea7a753ec877d9721b2'),
 (38996514669,'b11751f13269fc5f0f9c48c4a3fca02adb2f456d75db6cec472600caed12fda9','a512740886355775abb1c238a795a458f65e1a63'),
 (38998439741,'9b9ba3e5e8f0a17d4e39ad7dd2898d14db8ad31254b53d7d2b603388262a17a3','86a546672d1cbdf85468974cf9c1ea754299ab46'),
 (39000339956,'27de81f03a3e80565e3485f4d134dfd1f572eb27091d9d45071c19cb894ddf0b','2f3ca7971df4dff644efb8ec377083b6f62f2bc1'),
 (39002223959,'54334ea98371a1f64f1e3ce496a72ff4ea389fd78af79977af7376f85a3dccc9','b6f41ea80691a4b7162e625bd3d7fc3d7e84f2d2'),
 (39004093680,'607ff9a0e10b286d0cbefb5576f7a5be90b1a96242f579e2543e635b92bbbd6b','f491b2c2bd1a829242d26332ba91dc9b88a5a8eb'),
 (39005927838,'492c25f55e662839cae725d64acd1dd67f6fb12e77d2c374692623c47bff624c','bc5915de24c585c6c6e1fe454b23e7bcd344b875'),
 (39007349466,'af003b49a4a3d51c25b39064b6a1b8230396799a5673414be39d9766abb78772','23e8741cf935a682a7b7505bf02a23dcd6cedfd4'),
 (39008952713,'6b9167e30457416ed6df319ddb9c5963ddabf749503823ffe5e89652d2184a3b','b91eed907cdc7f5e85bec9171c431dbe129eea92'),
 (39010808616,'82b7474e4a9fc1344bcef24e12b11f8defc5688610b073018e77f72c693e22cb','7ab8535c2937eba1677cf39f6b7bf6eec04c8518'),
 (39012672118,'81a86e0ae4239b9a78743ef826ec567ec7a2b92239099933552810ea37a936f3','302a0b1b7f365f89ca320e6f516884ef4cb10c66'),
)
MANDATORY_STEPS = {
 'Bind execution to unchanged current main',
 'Restore dedicated durable state branch',
 'Validate restoration and capture publication parent',
 'Exact-SHA deterministic preflight',
 'Read-only public project monitoring',
 'Bounded public code and opportunity research',
 'Evidence-bound deterministic experiment',
 'Verify authoritative state and zero event backlog',
 'Verify main and state parent before publication',
 'Verify and pack durable state into bounded Git blobs',
 'Publish one nonsecret state transaction without force',
 'Preserve verifiable execution evidence',
}

def require(condition, code):
    if not condition:
        raise ValueError(code)

def provider(path):
    require(path.startswith('repos/P00NSMASHER/portfolio-brain/'), 'UNAPPROVED_PROVIDER_PATH')
    output = subprocess.check_output(['gh','api',path],text=True,timeout=25)
    return json.loads(output)

def time_value(value):
    require(type(value) is str and value.endswith('Z'),'TIME_INVALID')
    return datetime.fromisoformat(value[:-1]+'+00:00')

def exact_original_checks():
    head=os.environ.get('REVIEWED_PR_SHA','')
    require(re.fullmatch('[a-f0-9]{40}',head) is not None,'PR_HEAD_INVALID')
    pr=provider('repos/'+OWNER_REPO+'/pulls/710')
    require(pr.get('state')=='open' and pr.get('draft') is True
           and pr.get('head',{}).get('sha')==head
           and pr.get('head',{}).get('repo',{}).get('full_name')==OWNER_REPO
           and pr.get('head',{}).get('ref')=='feature/v8-authority-map-20261016'
           and pr.get('base',{}).get('ref')=='main'
           and pr.get('base',{}).get('sha')==SOURCE
           and TRIGGER_MARKER in (pr.get('body') or ''),'UNREVIEWED_PR_OR_SOURCE')
    checks=provider('repos/'+OWNER_REPO+'/commits/'+head+'/check-runs?per_page=100')
    rows=checks.get('check_runs')
    require(type(rows) is list and type(checks.get('total_count')) is int
            and checks['total_count']==len(rows),'ORIGINAL_CHECK_CENSUS_INVALID')
    for name,app in (('validate',15368),('portfolio-phase1-gate',5121826)):
        relevant=[x for x in rows if x.get('name')==name and x.get('app',{}).get('id')==app and x.get('head_sha')==head]
        require(relevant and all(x.get('conclusion')=='success' and x.get('status')=='completed' for x in relevant),'ORIGINAL_INDEPENDENT_GATE_MISSING_'+name)
    main=provider('repos/'+OWNER_REPO+'/branches/main')
    require(main.get('commit',{}).get('sha')==SOURCE, 'MAIN_DRIFT')
    return head

def original_census():
    finished=[]; events=[]
    parent=ORIGINAL_SOURCE_START
    for run_id,ziphash,child in CENSUS:
        run=provider('repos/'+OWNER_REPO+'/actions/runs/'+str(run_id))
        require(run.get('head_sha')==SOURCE and run.get('name')=='brain-cycle-v2'
                and run.get('head_branch')=='main' and run.get('run_attempt')==1
                and run.get('conclusion')=='success' and run.get('status')=='completed'
                and run.get('path')=='.github/workflows/brain-cycle.yml',
                'ORIGINAL_RUN_INVALID_'+str(run_id))
        event=run.get('event')
        require(event in {'schedule','workflow_dispatch'},'NONAUTOMATIC_ORIGIN')
        jobs=provider('repos/'+OWNER_REPO+'/actions/runs/'+str(run_id)+'/jobs?per_page=100')
        arr=jobs.get('jobs')
        require(jobs.get('total_count')==1 and type(arr) is list and len(arr)==1,'JOB_CENSUS_INVALID')
        job=arr[0]
        require(job.get('name')=='monitor' and job.get('status')=='completed'
                and job.get('conclusion')=='success' and job.get('run_attempt') in {None,1},'JOB_NOT_SUCCESS')
        steps=job.get('steps')
        require(type(steps) is list and not any(x.get('conclusion')=='failure' for x in steps)
                and all(any(x.get('name')==name and x.get('conclusion')=='success' for x in steps) for name in MANDATORY_STEPS),
                'ORIGINAL_MANDATORY_STEP_FAILED')
        completed=time_value(job.get('completed_at'))
        finished.append(completed); events.append(event)
        artifacts=provider('repos/'+OWNER_REPO+'/actions/runs/'+str(run_id)+'/artifacts?per_page=100')
        rows=artifacts.get('artifacts')
        require(type(rows) is list and len(rows)==1 and artifacts.get('total_count')==1,'ARTIFACT_CENSUS_INVALID')
        art=rows[0]
        require(art.get('expired') is False
                and art.get('digest')=='sha256:'+ziphash
                and art.get('name')==f'brain-v2-cycle-{SOURCE}-{run_id}-1','ORIGINAL_ZIP_METADATA_MISMATCH')
        commit=provider('repos/'+OWNER_REPO+'/git/commits/'+child)
        require(commit.get('sha')==child and len(commit.get('parents',[]))==1
                and commit['parents'][0]['sha']==parent,'ORIGINAL_PUBLISHED_STATE_CHAIN')
        parent=child
    require(parent==TERMINAL_STATE and len(finished)==19,'TERMINAL_IDENTITY_CHANGED')
    gaps=[int((b-a).total_seconds()) for a,b in zip(finished,finished[1:])]
    span=int((finished[-1]-finished[0]).total_seconds())
    require(all(x>0 for x in gaps) and max(gaps)<=5400,'ORIGINAL_AUTOMATIC_GAP_EXCEEDED')
    require(span>=21600,'ORIGINAL_SIX_HOUR_WINDOW_INCOMPLETE')
    require(events.count('schedule')==3 and events.count('workflow_dispatch')==16,'ORIGINAL_ORIGIN_MIX_CHANGED')
    # Cloudflare dispatches are separately corroborated against original provider
    # event/request IDs; this local provider census does not self-sign that proof.
    return {'run_count':len(finished),'span_seconds':span,'max_gap_seconds':max(gaps),'native_schedule_runs':3,'cloudflare_dispatch_runs':16}

def independent_terminal():
    workspace=Path(os.environ['GITHUB_WORKSPACE'])
    canonical=workspace/'canonical'
    terminal=workspace/'terminal'
    require(subprocess.check_output(['git','-C',str(canonical),'rev-parse','HEAD'],text=True).strip()==SOURCE,'REVIEWED_SOURCE_CHECKOUT_DRIFT')
    require(subprocess.check_output(['git','-C',str(terminal),'rev-parse','HEAD'],text=True).strip()==TERMINAL_STATE,'TERMINAL_CHECKOUT_DRIFT')
    require(subprocess.check_output(['git','-C',str(terminal),'hash-object','state-manifest.json'],text=True).strip()=='0588b7c51d9449129e322909d2e294d87c2a0004','TERMINAL_MANIFEST_NOT_REVIEWED')
    # All imports below are from the exact immutable production-source tree,
    # not the candidate branch or an untrusted downloaded Python module.
    sys.path.insert(0,str(canonical))
    from brain.state_archive import restore
    from soak_v3.audit import verify_sqlite
    from brain.core import Store, digest
    restore(terminal)
    database=terminal/'state.sqlite'
    result=verify_sqlite(database,expected_sequence=SEQUENCE,
                         expected_chain=CHAIN,expected_source=SOURCE,
                         max_bytes=64*1024*1024,strict_event_ids=True)
    require(result['status']=='PASS','TERMINAL_EVENT_REPLAY_FAILED')
    state=Store(database,visibility='PUBLIC')
    try:
        row=state.db.execute('SELECT created_at,hash FROM reports ORDER BY id DESC LIMIT 1').fetchone()
        require(row is not None,'TERMINAL_REPORT_MISSING')
        report=state.read_report(SOURCE,now=row['created_at'])
        require(report.get('state_sequence')==SEQUENCE
                and report.get('canonical_hash')==CHAIN
                and report.get('pending_events')==0
                and report.get('status')=='PASS'
                and digest(report)==row['hash'],'TERMINAL_REPORT_DETERMINISTIC_MISMATCH')
    finally:
        state.close()
    return {'sqlite_sha256':result['sha256'],
            'sequence':SEQUENCE,'canonical_hash':CHAIN,
            'pending_events':0,'deterministic_report':'PASS','chunk_manifest_git_blob':'0588b7c51d9449129e322909d2e294d87c2a0004'}

def main():
    head=exact_original_checks()
    counts=original_census()
    terminal=independent_terminal()
    # Even after this independent PASS, release requires separately observed
    # Cloudflare provider/signed origin evidence and protected reviewer judgment.
    receipt=dict(schema_version=1,proof='INDEPENDENT_PROVIDER_AND_TERMINAL_REPLAY',
                 reviewed_pr_source=head,production_source=SOURCE,
                 terminal_state=TERMINAL_STATE,original_provider_census=counts,
                 terminal_replay=terminal,external_provider_origin_crosscheck='REQUIRED_SEPARATELY',
                 authorizes_merge=False,authorizes_deploy=False,
                 global_autonomous_repairs_certified=False)
    output=Path(os.environ['RUNNER_TEMP'])/'v8-independent-terminal-replay.json'
    output.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    print('Independent original GitHub run census, continuous state chain, terminal ZIP source checks and SQLite/report replay passed. No release authorized.')
if __name__=='__main__':
    try:
        main()
    except Exception:
        # No provider body, token, environment, or transport error details.
        raise SystemExit('V8_INDEPENDENT_TERMINAL_ACCEPTANCE_FAILED; RELEASE_HOLD_REMAINS') from None
