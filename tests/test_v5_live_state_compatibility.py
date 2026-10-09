"""V5 compatibility with REAL immutable v4-origin production SQLite bytes.

An isolated CI test. GitHub Foundation runners provide networked Git transport;
the separately sandboxed independent App has no network, so it MUST skip the
remote retrieval instead of manufacturing a pass. No writes to live Git state,
protected source, existing acceptance records or the fetched original bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from brain.core import Store, canonical, digest, utcnow

PRODUCTION = "9fc08c72e2d050359e7f119bfcbfb82b23f95b5b"
STATE_REF = "refs/heads/brain-state-v2"


def git(*args, raw=False):
    value = subprocess.check_output(
        ["git", *args], stderr=subprocess.PIPE, timeout=35
    )
    return value if raw else value.decode("utf-8").strip()


def physical_ledger_snapshot(path):
    """Independent immutable/RO verification before invoking V5 application code."""
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        meta = {row["key"]: row["value"]
                for row in db.execute("SELECT key,value FROM meta")}
        assert meta["visibility"] == "PUBLIC"
        assert meta["schema_version"] == "2"
        rows = db.execute(
            "SELECT seq,id,body,hash,status,received_at FROM events ORDER BY seq"
        ).fetchall()
        assert rows, "Empty production SQLite cannot prove V5 compatibility"
        watermark = db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='events'"
        ).fetchone()
        assert watermark is not None and watermark[0] == len(rows)
        ledger = {
            x["seq"]: x
            for x in db.execute("SELECT seq,prev_hash,chain_hash FROM ledger")
        }
        assert len(ledger) == len(rows)
        previous = "0" * 64
        for sequence, row in enumerate(rows, 1):
            assert row["seq"] == sequence
            assert row["status"] == "APPLIED"
            event = json.loads(row["body"])
            assert row["id"] == event["id"]
            assert canonical(event) == row["body"]
            assert digest(event) == row["hash"]
            entry = ledger[sequence]
            assert entry["prev_hash"] == previous
            expected = digest({
                "seq": sequence,
                "event_hash": row["hash"],
                "previous": previous,
            })
            assert entry["chain_hash"] == expected
            previous = expected
        assert db.execute(
            "SELECT count(*) FROM events WHERE status='PENDING'"
        ).fetchone()[0] == 0
        last = db.execute(
            "SELECT seq,chain_hash,source_sha,body,hash,created_at "
            "FROM reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert last is not None
        old_report = json.loads(last["body"])
        assert canonical(old_report) == last["body"]
        assert digest(old_report) == last["hash"]
        assert last["source_sha"] == PRODUCTION
        assert old_report["source_sha"] == PRODUCTION
        assert last["seq"] == len(rows)
        assert last["chain_hash"] == previous
        assert old_report["canonical_hash"] == previous
        assert old_report["state_sequence"] == len(rows)
        assert old_report["status"] == "PASS"
        assert old_report["pending_events"] == 0
        attempts = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
        reports = db.execute("SELECT count(*) FROM reports").fetchone()[0]
        return {
            "sequence": len(rows),
            "canonical_hash": previous,
            "reports": reports,
            "attempts": attempts,
            "legacy_report_hash": last["hash"],
            "legacy_report_created_at": last["created_at"],
            "legacy_report_source": last["source_sha"],
        }


class RealStateV5Compatibility(unittest.TestCase):
    def test_current_production_sqlite_replays_as_v5_on_disposable_copy(self):
        if os.environ.get("GITHUB_ACTIONS") != "true":
            self.skipTest(
                "OFFLINE_INDEPENDENT_SANDBOX: only networked GitHub Foundation "
                "may issue a raw production SQLite replay receipt"
            )

        # The old source is an immutable acceptance identity. The V5 CI can
        # read state but must never imply V5 has been deployed or accepted.
        self.assertEqual(
            git("ls-remote", "origin", "refs/heads/main").split()[0],
            PRODUCTION,
            "Original v4 protected source changed; no compatibility claim",
        )
        # checkout@v4 on pull_request normally checks out GitHub's virtual
        # merge commit, not the PR's reviewed head. Bind BOTH identities and
        # require byte-identical source trees instead of misnaming the merge.
        self.assertEqual(os.environ.get("GITHUB_EVENT_NAME"), "pull_request")
        branch = "refs/heads/integration/portfolio-brain-v5-candidate-20261008"
        checkout_commit = git("rev-parse", "HEAD")
        branch_tip = git("ls-remote", "origin", branch).split()[0]
        self.assertRegex(branch_tip, r"^[0-9a-f]{40}$")
        git("fetch", "--quiet", "--no-tags", "origin", branch)
        candidate = git("rev-parse", "FETCH_HEAD")
        self.assertEqual(candidate, branch_tip, "PR head advanced during acquisition")
        self.assertNotEqual(candidate, PRODUCTION)
        checkout_tree = git("rev-parse", "HEAD^{tree}")
        candidate_tree = git("rev-parse", f"{candidate}^{{tree}}")
        self.assertEqual(checkout_tree, candidate_tree, "PR checkout tree differs from reviewed PR head")
        if checkout_commit != candidate:
            parents = [
                line.removeprefix("parent ")
                for line in git("cat-file", "-p", "HEAD").splitlines()
                if line.startswith("parent ")
            ]
            self.assertEqual(
                parents, [PRODUCTION, candidate],
                "PR virtual merge must derive from frozen main and exact PR head",
            )
            checkout_kind = "GITHUB_PULL_REQUEST_MERGE_SAME_TREE"
        else:
            checkout_kind = "EXACT_PULL_REQUEST_HEAD"
        git("fetch", "--quiet", "--no-tags", "origin", STATE_REF)
        state_commit = git("rev-parse", "FETCH_HEAD")
        self.assertRegex(state_commit, r"^[0-9a-f]{40}$")
        blob = git("rev-parse", f"{state_commit}:state.sqlite")
        raw = git("show", f"{state_commit}:state.sqlite", raw=True)
        self.assertTrue(raw.startswith(b"SQLite format 3\x00"))
        self.assertEqual(
            blob,
            hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\x00" + raw
            ).hexdigest(),
            "Git object byte proof failed",
        )
        raw_digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(
            git("ls-remote", "origin", "refs/heads/main").split()[0],
            PRODUCTION,
            "Protected main changed during snapshot acquisition",
        )
        self.assertEqual(
            git("ls-remote", "origin", branch).split()[0],
            candidate,
            "PR head moved during snapshot acquisition",
        )

        with tempfile.TemporaryDirectory(prefix="brain-v5-ro-migration-") as temp:
            original = Path(temp) / "original.sqlite"
            original.write_bytes(raw)
            os.chmod(original, 0o400)
            before = physical_ledger_snapshot(original)
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), raw_digest)
            disposable = Path(temp) / "candidate-copy.sqlite"
            shutil.copyfile(original, disposable)
            os.chmod(disposable, 0o600)

            # Store initialization and new report generation may mutate ONLY
            # this disposable file. The actual remote state and immutable input
            # are never opened for writing or committed back to Git.
            store = Store(disposable, visibility="PUBLIC")
            try:
                old_events, old_seq, old_chain = store._verified_events()
                self.assertEqual(old_seq, before["sequence"])
                self.assertEqual(old_chain, before["canonical_hash"])
                before_event_count = store.db.execute(
                    "SELECT count(*) FROM events"
                ).fetchone()[0]
                before_attempt_count = store.db.execute(
                    "SELECT count(*) FROM attempts"
                ).fetchone()[0]
                # New source legitimately changes derived report projection.
                # It must NOT rewrite the v4 report or the original event ledger.
                analysis_at = utcnow()
                v5_report = store.report(candidate, now=analysis_at)
                self.assertEqual(v5_report["status"], "PASS")
                self.assertEqual(v5_report["source_sha"], candidate)
                self.assertEqual(v5_report["state_sequence"], old_seq)
                self.assertEqual(v5_report["canonical_hash"], old_chain)
                self.assertEqual(v5_report["pending_events"], 0)
                self.assertIn("repository_changes", v5_report)
                self.assertIsInstance(v5_report["repository_changes"], list)
                self.assertIsInstance(v5_report["reuse_candidates"], list)
                self.assertEqual(v5_report["learning"]["events"], old_seq)
                self.assertEqual(
                    store.read_report(candidate, now=analysis_at), v5_report,
                    "V5 deterministic canonical report read/replay failed",
                )
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM events").fetchone()[0],
                    before_event_count,
                    "V5 analysis rewrote immutable event records",
                )
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM attempts").fetchone()[0],
                    before_attempt_count,
                    "V5 analysis invented operational outcomes",
                )
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM reports").fetchone()[0],
                    before["reports"] + 1,
                )
                retained = store.db.execute(
                    "SELECT hash,source_sha FROM reports "
                    "ORDER BY id DESC LIMIT 1 OFFSET 1"
                ).fetchone()
                self.assertEqual(
                    (retained["hash"], retained["source_sha"]),
                    (before["legacy_report_hash"], PRODUCTION),
                    "V5 analysis rewrote historical V4 report",
                )
                replay_events, replay_seq, replay_chain = store._verified_events()
                self.assertEqual(len(replay_events), len(old_events))
                self.assertEqual(replay_seq, old_seq)
                self.assertEqual(replay_chain, old_chain)
                receipt = {
                    "status": "PASS_REAL_SOURCE_READONLY_V5_PROJECTION_COMPATIBILITY",
                    "scope": "GITHUB_FOUNDATION_CI_DISPOSABLE_COPY_ONLY",
                    "original_production_source": PRODUCTION,
                    "v5_candidate_source": candidate,
                    "ci_checkout_commit": checkout_commit,
                    "ci_checkout_kind": checkout_kind,
                    "candidate_source_tree": candidate_tree,
                    "source_tree_matches_reviewed_pr_head": True,
                    "state_commit": state_commit,
                    "sqlite_blob": blob,
                    "sqlite_sha256": raw_digest,
                    "sqlite_bytes": len(raw),
                    "event_sequence": old_seq,
                    "canonical_hash": old_chain,
                    "historical_v4_reports_preserved": True,
                    "new_v5_report_replayed": True,
                    "new_v5_report_status": v5_report["status"],
                    "historical_events_mutated": False,
                    "attempts_mutated": False,
                    "pending_events": 0,
                    "candidate_count": len(v5_report["reuse_candidates"]),
                    "repository_change_count": len(v5_report["repository_changes"]),
                    "feedback_count": len(v5_report["learning"]["outcomes"]),
                    "production_deployed": False,
                    "v5_six_hour_soak_accepted": False,
                    "contains_raw_database_bytes": False,
                }
            finally:
                store.close()

            self.assertEqual(
                hashlib.sha256(original.read_bytes()).hexdigest(),
                raw_digest,
                "Immutable downloaded original bytes were modified",
            )
            self.assertEqual(
                physical_ledger_snapshot(original), before,
                "Original on-disk SQLite evidence changed",
            )
        print(
            "INDEPENDENT_V5_REAL_STATE_COMPATIBILITY_RECEIPT="
            + json.dumps(receipt, sort_keys=True)
        )


if __name__ == "__main__":
    unittest.main()
