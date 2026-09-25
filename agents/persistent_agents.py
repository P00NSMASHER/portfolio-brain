#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sqlite3,time,uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class AgentRuntimeError(ValueError):pass
def req(ok,msg):
    if not ok:raise AgentRuntimeError(msg)
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())

class PortfolioAgentRuntime:
    def __init__(self,db_path,registry_doc=None):
        self.conn=sqlite3.connect(str(db_path));self.conn.row_factory=sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON");self.conn.execute("PRAGMA journal_mode=WAL")
        self.registry=registry_doc or load("agents/AGENT_REGISTRY.json");self.policy=load("agents/AGENT_POLICY.json")
        self.roles={r["agent_id"]:r for r in self.registry["roles"]}
        self.projects={p["project_id"] for p in load("registry/projects.json")["projects"]}
        self._migrate();self.bootstrap_agents()
    def close(self):self.conn.close()
    def _migrate(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents(agent_id TEXT PRIMARY KEY,role_key TEXT NOT NULL,status TEXT NOT NULL,generation INTEGER NOT NULL,parent_agent_id TEXT,last_heartbeat_at REAL,state_refs_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS work_items(work_id TEXT PRIMARY KEY,goal_type TEXT NOT NULL,title TEXT NOT NULL,assigned_agent_id TEXT NOT NULL REFERENCES agents(agent_id),project_ids_json TEXT NOT NULL,required_authority TEXT NOT NULL,consequence TEXT NOT NULL,state TEXT NOT NULL,priority INTEGER NOT NULL,lease_generation INTEGER NOT NULL DEFAULT 0,lease_owner TEXT,lease_expires_at REAL,run_id TEXT,state_refs_json TEXT NOT NULL,evidence_refs_json TEXT NOT NULL,output_hash TEXT,summary TEXT,verification_id TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS verification_reports(verification_id TEXT PRIMARY KEY,work_id TEXT NOT NULL REFERENCES work_items(work_id),builder_agent_id TEXT NOT NULL,verifier_agent_id TEXT NOT NULL,verdict TEXT NOT NULL,report_hash TEXT NOT NULL,evidence_refs_json TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(snapshot_id TEXT PRIMARY KEY,work_id TEXT NOT NULL REFERENCES work_items(work_id),state TEXT NOT NULL,state_refs_json TEXT NOT NULL,event_seq INTEGER NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,agent_id TEXT,work_id TEXT,event_type TEXT NOT NULL,payload_json TEXT NOT NULL,created_at REAL NOT NULL,prev_hash TEXT NOT NULL,event_hash TEXT NOT NULL UNIQUE);
        CREATE INDEX IF NOT EXISTS idx_agent_work_queue ON work_items(assigned_agent_id,state,priority DESC,created_at);
        """);self.conn.commit()
    def bootstrap_agents(self,now=None):
        ts=time.time() if now is None else float(now)
        for r in self.registry["roles"]:
            self.conn.execute("INSERT OR IGNORE INTO agents(agent_id,role_key,status,generation,parent_agent_id,last_heartbeat_at,state_refs_json) VALUES(?,?,?,?,?,?,?)",(r["agent_id"],r["role_key"],r["status"],1,r["parent_agent_id"],ts,"[]"))
        self.conn.commit()
    def _role(self,agent_id):
        req(agent_id in self.roles,f"unknown agent: {agent_id}");return self.roles[agent_id]
    def _work(self,work_id):
        row=self.conn.execute("SELECT * FROM work_items WHERE work_id=?",(work_id,)).fetchone();req(row is not None,f"unknown work: {work_id}");return row
    def _event(self,agent_id,work_id,event_type,payload,now):
        prev=self.conn.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone();prev_hash=prev["event_hash"] if prev else "sha256:"+"0"*64
        core={"agent_id":agent_id,"work_id":work_id,"event_type":event_type,"payload":payload,"created_at":float(now),"prev_hash":prev_hash}
        event_hash=sha(core);event_id="AEVT-"+event_hash.split(":",1)[1][:20].upper()
        self.conn.execute("INSERT INTO events(event_id,agent_id,work_id,event_type,payload_json,created_at,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",(event_id,agent_id,work_id,event_type,canon(payload),float(now),prev_hash,event_hash))
        return event_id
    def heartbeat_agent(self,agent_id,now=None):
        ts=time.time() if now is None else float(now);self._role(agent_id)
        self.conn.execute("UPDATE agents SET last_heartbeat_at=? WHERE agent_id=?",(ts,agent_id));self._event(agent_id,None,"AGENT_HEARTBEAT",{},ts);self.conn.commit()
    def authorize_model_tier(self,agent_id,tier):
        role=self._role(agent_id);req(type(tier) is int and 0<=tier<=3,"invalid model tier");req(tier<=role["max_model_tier"],"requested model tier exceeds role ceiling");return True
    def enqueue_work(self,creator_agent_id,assigned_agent_id,goal_type,title,project_ids,required_authority,consequence,*,priority=0,state_refs=None,work_id=None,now=None):
        ts=time.time() if now is None else float(now);creator=self._role(creator_agent_id);target=self._role(assigned_agent_id)
        req(creator["can_delegate"],"creator role cannot delegate work");req(target["status"]=="ACTIVE","target agent is not active");req(goal_type in target["allowed_goal_types"],"goal type is not allowed for target role")
        req(required_authority!="ACT","agent work may not require ACT");ranks=self.policy["authority_rank"];req(required_authority in ranks and ranks[required_authority]<=ranks[target["max_autonomy"]],"work authority exceeds role ceiling")
        req(consequence in {"LOW","MEDIUM","HIGH","CRITICAL"},"invalid consequence");req(isinstance(project_ids,list) and project_ids and len(project_ids)==len(set(project_ids)),"project_ids required and unique");req(all(p in self.projects for p in project_ids),"work references unknown project")
        refs=list(state_refs or []);req(len(refs)==len(set(refs)) and all(isinstance(x,str) and x for x in refs),"state_refs invalid");wid=work_id or "AWORK-"+uuid.uuid4().hex[:20].upper()
        self.conn.execute("INSERT INTO work_items(work_id,goal_type,title,assigned_agent_id,project_ids_json,required_authority,consequence,state,priority,state_refs_json,evidence_refs_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'PENDING',?,?,?,?,?)",(wid,goal_type,title,assigned_agent_id,canon(project_ids),required_authority,consequence,int(priority),canon(refs),"[]",ts,ts))
        self._event(creator_agent_id,wid,"WORK_ENQUEUED",{"assigned_agent_id":assigned_agent_id,"goal_type":goal_type,"required_authority":required_authority,"consequence":consequence},ts);self.conn.commit();return wid
    def requeue_expired(self,now=None):
        ts=time.time() if now is None else float(now);rows=self.conn.execute("SELECT work_id,assigned_agent_id,lease_generation,run_id FROM work_items WHERE state='RUNNING' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?",(ts,)).fetchall()
        for row in rows:
            self.conn.execute("UPDATE work_items SET state='PENDING',lease_owner=NULL,lease_expires_at=NULL,run_id=NULL,updated_at=? WHERE work_id=?",(ts,row["work_id"]))
            self._event(row["assigned_agent_id"],row["work_id"],"LEASE_EXPIRED_REQUEUED",{"lease_generation":row["lease_generation"],"run_id":row["run_id"]},ts)
        self.conn.commit();return len(rows)
    def claim_work(self,agent_id,worker_instance_id,*,lease_seconds=None,now=None):
        ts=time.time() if now is None else float(now);role=self._role(agent_id);lease=int(lease_seconds or self.policy["lease"]["default_seconds"])
        req(self.policy["lease"]["minimum_seconds"]<=lease<=self.policy["lease"]["maximum_seconds"],"lease_seconds outside policy");req(isinstance(worker_instance_id,str) and worker_instance_id,"worker_instance_id required");self.requeue_expired(ts)
        busy=self.conn.execute("SELECT 1 FROM work_items WHERE assigned_agent_id=? AND state='RUNNING' AND lease_expires_at>?",(agent_id,ts)).fetchone()
        if busy:return None
        allowed=tuple(role["allowed_goal_types"]);placeholders=",".join("?" for _ in allowed)
        row=self.conn.execute(f"SELECT * FROM work_items WHERE assigned_agent_id=? AND state='PENDING' AND goal_type IN ({placeholders}) ORDER BY priority DESC,created_at LIMIT 1",(agent_id,*allowed)).fetchone()
        if row is None:return None
        generation=int(row["lease_generation"])+1;run_id="ARUN-"+uuid.uuid4().hex[:20].upper()
        self.conn.execute("UPDATE work_items SET state='RUNNING',lease_generation=?,lease_owner=?,lease_expires_at=?,run_id=?,updated_at=? WHERE work_id=?",(generation,worker_instance_id,ts+lease,run_id,ts,row["work_id"]))
        self._event(agent_id,row["work_id"],"WORK_CLAIMED",{"worker_instance_id":worker_instance_id,"lease_generation":generation,"run_id":run_id},ts);self.conn.commit()
        return {"work_id":row["work_id"],"run_id":run_id,"lease_generation":generation,"lease_expires_at":ts+lease}
    def _require_live_lease(self,agent_id,work_id,worker_instance_id,run_id,generation,now):
        row=self._work(work_id);req(row["assigned_agent_id"]==agent_id and row["state"]=="RUNNING","work is not running for agent");req(row["lease_owner"]==worker_instance_id and row["run_id"]==run_id and int(row["lease_generation"])==int(generation),"stale or invalid lease identity");req(row["lease_expires_at"] is not None and float(row["lease_expires_at"])>float(now),"worker lease expired");return row
    def heartbeat_lease(self,agent_id,work_id,worker_instance_id,run_id,generation,*,extend_seconds=None,now=None):
        ts=time.time() if now is None else float(now);ext=int(extend_seconds or self.policy["lease"]["default_seconds"]);req(self.policy["lease"]["minimum_seconds"]<=ext<=self.policy["lease"]["maximum_seconds"],"extend_seconds outside policy");self._require_live_lease(agent_id,work_id,worker_instance_id,run_id,generation,ts)
        self.conn.execute("UPDATE work_items SET lease_expires_at=?,updated_at=? WHERE work_id=?",(ts+ext,ts,work_id));self._event(agent_id,work_id,"LEASE_HEARTBEAT",{"lease_generation":int(generation),"run_id":run_id},ts);self.conn.commit()
    def submit_work(self,agent_id,work_id,worker_instance_id,run_id,generation,*,output_hash,evidence_refs,summary="",state_refs=None,now=None):
        ts=time.time() if now is None else float(now);self._require_live_lease(agent_id,work_id,worker_instance_id,run_id,generation,ts);req(isinstance(output_hash,str) and output_hash.startswith("sha256:") and len(output_hash)==71,"output_hash must be sha256");req(isinstance(evidence_refs,list) and evidence_refs and len(evidence_refs)==len(set(evidence_refs)),"submission evidence_refs required and unique")
        refs=list(state_refs or []);req(len(refs)==len(set(refs)),"state_refs must be unique")
        self.conn.execute("UPDATE work_items SET state='VERIFYING',lease_owner=NULL,lease_expires_at=NULL,run_id=NULL,output_hash=?,summary=?,evidence_refs_json=?,state_refs_json=?,updated_at=? WHERE work_id=?",(output_hash,str(summary)[:1000],canon(evidence_refs),canon(refs),ts,work_id))
        self._event(agent_id,work_id,"WORK_SUBMITTED_FOR_VERIFICATION",{"output_hash":output_hash,"evidence_refs":evidence_refs},ts);self.conn.commit()
    def verify_work(self,verifier_agent_id,work_id,verdict,*,report_hash,evidence_refs,now=None):
        ts=time.time() if now is None else float(now);work=self._work(work_id);verifier=self._role(verifier_agent_id);builder=self._role(work["assigned_agent_id"])
        req(work["state"]=="VERIFYING","work is not awaiting verification");req(verifier["verifier_eligible"],"role is not verifier-eligible");req(verifier_agent_id!=work["assigned_agent_id"],"builder cannot verify own work");req(verifier["independence_group"]!=builder["independence_group"],"verifier independence group must differ from builder")
        req("*" in verifier["verification_goal_types"] or work["goal_type"] in verifier["verification_goal_types"],"verifier role cannot verify this goal type");req(verdict in self.policy["allowed_verdicts"],"invalid verdict");req(isinstance(report_hash,str) and report_hash.startswith("sha256:") and len(report_hash)==71,"report_hash must be sha256");req(isinstance(evidence_refs,list) and evidence_refs and len(evidence_refs)==len(set(evidence_refs)),"verification evidence required")
        vid="AVER-"+uuid.uuid4().hex[:20].upper();self.conn.execute("INSERT INTO verification_reports(verification_id,work_id,builder_agent_id,verifier_agent_id,verdict,report_hash,evidence_refs_json,created_at) VALUES(?,?,?,?,?,?,?,?)",(vid,work_id,work["assigned_agent_id"],verifier_agent_id,verdict,report_hash,canon(evidence_refs),ts))
        new_state={"PASS":"COMPLETE","FAIL":"FAILED","UNKNOWN":"BLOCKED"}[verdict];self.conn.execute("UPDATE work_items SET state=?,verification_id=?,updated_at=? WHERE work_id=?",(new_state,vid,ts,work_id));self._event(verifier_agent_id,work_id,"WORK_VERIFIED",{"verification_id":vid,"verdict":verdict,"report_hash":report_hash,"builder_agent_id":work["assigned_agent_id"]},ts);self.conn.commit();return vid
    def checkpoint_work(self,work_id,*,now=None):
        ts=time.time() if now is None else float(now);row=self._work(work_id);last=self.conn.execute("SELECT COALESCE(MAX(seq),0) AS seq FROM events").fetchone()["seq"];sid="ASNAP-"+uuid.uuid4().hex[:20].upper();self.conn.execute("INSERT INTO snapshots(snapshot_id,work_id,state,state_refs_json,event_seq,created_at) VALUES(?,?,?,?,?,?)",(sid,work_id,row["state"],row["state_refs_json"],last,ts));self.conn.commit();return sid
    def restore_state_refs(self,work_id,snapshot_id,*,now=None):
        ts=time.time() if now is None else float(now);work=self._work(work_id);req(work["state"] not in {"COMPLETE","FAILED","CANCELLED"},"terminal work cannot restore operational state");snap=self.conn.execute("SELECT * FROM snapshots WHERE snapshot_id=? AND work_id=?",(snapshot_id,work_id)).fetchone();req(snap is not None,"snapshot not found")
        self.conn.execute("UPDATE work_items SET state_refs_json=?,updated_at=? WHERE work_id=?",(snap["state_refs_json"],ts,work_id));self._event(work["assigned_agent_id"],work_id,"WORK_STATE_RESTORED",{"snapshot_id":snapshot_id,"snapshot_event_seq":snap["event_seq"]},ts);self.conn.commit()
    def get_work(self,work_id):
        row=self._work(work_id);d=dict(row)
        for k in ["project_ids_json","state_refs_json","evidence_refs_json"]:d[k[:-5]]=json.loads(d.pop(k))
        return d
    def event_chain_valid(self):
        prev="sha256:"+"0"*64
        for row in self.conn.execute("SELECT * FROM events ORDER BY seq"):
            core={"agent_id":row["agent_id"],"work_id":row["work_id"],"event_type":row["event_type"],"payload":json.loads(row["payload_json"]),"created_at":float(row["created_at"]),"prev_hash":prev}
            if row["prev_hash"]!=prev or row["event_hash"]!=sha(core):return False
            prev=row["event_hash"]
        return True
