"""Append-only local source-pinned repair queue. Not provider or release authority."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib,json,os,re,secrets,sqlite3,stat,tempfile
from pathlib import Path

class BatchFault(ValueError): pass
def must(ok,msg):
    if not ok: raise BatchFault(msg)
def encode(x): return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)
def digest(x): return hashlib.sha256(encode(x).encode()).hexdigest()
def hashval(x,n=64): return type(x) is str and re.fullmatch(r"[0-9a-f]{"+str(n)+r"}",x) is not None
def instant(x):
    must(type(x) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z",x),"TIME_INVALID")
    try: return datetime.fromisoformat(x[:-1]+"+00:00")
    except ValueError as e: raise BatchFault("TIME_INVALID") from e
def render(x): return x.isoformat(timespec="microseconds").replace("+00:00","Z")
PROJECTS={"portfolio-brain":"P00NSMASHER/portfolio-brain",
          "abvm":"P00NSMASHER/abvmschoolstarworld",
          "retally":"P00NSMASHER/github-value-hunt-ledger",
          "research-labs":"P00NSMASHER/github-value-hunt-ledger",
          "permitplate":"P00NSMASHER/permitplate-nyc",
          "capturebrief":"P00NSMASHER/capturebrief"}
NEXT={"OBSERVED":"DIAGNOSED","DIAGNOSED":"PATCHED","PATCHED":"TESTED"}
STAGES=set(NEXT)|{"TESTED"}
FIELDS={"project_id","repository","source_sha","fingerprint","owner","path","priority"}
IMMUTABLE=FIELDS|{"work_id","created_at"}
WORK=IMMUTABLE|{"stage","updated_at","epoch","claim","pending","evidence","effects"}
TABLE="CREATE TABLE batch_event (sequence INTEGER PRIMARY KEY, body TEXT NOT NULL, prev_hash TEXT NOT NULL, chain_hash TEXT NOT NULL)"
HEAD="CREATE TABLE batch_head (slot INTEGER PRIMARY KEY CHECK(slot=1), sequence INTEGER NOT NULL, chain_hash TEXT NOT NULL)"
MAX_EVENTS=4096
MAX_BYTES=4*1024*1024
MAX_WORK=256

def valid_path(p):
    return type(p) is str and 0<len(p)<=240 and not p.startswith("/") and "\\" not in p and all(x not in ("",".","..",".git") for x in p.split("/"))
def validate(row):
    must(type(row) is dict and set(row)==WORK,"WORK_FIELDS_INVALID")
    must(row["project_id"] in PROJECTS and row["repository"]==PROJECTS[row["project_id"]],"WORK_PROJECT_INVALID")
    must(hashval(row["source_sha"],40) and hashval(row["fingerprint"]) and hashval(row["work_id"]),"WORK_IDENTITY_INVALID")
    signature={k:row[k] for k in ("project_id","repository","source_sha","fingerprint","path")}
    must(row["work_id"]==digest(signature),"WORK_IDENTITY_INVALID")
    must(valid_path(row["path"]),"WORK_PATH_INVALID")
    must(type(row["owner"]) is str and re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}",row["owner"]) and type(row["priority"]) is int and 0<=row["priority"]<=4,"WORK_IDENTITY_INVALID")
    must(row["stage"] in STAGES and type(row["epoch"]) is int and row["epoch"]>=0,"WORK_STATE_INVALID")
    must(instant(row["updated_at"])>=instant(row["created_at"]),"TIME_REVERSED")
    must(type(row["evidence"]) is list and len(row["evidence"])<=64 and all(hashval(e) for e in row["evidence"]),"EVIDENCE_INVALID")
    must(type(row["effects"]) is dict,"EFFECT_INVALID")
    c=row["claim"]
    if c is not None:
        must(type(c) is dict and set(c)=={"token_hash","epoch","owner","issued_at","expires_at"}
             and hashval(c["token_hash"]) and c["epoch"]==row["epoch"] and c["owner"]==row["owner"]
             and 0<(instant(c["expires_at"])-instant(c["issued_at"])).total_seconds()<=3600,"CLAIM_INVALID")
    p=row["pending"]
    if p is not None:
        must(type(p) is dict and set(p)=={"operation_id","action","status"}
             and hashval(p["operation_id"]) and p["action"] in ("CREATE_BRANCH","CREATE_DRAFT_PR")
             and p["status"] in ("INTENT","UNKNOWN"),"EFFECT_INVALID")
    return row

class BatchQueue:
    def __init__(self,path):
        self.path=Path(os.path.abspath(path))
        must(self.path.parent.is_dir() and not any(p.is_symlink() for p in (self.path,*self.path.parents)),"STATE_PATH_UNSAFE")
        if not self.path.exists():
            fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            os.close(fd)
        st=self.path.stat()
        must(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid()
             and st.st_mode & 0o077==0,"STATE_PATH_UNSAFE")
        self.identity=(st.st_dev,st.st_ino)
        self.db=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        try:
            with self.tx():
                for name,sql in (("batch_event",TABLE),("batch_head",HEAD)):
                    prior=self.db.execute("SELECT sql FROM sqlite_master WHERE name=?",(name,)).fetchone()
                    if prior is None: self.db.execute(sql)
                    else: must(prior[0]==sql,"JOURNAL_SCHEMA_INVALID")
                self.db.execute("INSERT OR IGNORE INTO batch_head VALUES(1,0,?)",("0"*64,))
                self.scan()
        except BaseException:
            self.close()
            raise
    def close(self): self.db.close()
    @contextmanager
    def tx(self):
        must(not self.path.is_symlink() and (self.path.stat().st_dev,self.path.stat().st_ino)==self.identity,"STATE_PATH_CHANGED")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction: self.db.execute("ROLLBACK")
            raise
    def scan(self):
        must(not self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name IN ('batch_event','batch_head') LIMIT 1").fetchone(),
            "JOURNAL_SCHEMA_INVALID")
        must(self.db.execute("PRAGMA quick_check").fetchone()[0]=="ok","JOURNAL_TAMPERED")
        rows=self.db.execute("SELECT sequence,body,prev_hash,chain_hash FROM batch_event ORDER BY sequence LIMIT ?",(MAX_EVENTS+1,)).fetchall()
        must(len(rows)<=MAX_EVENTS and sum(len(r[1].encode()) for r in rows)<=MAX_BYTES,"JOURNAL_BOUND")
        records={}; prior="0"*64; old_time=None
        for position,(seq,raw,parent,ch) in enumerate(rows,1):
            try:
                frame=json.loads(raw)
                must(type(frame) is dict and set(frame)=={"time","previous","work"},"JOURNAL_TAMPERED")
                must(raw==encode(frame) and seq==position and parent==prior
                     and ch==digest({"sequence":seq,"body":frame,"parent":parent}),"JOURNAL_TAMPERED")
                at=instant(frame["time"])
                must(old_time is None or at>=old_time,"JOURNAL_TAMPERED")
                old_time=at
                item=validate(frame["work"]); old=records.get(item["work_id"])
                must(frame["previous"]==digest(old),"JOURNAL_TAMPERED")
                if old is not None:
                    must(all(old[k]==item[k] for k in IMMUTABLE) and instant(item["updated_at"])>=instant(old["updated_at"]),"JOURNAL_TAMPERED")
                records[item["work_id"]]=item; prior=ch
            except (KeyError,TypeError,ValueError,json.JSONDecodeError) as e:
                raise BatchFault("JOURNAL_TAMPERED") from e
        must(self.db.execute("SELECT slot,sequence,chain_hash FROM batch_head").fetchall()==[(1,len(rows),prior)],"JOURNAL_TAMPERED")
        must(len(records)<=MAX_WORK,"WORK_BOUND")
        return records,len(rows),prior
    def _append(self,row,at):
        records,seq,previous=self.scan()
        must(seq<MAX_EVENTS,"JOURNAL_BOUND")
        frame={"time":at,"previous":digest(records.get(row["work_id"])),"work":validate(row)}
        raw=encode(frame)
        size=self.db.execute("SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM batch_event").fetchone()[0]
        must(size+len(raw.encode())<=MAX_BYTES,"JOURNAL_BOUND")
        chain=digest({"sequence":seq+1,"body":frame,"parent":previous})
        self.db.execute("INSERT INTO batch_event VALUES(?,?,?,?)",(seq+1,raw,previous,chain))
        self.db.execute("UPDATE batch_head SET sequence=?,chain_hash=? WHERE slot=1",(seq+1,chain))
    def snapshot(self):
        self.db.execute("BEGIN")
        try: return {"work":deepcopy(self.scan()[0])}
        finally: self.db.execute("ROLLBACK")
    def checkpoint(self):
        self.db.execute("BEGIN")
        try:
            work,seq,h=self.scan()
            return {"sequence":seq,"chain_hash":h,"work_hash":digest(work)}
        finally: self.db.execute("ROLLBACK")
    def observe(self,item,*,now):
        must(type(item) is dict and set(item)==FIELDS,"WORK_FIELDS_INVALID")
        must(item["project_id"] in PROJECTS and item["repository"]==PROJECTS[item["project_id"]],"WORK_PROJECT_INVALID")
        must(hashval(item["source_sha"],40) and hashval(item["fingerprint"]),"WORK_IDENTITY_INVALID")
        must(valid_path(item["path"]),"WORK_PATH_INVALID")
        must(type(item["owner"]) is str and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}",item["owner"])
             and type(item["priority"]) is int and 0<=item["priority"]<=4,"WORK_IDENTITY_INVALID")
        instant(now)
        attrs=dict(item);attrs["owner"]=attrs["owner"].casefold()
        wid=digest({k:attrs[k] for k in ("project_id","repository","source_sha","fingerprint","path")})
        row=dict(attrs,work_id=wid,created_at=now,updated_at=now,stage="OBSERVED",epoch=0,claim=None,pending=None,evidence=[],effects={})
        with self.tx():
            state,_,_=self.scan()
            old=state.get(wid)
            if old:
                must(all(old[k]==row[k] for k in IMMUTABLE if k!="created_at"),"OBSERVATION_CONFLICT")
                return wid
            must(len(state)<MAX_WORK,"WORK_BOUND")
            self._append(row,now)
        return wid
    def claim(self,wid,owner,*,now,ttl_seconds=3600):
        must(hashval(wid) and type(owner) is str and type(ttl_seconds) is int and 0<ttl_seconds<=3600,"CLAIM_INVALID")
        at=instant(now)
        with self.tx():
            work,_,_=self.scan()
            must(wid in work,"WORK_UNKNOWN")
            row=deepcopy(work[wid])
            must(row["owner"]==owner.casefold(),"CLAIM_OWNER_INVALID")
            must(at>=instant(row["updated_at"]),"TIME_REVERSED")
            must(row["pending"] is None,"RECONCILIATION_REQUIRED")
            if row["claim"] and at<instant(row["claim"]["expires_at"]): raise BatchFault("CLAIM_CONFLICT")
            for key,other in work.items():
                if key==wid: continue
                busy=other["pending"] is not None or (other["claim"] is not None and at<instant(other["claim"]["expires_at"]))
                if busy and (other["repository"].casefold()==row["repository"].casefold() or other["owner"]==row["owner"]):
                    raise BatchFault("CLAIM_CONFLICT")
            token=secrets.token_hex(32); row["epoch"]+=1
            row["claim"]={"token_hash":digest(token),"epoch":row["epoch"],"owner":row["owner"],
                          "issued_at":now,"expires_at":render(at+timedelta(seconds=ttl_seconds))}
            row["updated_at"]=now
            self._append(row,now)
        return token
    @staticmethod
    def _owned(row,token,at):
        # An action timestamp predating the last committed claim/update
        # is a chronology violation, regardless of token validity.
        must(instant(at)>=instant(row["updated_at"]),"TIME_REVERSED")
        claim=row["claim"]
        must(claim is not None and type(token) is str and secrets.compare_digest(claim["token_hash"],digest(token))
             and instant(claim["issued_at"])<=instant(at)<instant(claim["expires_at"]),"CLAIM_STALE")
        must(instant(at)>=instant(row["updated_at"]),"TIME_REVERSED")
    def advance(self,wid,token,stage,*,evidence_sha,now):
        must(hashval(evidence_sha),"EVIDENCE_INVALID")
        with self.tx():
            work,_,_=self.scan()
            must(wid in work,"WORK_UNKNOWN")
            row=deepcopy(work[wid]);self._owned(row,token,now)
            must(row["pending"] is None,"RECONCILIATION_REQUIRED")
            must(NEXT.get(row["stage"])==stage,"TRANSITION_DENIED")
            row["stage"]=stage;row["updated_at"]=now
            row["evidence"]=list(dict.fromkeys([*row["evidence"],evidence_sha]))
            self._append(row,now)
    def begin_effect(self,wid,token,*,action,now):
        must(action in ("CREATE_BRANCH","CREATE_DRAFT_PR"),"EFFECT_INVALID")
        with self.tx():
            work,_,_=self.scan()
            must(wid in work,"WORK_UNKNOWN")
            row=deepcopy(work[wid]);self._owned(row,token,now)
            must(row["stage"]=="TESTED","EFFECT_BEFORE_TESTING")
            must(row["pending"] is None,"RECONCILIATION_REQUIRED")
            op=digest({"work_id":wid,"action":action,"source":row["source_sha"]})
            must(op not in row["effects"],"EFFECT_ALREADY_CONFIRMED")
            row["pending"]={"operation_id":op,"action":action,"status":"INTENT"}
            row["updated_at"]=now; self._append(row,now)
        return op
    def mark_unknown(self,wid,operation_id,*,now):
        with self.tx():
            work,_,_=self.scan()
            must(wid in work,"WORK_UNKNOWN")
            row=deepcopy(work[wid]);p=row["pending"]
            must(p is not None and p["operation_id"]==operation_id,"EFFECT_UNKNOWN")
            must(instant(now)>=instant(row["updated_at"]),"TIME_REVERSED")
            if p["status"]=="UNKNOWN": return
            p["status"]="UNKNOWN";row["updated_at"]=now;self._append(row,now)
    def reconcile(self,wid,operation_id,proof,*,now):
        # Arbitrary self-attested dicts cannot clear unknown provider writes.
        must(hashval(wid) and hashval(operation_id),"EFFECT_INVALID")
        instant(now)
        raise BatchFault("PROVIDER_READBACK_REQUIRED")
    def reconcile_original_draft(self,wid,operation_id,reader,*,pr_number,candidate_sha,now):
        """Resolve an uncertain external draft only after original GitHub GETs.

        Keep network calls outside the SQLite transaction. Revalidate the
        identical immutable work snapshot after readback; a concurrent claim
        or state change cannot be silently overwritten.
        """
        from brain.v9.batch_provider import GitHubOriginalReader
        must(hashval(wid) and hashval(operation_id) and hashval(candidate_sha,40)
             and type(pr_number) is int and 0<pr_number<10**9
             and type(reader) is GitHubOriginalReader,"PROVIDER_READBACK_REQUIRED")
        instant(now)
        original=self.snapshot()["work"].get(wid)
        must(original is not None,"WORK_UNKNOWN")
        pending=original["pending"]
        must(pending is not None and pending["operation_id"]==operation_id
             and pending["action"]=="CREATE_DRAFT_PR"
             and pending["status"] in ("INTENT","UNKNOWN"),
             "RECONCILIATION_REQUIRED")
        observed=reader.read_draft_only(
            original["repository"],pr_number,base_sha=original["source_sha"],
            head_sha=candidate_sha,operation_id=operation_id)
        must(observed["status"]=="ORIGINAL_DRAFT_WRITE_OBSERVED_CHECKS_UNKNOWN"
             and observed["production_accepted"] is False
             and observed["independent_check_verified"] is False,
             "PROVIDER_READBACK_REQUIRED")
        with self.tx():
            state,_,_=self.scan()
            current=state.get(wid)
            must(current is not None and digest(current)==digest(original),
                 "RECONCILIATION_SOURCE_CHANGED")
            must(instant(now)>=instant(current["updated_at"]),"TIME_REVERSED")
            item=deepcopy(current)
            item["effects"][operation_id]={
                "kind":"ORIGINAL_DRAFT_OBSERVED_NOT_APPROVED",
                "pr_number":pr_number,"candidate_sha":candidate_sha,
                "source_sha":current["source_sha"],"evidence_sha256":digest(observed),
                "observed_at":now,"production_accepted":False}
            item["pending"]=None
            item["updated_at"]=now
            self._append(item,now)
        return {"status":"EXTERNAL_DRAFT_RECONCILED_NOT_VERIFIED",
                "operation_id":operation_id,"provider_writes":0,
                "independent_gate_passed":False,"production_accepted":False}

    def metrics(self,*,now):
        at=instant(now)
        work=self.snapshot()["work"]
        ages=[(at-instant(row["created_at"])).total_seconds() for row in work.values()]
        must(all(t>=0 for t in ages),"TIME_REVERSED")
        return {"work_items":len(work),"uncertain_effects":sum(row["pending"] is not None for row in work.values()),
                "actual_live_verified":0,"production_accepted":False,
                "oldest_unresolved_seconds":max(ages,default=0),
                "stages":{s:sum(row["stage"]==s for row in work.values()) for s in sorted(STAGES)}}
    def restore_drill(self):
        before=self.checkpoint()
        with tempfile.TemporaryDirectory(prefix="brain-v9-restore-") as temp:
            target=Path(temp)/"replay.sqlite"
            with sqlite3.connect(target) as backup:
                self.db.backup(backup)
                must(backup.execute("PRAGMA integrity_check").fetchone()[0]=="ok","RESTORE_INTEGRITY_FAILED")
            other=BatchQueue(target)
            try: must(other.checkpoint()==before,"RESTORE_REPLAY_MISMATCH")
            finally: other.close()
        return {"status":"ISOLATED_RESTORE_REPLAY_PASSED","checkpoint":before,
                "production_accepted":False,"source_database_modified":False}
