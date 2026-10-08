"""Read-only, byte-level replay of the live Brain v4 SQLite authority.

Evidence-only CI check. Never publishes state or judges the six-hour soak.
Run on an isolated PR branch; do not merge into production during v4.
"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = "P00NSMASHER/portfolio-brain"
SOURCE = "9fc08c72e2d050359e7f119bfcbfb82b23f95b5b"
BRANCH = "refs/heads/brain-state-v2"

def git(*args, binary=False):
    data = subprocess.check_output(["git", *args], stderr=subprocess.PIPE)
    return data if binary else data.decode("utf-8").strip()

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def sha(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()

def stamp(value):
    assert isinstance(value, str) and value.endswith("Z"), "non-UTC timestamp"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

class IndependentRawSqliteV4(unittest.TestCase):
    def test_live_state_binary_and_canonical_replay(self):
        # Prevent a PR running after protected production main has moved.
        actual_main = git("ls-remote", "origin", "refs/heads/main").split()[0]
        self.assertEqual(actual_main, SOURCE, "protected main drift: no replay acceptance")

        # Git verifies the remote objects. Read exactly one immutable state commit.
        git("fetch", "--quiet", "--no-tags", "origin", BRANCH)
        state_commit = git("rev-parse", "FETCH_HEAD")
        self.assertRegex(state_commit, r"^[0-9a-f]{40}$")
        blob = git("rev-parse", f"{state_commit}:state.sqlite")
        raw = git("show", f"{state_commit}:state.sqlite", binary=True)
        self.assertTrue(raw.startswith(b"SQLite format 3\x00"))
        calculated_blob = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\x00" + raw
        ).hexdigest()
        self.assertEqual(blob, calculated_blob, "Git object / raw byte identity mismatch")
        raw_sha256 = hashlib.sha256(raw).hexdigest()

        # Re-verify that the public source has not changed during retrieval.
        self.assertEqual(git("ls-remote", "origin", "refs/heads/main").split()[0], SOURCE)
        with tempfile.TemporaryDirectory(prefix="brain-v4-replay-") as td:
            database = Path(td) / "state.sqlite"
            database.write_bytes(raw)
            os.chmod(database, 0o600)
            with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchall()[0][0], "ok")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                meta = dict(db.execute("SELECT key,value FROM meta"))
                self.assertEqual(meta["schema_version"], "2")
                self.assertEqual(meta["visibility"], "PUBLIC")
                rows = db.execute("SELECT seq,id,body,hash,status,received_at FROM events ORDER BY seq").fetchall()
                self.assertGreater(len(rows), 0)
                watermark = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
                self.assertIsNotNone(watermark)
                self.assertEqual(watermark[0], len(rows), "event tail missing")
                ledger = {r["seq"]:r for r in db.execute("SELECT seq,prev_hash,chain_hash FROM ledger")}
                self.assertEqual(len(ledger), len(rows), "missing/orphan ledger entry")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE status='PENDING'").fetchone()[0], 0)
                previous = "0" * 64
                for number, row in enumerate(rows, 1):
                    self.assertEqual(row["seq"], number, "event sequence gap")
                    self.assertEqual(row["status"], "APPLIED")
                    event = json.loads(row["body"])
                    self.assertEqual(canonical(event), row["body"], "event not canonical JSON")
                    self.assertEqual(event["id"], row["id"], "durable event identity mismatch")
                    self.assertEqual(sha(event), row["hash"], "event hash mismatch")
                    self.assertLessEqual(stamp(event["observed_at"]), stamp(row["received_at"]))
                    self.assertRegex(event["source_sha"], r"^[0-9a-f]{40}$")
                    item = ledger[number]
                    self.assertEqual(item["prev_hash"], previous, "ledger parent broken")
                    expected = sha({"seq":number,"event_hash":row["hash"],"previous":previous})
                    self.assertEqual(item["chain_hash"], expected, "canonical hash replay mismatch")
                    previous = expected

                report_row = db.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 1").fetchone()
                self.assertIsNotNone(report_row)
                report = json.loads(report_row["body"])
                self.assertEqual(canonical(report), report_row["body"], "noncanonical latest report")
                self.assertEqual(sha(report), report_row["hash"], "latest report hash mismatch")
                self.assertEqual(report_row["seq"], len(rows))
                self.assertEqual(report_row["chain_hash"], previous)
                self.assertEqual(report_row["source_sha"], SOURCE)
                self.assertEqual(report["state_sequence"], len(rows))
                self.assertEqual(report["canonical_hash"], previous)
                self.assertEqual(report["pending_events"], 0)
                self.assertEqual(report["status"], "PASS")
                self.assertEqual(report["source_sha"], SOURCE)
                self.assertEqual(report["learning"]["events"], len(rows))
                self.assertEqual(report["generated_at"], report_row["created_at"])
                mandatory = {}
                for op in ("monitor", "research", "experiment"):
                    attempt = db.execute(
                        "SELECT * FROM attempts WHERE operation=? ORDER BY id DESC LIMIT 1",(op,)
                    ).fetchone()
                    self.assertIsNotNone(attempt, op + " attempt missing")
                    self.assertEqual(attempt["status"], "PASS", op + " failed")
                    self.assertEqual(attempt["source_sha"], SOURCE, op + " source drift")
                    mandatory[op] = attempt["id"]
                self.assertLess(mandatory["monitor"], mandatory["research"])
                self.assertLess(mandatory["research"], mandatory["experiment"])

        # The state branch might advance while this isolated read is running.
        # This proof is attached to state_commit, never to an unnamed "latest".
        proof = {
            "status":"PASS_RAW_SQLITE_BYTE_AND_LEDGER_REPLAY",
            "scope":"INDEPENDENT_READ_ONLY_GITHUB_CI",
            "source_sha":SOURCE, "state_commit":state_commit,
            "sqlite_git_blob":blob, "sqlite_sha256":raw_sha256,
            "sqlite_bytes":len(raw), "event_sequence":len(rows),
            "canonical_chain_hash":previous, "pending_events":0,
            "latest_report":"PASS", "mandatory_attempts":"PASS",
            "integrity_check":"ok", "foreign_key_check":"ok",
            "six_hour_soak_accepted":False,
            "raw_bytes_in_artifact":False
        }
        print("INDEPENDENT_V4_SQLITE_REPLAY_RECEIPT=" + json.dumps(proof,sort_keys=True))

if __name__=="__main__":
    unittest.main()
