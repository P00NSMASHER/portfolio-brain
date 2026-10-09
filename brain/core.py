"""One durable authority: a SQLite inbox, immutable ledger, and derived reports.

Acknowledged input is committed before processing. Each reduction is synchronous
inside BEGIN IMMEDIATE; readers never wait for a remote reducer. Reports are
rebuilt from the ledger and verified before being returned.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

class BrainError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise BrainError(message)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

def timestamp(value):
    require(isinstance(value, str) and value.endswith("Z"), "timestamp must be explicit UTC Z")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BrainError("invalid timestamp") from exc
    require(result.tzinfo is not None, "timezone missing")
    return result

KINDS = {"repository", "candidate", "experiment", "feedback", "holdings"}


def same_semantic_observation(prior, current):
    """Same kind/key/time cannot relabel the same payload or visibility.

    Producer/source revisions can differ for a legitimate identical replay;
    the observed payload and its factual/private provenance cannot differ.
    """
    return (
        prior["payload"] == current["payload"]
        and prior["data_kind"] == current["data_kind"]
        and prior["visibility"] == current["visibility"]
    )


def analyze_events(events, *, now, max_age):
    """Single deterministic projection shared by report creation and replay."""
    from brain.intelligence import build_report
    from brain.changes import repository_changes

    report = build_report(events, now=now, max_age=max_age)
    report["repository_changes"] = repository_changes(events, now=now, max_age=max_age)
    return report

def validate_event(event, now):
    require(type(event) is dict and set(event) == {"id", "kind", "key", "observed_at", "source_sha", "visibility", "data_kind", "payload"}, "event fields invalid")
    require(isinstance(event["id"], str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", event["id"]), "invalid event id")
    require(event["kind"] in KINDS and isinstance(event["key"], str) and 0 < len(event["key"]) <= 200, "invalid event kind/key")
    require(event["visibility"] in {"PUBLIC", "PRIVATE"}, "visibility invalid")
    require(event["data_kind"] in {"ACTUAL", "SIMULATED", "ESTIMATED"}, "data kind invalid")
    require(isinstance(event["source_sha"], str) and re.fullmatch(r"[0-9a-f]{40}", event["source_sha"]), "exact source SHA required")
    require(0 <= (timestamp(now)-timestamp(event["observed_at"])).total_seconds(), "future observation rejected")
    require(type(event["payload"]) is dict and len(canonical(event)) <= 1_000_000, "event payload invalid/too large")
    from brain.intelligence import validate_payload
    validate_payload(event["kind"], event["payload"], event["observed_at"])
    if event['kind']=='experiment':
        require(event['data_kind']=='SIMULATED', 'experiment data must be labelled simulated')
    if event['kind']=='holdings' and any(q['data_kind']=='SIMULATED' for q in event['payload']['quotes'].values()):
        require(event['data_kind']=='SIMULATED', 'synthetic quotes cannot be presented as actual holdings valuation')

class Store:
    def __init__(self, path, *, visibility="PRIVATE"):
        require(visibility in {"PUBLIC", "PRIVATE"}, "database visibility invalid")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
          id TEXT UNIQUE NOT NULL, body TEXT NOT NULL, hash TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('PENDING','APPLIED')), received_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ledger(seq INTEGER PRIMARY KEY REFERENCES events(seq),
          prev_hash TEXT NOT NULL, chain_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT,
          seq INTEGER NOT NULL, chain_hash TEXT NOT NULL, source_sha TEXT NOT NULL,
          created_at TEXT NOT NULL, body TEXT NOT NULL, hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL, operation TEXT NOT NULL, status TEXT NOT NULL, error_class TEXT, source_sha TEXT, event_seq INTEGER, details TEXT NOT NULL);
        ''')
        with self.transaction():
            row = self.db.execute("SELECT value FROM meta WHERE key='visibility'").fetchone()
            if row is None:
                self.db.execute("INSERT INTO meta VALUES('visibility',?)", (visibility,))
            else:
                require(row[0] == visibility, "database visibility cannot be silently changed")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema_version','2')")
            require(self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '2', "unsupported state schema")
        self.visibility = visibility

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def submit(self, events, *, now=None):
        now = now or utcnow()
        require(type(events) is list and 0 < len(events) <= 100, "batch must contain 1..100 events")
        for event in events:
            validate_event(event, now)
            require(self.visibility == "PRIVATE" or event["visibility"] == "PUBLIC", "private input rejected by public state")
        with self.transaction():
            for event in events:
                conflicts=self.db.execute("SELECT body FROM events WHERE json_extract(body,'$.kind')=? AND json_extract(body,'$.key')=? AND json_extract(body,'$.observed_at')=?", (event['kind'],event['key'],event['observed_at'])).fetchall()
                require(
                    all(same_semantic_observation(json.loads(row[0]), event) for row in conflicts),
                    "AMBIGUOUS_OBSERVATION: conflicting payload or evidence label at same source time",
                )
                body, value_hash = canonical(event), digest(event)
                old = self.db.execute("SELECT hash FROM events WHERE id=?", (event["id"],)).fetchone()
                if old:
                    require(old[0] == value_hash, "IDEMPOTENCY_CONFLICT: event id reused with different content")
                else:
                    self.db.execute("INSERT INTO events(id,body,hash,status,received_at) VALUES(?,?,?,'PENDING',?)", (event["id"], body, value_hash, now))
        return self.pending()

    def pending(self):
        return self.db.execute("SELECT count(*) FROM events WHERE status='PENDING'").fetchone()[0]

    def _verified_events(self, *, include_pending=False):
        require(self.db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "STATE_CORRUPT: SQLite check failed")
        rows = self.db.execute("SELECT e.*,l.prev_hash,l.chain_hash FROM events e LEFT JOIN ledger l USING(seq) ORDER BY seq").fetchall()
        watermark=self.db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
        maximum=rows[-1]['seq'] if rows else 0
        require((watermark[0] if watermark else 0)==maximum, 'EVENT_LOSS: committed inbox tail missing')
        previous, seq, events = "0"*64, 0, []
        pending_seen=False
        seen_semantic = {}
        require(self.db.execute("SELECT count(*) FROM ledger").fetchone()[0] == sum(row["status"]=="APPLIED" for row in rows), "STATE_CORRUPT: orphan ledger entry")
        for row in rows:
            require(row["seq"] == seq+1, "EVENT_GAP: ledger sequence is not contiguous")
            seq = row["seq"]
            event = json.loads(row["body"])
            require(row["id"] == event.get("id"), "STATE_CORRUPT: durable event identity mismatch")
            require(row["hash"] == digest(event), "STATE_CORRUPT: event hash mismatch")
            validate_event(event, row["received_at"])
            require(self.visibility == "PRIVATE" or event["visibility"] == "PUBLIC", "private event in public database")
            identity = (event["kind"], event["key"], event["observed_at"])
            prior = seen_semantic.setdefault(identity, event)
            require(
                same_semantic_observation(prior, event),
                "AMBIGUOUS_OBSERVATION: inconsistent durable evidence classification",
            )
            if row["status"] == "PENDING":
                pending_seen=True
                require(row["chain_hash"] is None and row["prev_hash"] is None, "pending event already has a ledger record")
                require(include_pending, "PENDING_EVENTS: drain before dependent reads")
            else:
                require(not pending_seen, "STATE_CORRUPT: applied event after unprocessed gap")
                require(row["prev_hash"] == previous, "STATE_CORRUPT: broken ledger chain")
                expected = digest({"seq":seq, "event_hash":row["hash"], "previous":previous})
                require(row["chain_hash"] == expected, "STATE_CORRUPT: chain digest mismatch")
                previous = expected
                events.append(event)
        return events, seq, previous

    def drain(self, *, fault=None):
        with self.transaction():
            self._verified_events(include_pending=True)
            previous = self.db.execute("SELECT chain_hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
            previous = previous[0] if previous else "0"*64
            rows = self.db.execute("SELECT * FROM events WHERE status='PENDING' ORDER BY seq").fetchall()
            for row in rows:
                chain = digest({"seq":row["seq"], "event_hash":row["hash"], "previous":previous})
                self.db.execute("INSERT INTO ledger VALUES(?,?,?)", (row["seq"], previous, chain))
                self.db.execute("UPDATE events SET status='APPLIED' WHERE seq=?", (row["seq"],))
                previous = chain
                if fault:
                    fault(row["seq"])
            self._verified_events()
        return len(rows)

    def report(self, source_sha, *, now=None, max_age=172800):
        now = now or utcnow()
        require(re.fullmatch(r"[0-9a-f]{40}", source_sha or ""), "report exact source SHA required")
        require(type(max_age) is int and 0 < max_age <= 172800, "freshness threshold out of bounds")
        with self.transaction():
            events, seq, chain = self._verified_events()
            report = analyze_events(events, now=now, max_age=max_age)
            report.update(source_sha=source_sha, state_sequence=seq, canonical_hash=chain, pending_events=0, generated_at=now)
            encoded = canonical(report)
            self.db.execute("INSERT INTO reports(seq,chain_hash,source_sha,created_at,body,hash) VALUES(?,?,?,?,?,?)", (seq,chain,source_sha,now,encoded,digest(report)))
        return report

    def read_report(self, source_sha, *, now=None, max_age=172800):
        now = now or utcnow()
        with self.transaction():
            events, seq, chain = self._verified_events()
            row = self.db.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 1").fetchone()
            require(row is not None, "MISSING_REPORT")
            report = json.loads(row["body"])
            require(row["hash"] == digest(report), "STATE_CORRUPT: report hash mismatch")
            from brain.intelligence import build_report
            replay=analyze_events(events, now=row['created_at'], max_age=max_age)
            replay.update(source_sha=row['source_sha'], state_sequence=row['seq'], canonical_hash=row['chain_hash'], pending_events=0, generated_at=row['created_at'])
            require(replay == report, "STATE_CORRUPT: report does not match deterministic ledger replay")
            require(row["seq"] == seq and row["chain_hash"] == chain, "STALE_REPORT: new events require new analysis")
            require(row["source_sha"] == source_sha, "SOURCE_SHA_CHANGED: rerun analysis for current code")
            require(0 <= (timestamp(now)-timestamp(row["created_at"])).total_seconds() <= max_age, "STALE_REPORT: generated_at expired")
            require(report["status"] == "PASS", "report does not pass semantic freshness and completeness")
            require(all(0 <= (timestamp(now)-timestamp(x)).total_seconds() <= max_age for x in report["semantic_timestamps"]), "STALE_SOURCE: wrapper cannot freshen evidence")
            return report

    def attempt(self, operation, status, error_class=None, *, source_sha=None, details=None):
        require(status in {"PASS", "FAIL"}, "attempt status invalid")
        with self.transaction():
            self.db.execute("INSERT INTO attempts(created_at,operation,status,error_class,source_sha,event_seq,details) VALUES(?,?,?,?,?,?,?)", (utcnow(),operation,status,error_class,source_sha,self.db.execute("SELECT coalesce(max(seq),0) FROM events").fetchone()[0],canonical(details or {})))

    def backup(self, destination):
        destination = Path(destination)
        require(destination.resolve() != self.path.resolve(), "backup must use another file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as other:
            self.db.backup(other)
            require(other.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "backup verification failed")
        os.chmod(destination, 0o600)
        return hashlib.sha256(destination.read_bytes()).hexdigest()
