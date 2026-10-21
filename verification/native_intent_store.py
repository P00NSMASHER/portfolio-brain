"""Private persistent native-enrollment intents, with no GitHub write authority.

Records are sticky by repository/PR, independent of labels and candidate heads.
SQLite transactions serialize claims; committing ATTEMPTED precedes any external
POST. A lost response or process cannot authorize a second attempt. This ledger
is trusted local storage, NOT an independent approval issuer or rollback-proof
vault. The protected final-check publisher is intentionally not modified here.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from verification import native_final_approval as approval

APPLICATION_ID = 0x424E4931
MAX_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 10000
MAX_INTENTS = 1000
HASH = re.compile(r'[0-9a-f]{64}\Z')
CODE = re.compile(r'[A-Z][A-Z0-9_]{0,63}\Z')
SCHEMA = (
    'CREATE TABLE meta (slot INTEGER PRIMARY KEY CHECK(slot=1), store_id TEXT NOT NULL)',
    'CREATE TABLE intents (pr INTEGER PRIMARY KEY, body TEXT NOT NULL, body_hash TEXT NOT NULL)',
    'CREATE TABLE events (seq INTEGER PRIMARY KEY, pr INTEGER NOT NULL, state TEXT NOT NULL, '
    'evidence TEXT NOT NULL, prev_hash TEXT NOT NULL, chain_hash TEXT NOT NULL)',
) + tuple(
    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
    "BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END"
    for table in ('meta', 'intents', 'events') for action in ('UPDATE', 'DELETE')
)
NEXT = {
    None: {'PREPARED'}, 'PREPARED': {'ATTEMPTED', 'REVOKED'},
    'ATTEMPTED': {'ENROLLED', 'DENIED', 'UNKNOWN', 'REVOKED'},
    'UNKNOWN': {'ENROLLED', 'DENIED', 'REVOKED'},
    'ENROLLED': {'REVOKED'}, 'DENIED': {'REVOKED'}, 'REVOKED': set(),
}


class StoreDenied(ValueError):
    """Sanitized local hold; never implies a safe external retry."""


def need(ok, code):
    if not ok:
        raise StoreDenied(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def hash_ok(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def number_ok(value):
    return type(value) is int and 0 < value < 10**15


def validate_ticket(ticket, source, policy, now):
    try:
        approval._ticket(ticket, source, policy, now)
    except Exception:
        raise StoreDenied('TICKET_OR_CURRENT_AUTHORITY_INVALID') from None


def private_path(path, *, existing=True):
    need(os.name in ('posix', 'nt'), 'PRIVATE_STORAGE_PLATFORM_UNVERIFIED')
    path = Path(os.path.abspath(path))
    need(not any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)()
                 for p in (path, *path.parents)), 'SYMLINK_OR_JUNCTION_REFUSED')
    parent = path.parent.stat()
    need(stat.S_ISDIR(parent.st_mode), 'PRIVATE_PARENT_REQUIRED')
    if os.name == 'nt':
        from verification.native_windows_acl import verify_private_acl
        verify_private_acl(path.parent)
    else:
        need(parent.st_uid == os.getuid() and parent.st_mode & 0o077 == 0, 'PRIVATE_PARENT_REQUIRED')
    if existing:
        st = path.stat()
        need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size <= MAX_BYTES,
             'PRIVATE_REGULAR_STORE_REQUIRED')
        if os.name == 'nt':
            verify_private_acl(path)
        else:
            need(st.st_uid == os.getuid() and st.st_mode & 0o077 == 0, 'PRIVATE_REGULAR_STORE_REQUIRED')
    return path


@dataclass(frozen=True)
class Record:
    ticket: dict
    state: str
    digest: str
    version: int
    evidence: str


class IntentStore:
    """One durable intent per PR; re-approval requires a fresh governed PR."""

    @classmethod
    def create(cls, path, *, store_id):
        need(hash_ok(store_id), 'STORE_ID_INVALID')
        db = None
        try:
            path = private_path(path, existing=False)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            os.close(fd)
            db = sqlite3.connect(path, timeout=2, isolation_level=None)
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            db.execute('PRAGMA user_version=1')
            for sql in SCHEMA: db.execute(sql)
            db.execute('INSERT INTO meta VALUES (1, ?)', (store_id,))
            db.execute('COMMIT'); db.close(); db = None
            # SQLite FULL synchronizes commits. Also flush creation on POSIX.
            if os.name == 'posix':
                fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try: os.fsync(fd)
                finally: os.close(fd)
            return cls(path, expected_store_id=store_id)
        except StoreDenied:
            raise
        except (OSError, sqlite3.Error, ValueError):
            raise StoreDenied('STORE_CREATE_FAILED_NO_OVERWRITE') from None
        finally:
            if db is not None: db.close()

    def __init__(self, path, *, expected_store_id):
        self.db = None
        need(hash_ok(expected_store_id), 'STORE_ID_INVALID')
        self.store_id = expected_store_id
        try:
            self.path = private_path(path)
            st = self.path.stat(); self.identity = (st.st_dev, st.st_ino)
            fd = os.open(self.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
            try: header = os.read(fd, 100)
            finally: os.close(fd)
            need(len(header) == 100 and header[:16] == b'SQLite format 3\0'
                 and header[18:20] == b'\x01\x01'
                 and int.from_bytes(header[68:72], 'big') == APPLICATION_ID
                 and int.from_bytes(header[60:64], 'big') == 1, 'STORE_FORMAT_UNVERIFIED')
            self.db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True,
                                      timeout=2, isolation_level=None)
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA trusted_schema=OFF')
            with self._transaction(): pass
        except StoreDenied:
            self.close(); raise
        except (OSError, sqlite3.Error, ValueError):
            self.close(); raise StoreDenied('STORE_OPEN_FAILED_NO_RECREATE') from None

    def close(self):
        if self.db is not None:
            self.db.close(); self.db = None

    def __enter__(self): return self

    def __exit__(self, *args): self.close()

    def _identity(self):
        need(self.db is not None, 'STORE_CLOSED')
        private_path(self.path)
        st = self.path.stat()
        need((st.st_dev, st.st_ino) == self.identity, 'STORE_REPLACED')

    @contextmanager
    def _transaction(self, *, write=False):
        try:
            self._identity()
            self.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            snapshot = self._snapshot()
            yield snapshot
            self._identity()
            self.db.execute('COMMIT')
        except Exception as exc:
            if self.db is not None and self.db.in_transaction: self.db.execute('ROLLBACK')
            if isinstance(exc, StoreDenied): raise
            raise StoreDenied('STORE_IO_OR_INTEGRITY_UNVERIFIED') from None

    def _snapshot(self):
        schema = {row[0].strip().rstrip(';') for row in self.db.execute(
            "SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        need(schema == set(SCHEMA), 'STORE_SCHEMA_CHANGED')
        need(self.db.execute('SELECT slot, store_id FROM meta').fetchall()
             == [(1, self.store_id)], 'STORE_ID_MISMATCH')
        raw = self.db.execute('SELECT pr, body, body_hash FROM intents ORDER BY pr LIMIT ?',
                              (MAX_INTENTS + 1,)).fetchall()
        need(len(raw) <= MAX_INTENTS, 'STORE_INTENT_BOUND')
        tickets = {}
        for pr, body, body_hash in raw:
            need(number_ok(pr) and type(body) is str and len(body) <= 8192
                 and hash_ok(body_hash) and digest(body) == body_hash, 'STORE_TICKET_CORRUPT')
            t = json.loads(body)
            need(type(t) is dict and canonical(t) == body and t.get('pr_number') == pr,
                 'STORE_TICKET_CORRUPT')
            validate_ticket(t, t.get('controller_source_sha'), t.get('policy_sha'),
                            approval._utc(t.get('issued_at')))
            tickets[pr] = (t, body_hash)
        events = self.db.execute('SELECT seq, pr, state, evidence, prev_hash, chain_hash '
                                'FROM events ORDER BY seq LIMIT ?', (MAX_EVENTS + 1,)).fetchall()
        need(len(events) <= MAX_EVENTS, 'STORE_EVENT_BOUND')
        states = {}; previous = '0' * 64
        for expected, (seq, pr, state, evidence, prev, chain) in enumerate(events, 1):
            need(seq == expected and pr in tickets and type(state) is str
                 and type(evidence) is str and prev == previous and hash_ok(chain),
                 'STORE_EVENT_CORRUPT')
            old = states.get(pr)
            need(state in NEXT[old.state if old else None], 'STORE_TRANSITION_CORRUPT')
            need((state in ('PREPARED', 'ATTEMPTED') and evidence == '')
                 or (state == 'REVOKED' and CODE.fullmatch(evidence) is not None)
                 or (state in ('ENROLLED', 'DENIED', 'UNKNOWN') and hash_ok(evidence)),
                 'STORE_EVENT_EVIDENCE_INVALID')
            t, body_hash = tickets[pr]
            need(chain == digest(canonical([self.store_id, seq, pr, body_hash, state,
                                             evidence, prev])), 'STORE_HASH_CHAIN_INVALID')
            states[pr] = Record(t, state, body_hash, seq, evidence); previous = chain
        need(set(states) == set(tickets), 'STORE_ORPHAN_INTENT')
        return states, len(events), previous

    def _append(self, snapshot, pr, ticket, body_hash, state, evidence=''):
        states, count, previous = snapshot
        need(count < MAX_EVENTS, 'STORE_EVENT_BOUND')
        old = states.get(pr)
        need(state in NEXT[old.state if old else None], 'INTENT_TRANSITION_DENIED')
        seq = count + 1
        chain = digest(canonical([self.store_id, seq, pr, body_hash, state, evidence, previous]))
        self.db.execute('INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)',
                        (seq, pr, state, evidence, previous, chain))
        return Record(json.loads(canonical(ticket)), state, body_hash, seq, evidence)

    def prepare(self, ticket, *, expected_source_sha, expected_policy_sha, now):
        need(type(ticket) is dict, 'TICKET_INVALID')
        ticket = dict(ticket)
        validate_ticket(ticket, expected_source_sha, expected_policy_sha, now)
        body = canonical(ticket); body_hash = digest(body); pr = ticket['pr_number']
        with self._transaction(write=True) as snapshot:
            states = snapshot[0]
            if pr in states:
                need(states[pr].digest == body_hash, 'INTENT_ALREADY_EXISTS_DIFFERENT_TICKET')
                return states[pr]
            need(len(states) < MAX_INTENTS, 'STORE_INTENT_BOUND')
            self.db.execute('INSERT INTO intents VALUES (?, ?, ?)', (pr, body, body_hash))
            return self._append(snapshot, pr, ticket, body_hash, 'PREPARED')

    @staticmethod
    def _record(snapshot, pr, expected_digest=None):
        need(number_ok(pr), 'PR_NUMBER_INVALID')
        item = snapshot[0].get(pr)
        need(item is not None, 'INTENT_MISSING')
        if expected_digest is not None:
            need(hash_ok(expected_digest) and item.digest == expected_digest, 'INTENT_BINDING_CHANGED')
        return item

    def load(self, pr):
        with self._transaction() as snapshot: return self._record(snapshot, pr)

    def event_count(self):
        with self._transaction() as snapshot: return snapshot[1]

    def claim(self, pr, expected_digest, *, expected_source_sha, expected_policy_sha, now):
        with self._transaction(write=True) as snapshot:
            item = self._record(snapshot, pr, expected_digest)
            validate_ticket(item.ticket, expected_source_sha, expected_policy_sha, now)
            need(item.state == 'PREPARED', 'INTENT_ALREADY_ATTEMPTED_NO_RETRY')
            return self._append(snapshot, pr, item.ticket, item.digest, 'ATTEMPTED')

    def record_result(self, pr, expected_digest, state, evidence_hash):
        need(type(state) is str and state in ('ENROLLED', 'DENIED', 'UNKNOWN')
             and hash_ok(evidence_hash), 'RESULT_EVIDENCE_INVALID')
        with self._transaction(write=True) as snapshot:
            item = self._record(snapshot, pr, expected_digest)
            if item.state == state and item.evidence == evidence_hash: return item
            need(item.state in ('ATTEMPTED', 'UNKNOWN'), 'RESULT_TRANSITION_DENIED')
            return self._append(snapshot, pr, item.ticket, item.digest, state, evidence_hash)

    def revoke(self, pr, expected_digest, reason):
        need(type(reason) is str and CODE.fullmatch(reason) is not None, 'REVOCATION_REASON_INVALID')
        with self._transaction(write=True) as snapshot:
            item = self._record(snapshot, pr, expected_digest)
            if item.state == 'REVOKED' and item.evidence == reason: return item
            return self._append(snapshot, pr, item.ticket, item.digest, 'REVOKED', reason)


def verify_recorded_approval(read, store, *, pr_number, expected_source_sha, expected_policy_sha, now):
    """Use persisted intent, never a generic-success fallback, for the final gate.

    This adapter does not publish a check; integration into the trusted publisher
    and a persistent service deployment must be independently governed.
    """
    reads = 0
    try:
        original = store.load(pr_number)
        need(original.state == 'ENROLLED', 'INTENT_NOT_CONFIRMED_ENROLLED')
        result = approval.verify_final_approval(
            read, original.ticket, expected_source_sha=expected_source_sha,
            expected_policy_sha=expected_policy_sha, now=now)
        reads = result.reads
        need(store.load(pr_number) == original, 'INTENT_CHANGED_DURING_VERIFICATION')
        return result
    except StoreDenied as exc:
        return approval.Result('HOLD', str(exc), reads)
    except Exception:
        return approval.Result('HOLD', 'INTENT_STORE_UNVERIFIED', reads)
