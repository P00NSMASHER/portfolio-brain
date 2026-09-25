#!/usr/bin/env python3
"""Bounded autonomous software factory control plane."""
from __future__ import annotations
import base64,hashlib,json,re,sqlite3,time,uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class SoftwareFactoryError(ValueError):pass
def req(ok,msg):
    if not ok:raise SoftwareFactoryError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def policy():return load("software_factory/FACTORY_POLICY.json")
def _slug(v):return re.sub(r"[^a-z0-9._-]+","-",v.lower()).strip("-")[:48] or "work"

def identify_work(allocation_snapshot,experiment_portfolio):
    by_resource={p["resource_type"]:p for p in allocation_snapshot["plans"]}
    eng=by_resource["ENGINEERING_CAPACITY"]
    if eng["status"]!="ACTIVE_RECOMMENDATION" or not eng["recommendations"]:return []
    exp_by_id={p["experiment_id"]:p for p in experiment_portfolio["plans"]}
    out=[]
    for rec in eng["recommendations"]:
        exp=exp_by_id[rec["source_experiment_id"]]
        if exp["status"]!="READY_FOR_ISOLATED_EXECUTION" or exp["execution_mode"]!="ISOLATED_SYNTHETIC_TEST":continue
        out.append({
          "project_id":rec["project_id"],"experiment_id":exp["experiment_id"],"uncertainty_id":rec["source_uncertainty_id"],
          "required_goal_type":"ISOLATED_IMPLEMENTATION","required_authority":"MODIFY",
          "evidence_refs":rec["evidence_refs"]
        })
    return out

def _repo_policy(repository_id):
    rows=policy()["repository_policies"];matches=[x for x in rows if x["repository_id"]==repository_id]
    req(len(matches)==1,"repository policy missing/duplicate");return matches[0]

def _path_allowed(path):
    req(isinstance(path,str) and path and not path.startswith("/") and ".." not in Path(path).parts,"invalid candidate path")
    for f in policy()["forbidden_candidate_paths"]:
        if f.endswith("/"):
            if path.startswith(f):return False
        elif path==f or path.startswith(f):return False
    return True

class SoftwareFactory:
    def __init__(self,db_path):
        self.conn=sqlite3.connect(str(db_path));self.conn.row_factory=sqlite3.Row;self._migrate()
        self.roles={r["agent_id"]:r for r in load("agents/AGENT_REGISTRY.json")["roles"]}
    def close(self):self.conn.close()
    def _migrate(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS work(
          work_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,repository_id TEXT NOT NULL,repository_full_name TEXT NOT NULL,
          base_branch TEXT NOT NULL,base_sha TEXT NOT NULL,title TEXT NOT NULL,issue_ref TEXT NOT NULL,
          builder_agent_id TEXT NOT NULL,verifier_agent_id TEXT NOT NULL,state TEXT NOT NULL,attempt INTEGER NOT NULL,max_attempts INTEGER NOT NULL,
          branch_name TEXT,commit_sha TEXT,changed_paths_json TEXT NOT NULL,test_commands_json TEXT NOT NULL,test_receipt_hashes_json TEXT NOT NULL,
          diff_hash TEXT,verification_id TEXT,pr_number INTEGER,pr_url TEXT,provenance_refs_json TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS verification(
          verification_id TEXT PRIMARY KEY,work_id TEXT NOT NULL,builder_agent_id TEXT NOT NULL,verifier_agent_id TEXT NOT NULL,
          verdict TEXT NOT NULL,report_hash TEXT NOT NULL,evidence_refs_json TEXT NOT NULL,created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,work_id TEXT NOT NULL,event_type TEXT NOT NULL,
          payload_json TEXT NOT NULL,created_at REAL NOT NULL,prev_hash TEXT NOT NULL,event_hash TEXT UNIQUE NOT NULL
        );
        """);self.conn.commit()
    def _work(self,wid):
        r=self.conn.execute("SELECT * FROM work WHERE work_id=?",(wid,)).fetchone();req(r is not None,f"unknown work: {wid}");return r
    def _event(self,wid,event_type,payload,now):
        prev=self.conn.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash=prev["event_hash"] if prev else "sha256:"+"0"*64
        core={"work_id":wid,"event_type":event_type,"payload":payload,"created_at":float(now),"prev_hash":prev_hash}
        h=hashv(core);eid="SFE-"+h.split(":",1)[1][:20].upper()
        self.conn.execute("INSERT INTO events(event_id,work_id,event_type,payload_json,created_at,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?)",(eid,wid,event_type,canon(payload),float(now),prev_hash,h))
    def enqueue(self,*,work_id,project_id,repository_id,base_sha,title,issue_ref,verifier_agent_id,provenance_refs,now=None):
        ts=time.time() if now is None else float(now);rp=_repo_policy(repository_id)
        req(rp["candidate_modify_enabled"],"repository is not onboarded for candidate MODIFY")
        req(len(base_sha)==40 and all(c in "0123456789abcdef" for c in base_sha),"base_sha must be exact git SHA")
        req(verifier_agent_id in policy()["allowed_verifier_agent_ids"],"verifier not allowed")
        req(verifier_agent_id!="AGT-ENGINEER","builder cannot verify own work")
        req(provenance_refs and len(provenance_refs)==len(set(provenance_refs)),"provenance required and unique")
        self.conn.execute("""INSERT INTO work(work_id,project_id,repository_id,repository_full_name,base_branch,base_sha,title,issue_ref,builder_agent_id,verifier_agent_id,state,attempt,max_attempts,changed_paths_json,test_commands_json,test_receipt_hashes_json,provenance_refs_json,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,'QUEUED',0,?,'[]','[]','[]',?,?,?)""",
          (work_id,project_id,repository_id,rp["repository_full_name"],rp["default_branch"],base_sha,title,issue_ref,"AGT-ENGINEER",verifier_agent_id,policy()["max_attempts"],canon(provenance_refs),ts,ts))
        self._event(work_id,"ENQUEUED",{"repository_id":repository_id,"base_sha":base_sha,"verifier_agent_id":verifier_agent_id},ts);self.conn.commit()
    def claim(self,work_id,agent_id,now=None):
        ts=time.time() if now is None else float(now);r=self._work(work_id)
        req(agent_id=="AGT-ENGINEER" and agent_id==r["builder_agent_id"],"only Engineer may claim factory work");req(r["state"]=="QUEUED","work not queued")
        attempt=int(r["attempt"])+1;req(attempt<=int(r["max_attempts"]),"attempt limit exhausted")
        branch=f"{policy()['branch_prefix']}{_slug(work_id)}/attempt-{attempt}"
        req(branch!=r["base_branch"] and branch.startswith(policy()["branch_prefix"]),"attempt branch isolation failed")
        self.conn.execute("UPDATE work SET state='RUNNING',attempt=?,branch_name=?,updated_at=? WHERE work_id=?",(attempt,branch,ts,work_id))
        self._event(work_id,"CLAIMED",{"attempt":attempt,"branch_name":branch},ts);self.conn.commit()
        return self.branch_action(work_id)
    def branch_action(self,work_id):
        r=self._work(work_id);req(r["state"]=="RUNNING","work not running")
        return action_packet("CREATE_BRANCH",r,expected_head_sha=None,files=[],commit_message=None,pr_title=None,pr_body=None)
    def record_candidate_commit(self,work_id,agent_id,*,commit_sha,changed_paths,test_commands,test_receipt_hashes,diff_hash,now=None):
        ts=time.time() if now is None else float(now);r=self._work(work_id)
        req(agent_id=="AGT-ENGINEER" and r["builder_agent_id"]==agent_id,"only Engineer may record candidate commit");req(r["state"]=="RUNNING","work not running")
        req(len(commit_sha)==40 and commit_sha!=r["base_sha"],"candidate commit must differ from base and be exact SHA")
        req(changed_paths and len(changed_paths)<=policy()["max_changed_files"] and len(changed_paths)==len(set(changed_paths)),"changed_paths invalid")
        req(all(_path_allowed(p) for p in changed_paths),"candidate touches forbidden path")
        req(test_commands and len(test_commands)==len(set(test_commands)),"regression test commands required")
        req(test_receipt_hashes and len(test_receipt_hashes)==len(set(test_receipt_hashes)) and all(h.startswith("sha256:") and len(h)==71 for h in test_receipt_hashes),"test receipts required")
        req(isinstance(diff_hash,str) and diff_hash.startswith("sha256:") and len(diff_hash)==71,"diff_hash required")
        self.conn.execute("UPDATE work SET state='VERIFYING',commit_sha=?,changed_paths_json=?,test_commands_json=?,test_receipt_hashes_json=?,diff_hash=?,updated_at=? WHERE work_id=?",
                          (commit_sha,canon(changed_paths),canon(test_commands),canon(test_receipt_hashes),diff_hash,ts,work_id))
        self._event(work_id,"SUBMITTED_FOR_VERIFICATION",{"commit_sha":commit_sha,"diff_hash":diff_hash,"test_receipt_hashes":test_receipt_hashes},ts);self.conn.commit()
    def verify(self,work_id,verifier_agent_id,verdict,*,report_hash,evidence_refs,now=None):
        ts=time.time() if now is None else float(now);r=self._work(work_id)
        req(r["state"]=="VERIFYING","work not verifying");req(verifier_agent_id==r["verifier_agent_id"],"wrong verifier");req(verifier_agent_id!=r["builder_agent_id"],"builder cannot verify self")
        req(verifier_agent_id in policy()["allowed_verifier_agent_ids"],"verifier not allowed");req(verdict in {"PASS","FAIL","UNKNOWN"},"invalid verdict")
        req(report_hash.startswith("sha256:") and len(report_hash)==71,"report hash required");req(evidence_refs and len(evidence_refs)==len(set(evidence_refs)),"verification evidence required")
        vid="SFV-"+uuid.uuid4().hex[:20].upper()
        self.conn.execute("INSERT INTO verification(verification_id,work_id,builder_agent_id,verifier_agent_id,verdict,report_hash,evidence_refs_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                          (vid,work_id,r["builder_agent_id"],verifier_agent_id,verdict,report_hash,canon(evidence_refs),ts))
        if verdict=="PASS":state="READY_FOR_PR"
        elif int(r["attempt"])<int(r["max_attempts"]):state="QUEUED"
        else:state="BLOCKED"
        self.conn.execute("UPDATE work SET state=?,verification_id=?,branch_name=CASE WHEN ?='QUEUED' THEN NULL ELSE branch_name END,commit_sha=CASE WHEN ?='QUEUED' THEN NULL ELSE commit_sha END,updated_at=? WHERE work_id=?",
                          (state,vid,state,state,ts,work_id))
        self._event(work_id,"VERIFIED",{"verification_id":vid,"verdict":verdict,"next_state":state},ts);self.conn.commit();return vid
    def pr_action(self,work_id):
        r=self._work(work_id);req(r["state"]=="READY_FOR_PR","work not PR-ready");rp=_repo_policy(r["repository_id"]);req(rp["pr_create_enabled"],"PR creation disabled")
        title=f"[factory] {r['title']}"
        body=f"Factory work: {r['work_id']}\nBase: {r['base_sha']}\nCandidate: {r['commit_sha']}\nVerification: {r['verification_id']}\n"
        return action_packet("CREATE_PR",r,expected_head_sha=r["commit_sha"],files=[],commit_message=None,pr_title=title,pr_body=body)
    def record_pr(self,work_id,*,pr_number,pr_url,head_sha,now=None):
        ts=time.time() if now is None else float(now);r=self._work(work_id);req(r["state"]=="READY_FOR_PR","work not PR-ready")
        req(type(pr_number) is int and pr_number>0 and isinstance(pr_url,str) and pr_url,"invalid PR identity");req(head_sha==r["commit_sha"],"PR head does not match verified commit")
        self.conn.execute("UPDATE work SET state='PR_OPEN',pr_number=?,pr_url=?,updated_at=? WHERE work_id=?",(pr_number,pr_url,ts,work_id))
        self._event(work_id,"PR_OPENED",{"pr_number":pr_number,"pr_url":pr_url,"head_sha":head_sha},ts);self.conn.commit()
    def get(self,work_id):
        r=dict(self._work(work_id))
        for k in ["changed_paths_json","test_commands_json","test_receipt_hashes_json","provenance_refs_json"]:r[k[:-5]]=json.loads(r.pop(k))
        return r
    def event_chain_valid(self):
        prev="sha256:"+"0"*64
        for r in self.conn.execute("SELECT * FROM events ORDER BY seq"):
            core={"work_id":r["work_id"],"event_type":r["event_type"],"payload":json.loads(r["payload_json"]),"created_at":float(r["created_at"]),"prev_hash":prev}
            if r["prev_hash"]!=prev or r["event_hash"]!=hashv(core):return False
            prev=r["event_hash"]
        return True

def action_packet(operation,row,*,expected_head_sha,files,commit_message,pr_title,pr_body):
    req(operation in policy()["executor_operations"],"unsupported executor operation")
    req(row["branch_name"] and row["branch_name"].startswith(policy()["branch_prefix"]),"candidate branch required")
    req(row["branch_name"]!=row["base_branch"],"candidate branch cannot be default branch")
    core={"schema_version":"1.0.0","operation":operation,"factory_work_id":row["work_id"],"repository_full_name":row["repository_full_name"],"default_branch":row["base_branch"],"branch_name":row["branch_name"],"base_sha":row["base_sha"],"expected_head_sha":expected_head_sha,"files":files,"commit_message":commit_message,"pr_title":pr_title,"pr_body":pr_body}
    aid="SFA-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper()
    packet={"action_id":aid,**core}
    return {**packet,"action_hash":hashv(packet)}

def make_commit_action(work,files,commit_message):
    req(work["state"]=="RUNNING","work not running");req(files and len(files)<=policy()["max_changed_files"],"candidate files required")
    total=0;normalized=[]
    for f in files:
        path=f["path"];req(_path_allowed(path),"candidate touches forbidden path")
        raw=base64.b64decode(f["content_b64"],validate=True);req(len(raw)<=policy()["max_single_file_bytes"],"file too large")
        total+=len(raw);req(total<=policy()["max_total_content_bytes"],"candidate content budget exceeded")
        h="sha256:"+hashlib.sha256(raw).hexdigest();req(h==f["content_sha256"],"content hash mismatch")
        normalized.append({"path":path,"content_b64":f["content_b64"],"content_sha256":h})
    row={**work}
    return action_packet("COMMIT_CANDIDATE",row,expected_head_sha=work["base_sha"],files=normalized,commit_message=commit_message,pr_title=None,pr_body=None)
