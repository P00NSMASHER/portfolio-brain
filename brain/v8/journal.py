"""Private local append-only work history; never operates a production provider."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import stat
from brain.core import BrainError, canonical, digest, require
from brain.v8 import SCOPE
from brain.v8.contracts import HASH, matches, validate_work, advance, parse_utc

APPLICATION_ID = 0x42523830
SCHEMA = '''CREATE TABLE kernel_events (
seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE,
body TEXT NOT NULL, body_hash TEXT NOT NULL, prev_hash TEXT NOT NULL, chain_hash TEXT NOT NULL)'''
OP_FIELDS = {'schema_version','operation_id','work','expected_state','occurred_at','outcome'}
OUTCOMES = {'LOCAL_COMMITTED','EXTERNAL_INTENT','EXTERNAL_CONFIRMED','EXTERNAL_UNKNOWN'}
MUTABLE = {'state','evidence_ids','updated_at','attempts','blocker'}
MAX_RECORDS = 10000


def _private_path(path):
    path=Path(os.path.abspath(path))
    require(not any(p.is_symlink() for p in (path,*path.parents)), 'V8_SYMLINK_REFUSED')
    parent=path.parent.stat()
    require(parent.st_uid==os.getuid() and parent.st_mode & 0o077==0,
            'V8_PRIVATE_PARENT_REQUIRED')
    if path.exists():
        st=path.stat()
        require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid()
                and st.st_mode & 0o077==0 and st.st_size<=64*1024*1024,
                'V8_PRIVATE_REGULAR_FILE_REQUIRED')
    return path


def _operation(op):
    require(type(op) is dict and set(op)==OP_FIELDS, 'V8_OPERATION_FIELDS_INVALID')
    require(type(op['schema_version']) is int and op['schema_version']==1
            and matches(HASH,op['operation_id']), 'V8_OPERATION_ID_INVALID')
    row=validate_work(op['work'])
    require(type(op['outcome']) is str and op['outcome'] in OUTCOMES, 'V8_OUTCOME_INVALID')
    require(op['occurred_at']==row['updated_at'], 'V8_OPERATION_TIME_MISMATCH')
    parse_utc(op['occurred_at'])
    require(op['expected_state'] is None or type(op['expected_state']) is str,
            'V8_EXPECTED_STATE_INVALID')
    return deepcopy(op)


def _apply_work(op, state, pending):
    op=_operation(op)
    row=op['work']
    key=row['work_id']
    prior=state.get(key)
    if prior is None:
        require(op['expected_state'] is None and row['state']=='OBSERVED',
                'V8_CREATION_STATE_INVALID')
    else:
        require(op['expected_state']==prior['state'], 'V8_STATE_CONFLICT')
        require(all(row[k]==prior[k] for k in row if k not in MUTABLE),
                'V8_IMMUTABLE_WORK_CHANGED')
        require(row['attempts']>=prior['attempts'] and
                parse_utc(row['updated_at'])>=parse_utc(prior['updated_at']),
                'V8_PROGRESS_REVERSED')
        if row['state']!=prior['state']:
            candidate=deepcopy(prior)
            candidate['blocker']=row['blocker']
            expected=advance(candidate,row['state'],evidence_ids=row['evidence_ids'],now=row['updated_at'])
            require(expected['state']==row['state'], 'V8_TRANSITION_INVALID')
        else:
            require(op['outcome']!='LOCAL_COMMITTED', 'V8_NO_PROGRESS_OPERATION')
    outcome=op['outcome']
    if outcome=='EXTERNAL_INTENT':
        require(key not in pending and not any(
            state[other]['resource']==row['resource'] for other in pending),
            'V8_EXTERNAL_RECONCILIATION_REQUIRED')
        pending[key]=op['operation_id']
    elif outcome in {'EXTERNAL_CONFIRMED','EXTERNAL_UNKNOWN'}:
        require(key in pending, 'V8_EXTERNAL_INTENT_REQUIRED')
        if outcome=='EXTERNAL_CONFIRMED':
            del pending[key]
    else:
        require(key not in pending, 'V8_EXTERNAL_RECONCILIATION_REQUIRED')
    state[key]=row


class KernelJournal:
    def __init__(self,path,*,create=False,readonly=False):
        require(type(create) is bool and type(readonly) is bool and not(create and readonly),
                'V8_JOURNAL_MODE_INVALID')
        self.path=_private_path(path)
        self.readonly=readonly
        self.db=None
        fresh=not self.path.exists()
        require(not fresh or create, 'V8_JOURNAL_MISSING')
        if fresh:
            fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            os.close(fd)
        self.identity=(self.path.stat().st_dev,self.path.stat().st_ino)
        try:
            if not fresh:
                probe=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=5)
                try:
                    self._schema(probe)
                finally:
                    probe.close()
            mode='ro' if readonly else 'rw'
            self.db=sqlite3.connect(self.path.as_uri()+'?mode='+mode,uri=True,
                                    timeout=5,isolation_level=None)
            self.db.row_factory=sqlite3.Row
            if fresh:
                with self._transaction():
                    self.db.execute(SCHEMA)
                    self.db.execute('PRAGMA application_id='+str(APPLICATION_ID))
                    self.db.execute('PRAGMA user_version=1')
                fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
                try: os.fsync(fd)
                finally: os.close(fd)
            self._schema(self.db)
            if not readonly:
                self.db.execute('PRAGMA synchronous=FULL')
            self.replay()
        except (sqlite3.Error,OSError) as exc:
            self.close()
            raise BrainError('V8_JOURNAL_UNREADABLE') from exc
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _schema(db):
        require(db.execute('PRAGMA application_id').fetchone()[0]==APPLICATION_ID
                and db.execute('PRAGMA user_version').fetchone()[0]==1,
                'V8_FOREIGN_DATABASE_REFUSED')
        objects=db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        require(len(objects)==1 and tuple(objects[0])==('table','kernel_events',SCHEMA),
                'V8_JOURNAL_SCHEMA_INVALID')
        require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','V8_SQLITE_CORRUPT')

    @contextmanager
    def _transaction(self):
        require(not self.readonly,'V8_READONLY_JOURNAL')
        _private_path(self.path)
        require((self.path.stat().st_dev,self.path.stat().st_ino)==self.identity,
                'V8_JOURNAL_REPLACED')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _scan(self):
        rows=self.db.execute('SELECT * FROM kernel_events ORDER BY seq LIMIT ?',
                             (MAX_RECORDS+1,)).fetchall()
        require(len(rows)<=MAX_RECORDS,'V8_JOURNAL_RECORD_BOUND')
        records,state,pending=[],{},{}
        previous='0'*64
        for number,stored in enumerate(rows,1):
            require(stored['seq']==number and stored['prev_hash']==previous,
                    'V8_JOURNAL_SEQUENCE_OR_PARENT_INVALID')
            try: op=json.loads(stored['body'])
            except (ValueError,TypeError) as exc: raise BrainError('V8_JOURNAL_BODY_INVALID') from exc
            require(stored['body']==canonical(op) and stored['body_hash']==digest(op),
                    'V8_JOURNAL_BODY_TAMPERED')
            frame={k:stored[k] for k in ('seq','kind','operation_id','body_hash','prev_hash')}
            require(stored['chain_hash']==digest(frame),'V8_JOURNAL_CHAIN_TAMPERED')
            require(stored['kind']=='WORK' and stored['operation_id']==op.get('operation_id'),
                    'V8_JOURNAL_OPERATION_INVALID')
            _apply_work(op,state,pending)
            records.append(dict(sequence=number,kind=stored['kind'],operation=op,chain_hash=stored['chain_hash']))
            previous=stored['chain_hash']
        return records,state,pending

    def replay(self):
        try:
            return self._scan()[0]
        except sqlite3.Error as exc:
            raise BrainError('V8_JOURNAL_UNREADABLE') from exc

    @staticmethod
    def _receipt(record):
        return dict(sequence=record['sequence'],operation_id=record['operation']['operation_id'],
                    chain_hash=record['chain_hash'],scope=SCOPE,automatic_execution_authority=False,
                    reconciliation_required=record['operation']['outcome'] in {'EXTERNAL_INTENT','EXTERNAL_UNKNOWN'})

    def append(self,operation):
        op=_operation(operation)
        with self._transaction():
            records,state,pending=self._scan()
            for record in records:
                if record['operation']['operation_id']==op['operation_id']:
                    require(record['operation']==op,'V8_OPERATION_IDEMPOTENCY_CONFLICT')
                    return self._receipt(record)
            require(len(records)<MAX_RECORDS,'V8_JOURNAL_RECORD_BOUND')
            _apply_work(op,state,pending)
            sequence=len(records)+1
            previous=records[-1]['chain_hash'] if records else '0'*64
            frame=dict(seq=sequence,kind='WORK',operation_id=op['operation_id'],
                       body_hash=digest(op),prev_hash=previous)
            chain=digest(frame)
            self.db.execute('INSERT INTO kernel_events VALUES(?,?,?,?,?,?,?)',
                (sequence,'WORK',op['operation_id'],canonical(op),digest(op),previous,chain))
            return self._receipt(dict(sequence=sequence,operation=op,chain_hash=chain))

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db=None

    def __enter__(self): return self
    def __exit__(self,*args): self.close()
