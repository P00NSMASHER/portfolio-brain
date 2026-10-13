"""One-off V7 human-review shadow audit on immutable original V6 state.

AUDIT ONLY. DO NOT MERGE. Only a genuine Foundation pull-request runner
fetches the exact pinned state Git object. All analysis uses an isolated copy.
Never touch production state, source refs, clock, signer, credentials, or runs.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = "P00NSMASHER/portfolio-brain"
V6_SOURCE = "f39a8b2ad88b6e1f0db246b586c89a9d611a566c"
V7_REVIEWED_SOURCE = "799edef43ffc0a913f5284b03022c65a2791f400"
ORIGINAL_STATE = "204dd965821e950b285fc9e374ef4254a702911d"
ORIGINAL_GIT_BLOB = "fdd7674d878dd5289261ab3b4062d73390a191f2"
ORIGINAL_SIZE = 49594368

CODE_BLOBS = {
    "brain/core.py": "a8155fd06fdbfead31177474ca05b9291d56772e",
    "brain/triage.py": "e204880f4d78201fe8f6585ad93e304f548ace19",
    "brain/render.py": "dedc3f94dabda257fc7c046f24fa65887465baa8",
}


def canonical(x):
    return json.dumps(
        x, sort_keys=True, separators=(",", ":"),
        allow_nan=False, ensure_ascii=False,
    )


def run_git(args, *, cwd, timeout=150):
    p = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    assert p.returncode == 0, "pinned source Git read failed"
    return p.stdout.strip()


def verify_original(path):
    data = Path(path).read_bytes()
    assert len(data) == ORIGINAL_SIZE, "original V6 state bytes changed"
    sha1 = hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data
    ).hexdigest()
    assert sha1 == ORIGINAL_GIT_BLOB, "original state Git identity mismatch"
    sha256 = hashlib.sha256(data).hexdigest()
    with sqlite3.connect("file:" + str(Path(path).resolve()) + "?mode=ro&immutable=1",
                         uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        meta = dict(db.execute("SELECT key,value FROM meta"))
        assert meta["visibility"] == "PUBLIC" and meta["schema_version"] == "2"
        total = db.execute("SELECT count(*) FROM events").fetchone()[0]
        ledger = db.execute("SELECT count(*) FROM ledger").fetchone()[0]
        pending = db.execute(
            "SELECT count(*) FROM events WHERE status='PENDING'"
        ).fetchone()[0]
        assert total > 0 and total == ledger and pending == 0
        last = db.execute(
            "SELECT seq,source_sha,created_at,hash,body FROM reports "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert last and last[1] == V6_SOURCE and last[0] == total
        assert hashlib.sha256(canonical(json.loads(last[4])).encode()).hexdigest() == last[3]
        return sha256, total, last[2], json.loads(last[4])


class FrozenV7RealStateShadowAudit(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("GITHUB_WORKFLOW") == "foundation-ci"
        and os.getenv("GITHUB_EVENT_NAME") == "pull_request"
        and os.getenv("GITHUB_REPOSITORY") == REPO,
        "one-off Foundation CI only; never scheduled/production",
    )
    def test_v7_actual_v6_state_shadow_is_readonly_and_source_bound(self):
        root = Path(__file__).resolve().parents[1]
        for path, sha in CODE_BLOBS.items():
            self.assertEqual(run_git(["hash-object", path], cwd=root, timeout=15), sha)

        with tempfile.TemporaryDirectory(prefix="v7-shadow-audit-") as tmp:
            folder = Path(tmp)
            run_git(["fetch", "--no-tags", "--depth=1", "origin", ORIGINAL_STATE], cwd=root)
            self.assertEqual(
                run_git(["rev-parse", "FETCH_HEAD"], cwd=root, timeout=15),
                ORIGINAL_STATE,
            )
            immutable = folder / "original-V6-state.sqlite"
            with immutable.open("wb") as output:
                p = subprocess.run(
                    ["git", "show", "FETCH_HEAD:state.sqlite"],
                    cwd=root, stdout=output, stderr=subprocess.PIPE,
                    timeout=150, check=False,
                )
            self.assertEqual(p.returncode, 0, "original state blob unavailable")
            before_digest, event_count, as_of, stored = verify_original(immutable)
            from brain.core import Store
            from brain.render import write_report
            from brain.triage import decision_queue

            clone = folder / "only-writable-disposable-copy.sqlite"
            shutil.copyfile(immutable, clone)
            db = Store(clone, visibility="PUBLIC")
            try:
                verified = db.read_report(V6_SOURCE, now=as_of)
                self.assertEqual(canonical(verified), canonical(stored))
                before = canonical(verified)

                # No source-provider networking is legitimate in a pure
                # decision queue or private report renderer.
                with patch("socket.socket", side_effect=AssertionError(
                    "network operation prohibited in V7 shadow projection"
                )):
                    queue = decision_queue(verified)
                    repeated = decision_queue(copy.deepcopy(verified))
                    flipped = copy.deepcopy(verified)
                    flipped["reuse_candidates"].reverse()
                    self.assertEqual(queue, repeated)
                    self.assertEqual(queue, decision_queue(flipped))
                    destination = folder / "private-preview"
                    write_report(verified, destination)

                self.assertEqual(queue["source_sha"], V6_SOURCE)
                self.assertEqual(queue["state_sequence"], verified["state_sequence"])
                self.assertLessEqual(len(queue["items"]), 10)
                self.assertTrue(all(
                    x["status"] == "HUMAN_REVIEW_PROPOSAL_NOT_EXECUTED"
                    and x["action_authority"] is False
                    and x["verified_revenue"] is None
                    and all(v.startswith("https://github.com/") for v in x["source_refs"])
                    for x in queue["items"]
                ))
                kinds = Counter(x["category"] for x in queue["items"])
                targets = Counter(x["metadata"].get("target") for x in queue["items"]
                                  if x["category"] == "REVIEW_THIRD_PARTY_SOURCE")
                self.assertTrue(all(count <= 2 for count in targets.values()))
                self.assertLessEqual(sum(targets.values()), 6)
                current_changes = [
                    x for x in verified["repository_changes"] if x["change_types"]
                ]
                if not current_changes:
                    self.assertFalse(any(
                        x["category"] in {"INVESTIGATE_CHECK_CHANGE",
                                          "REVIEW_SOURCE_REVISION",
                                          "REVIEW_TRACKER_TALLY",
                                          "REVIEW_CHECK_RECOVERY"}
                        for x in queue["items"]
                    ))
                self.assertEqual(canonical(verified), before)
                machine = json.loads((destination / "report.json").read_text())
                self.assertEqual(canonical(machine), before)
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
                for name in ("report.json", "report.html", "report.md"):
                    self.assertEqual(
                        stat.S_IMODE((destination / name).stat().st_mode), 0o600
                    )
                md = (destination / "report.md").read_text()
                self.assertIn("Evidence-gated decision queue", md)
                self.assertIn("human review only", md.lower())
                self.assertNotIn("validated 100% profitable", md)
                self.assertEqual(
                    db.pending(), 0, "read-only preview must not enqueue inputs"
                )
                self.assertEqual(
                    verified["state_sequence"], event_count
                )
            finally:
                db.close()

            self.assertEqual(verify_original(immutable)[0], before_digest)
            # Print only aggregate, public, source-qualified metadata.
            print("BRAIN_V7_REAL_STATE_SHADOW=" + canonical({
                "snapshot_commit": ORIGINAL_STATE,
                "original_git_blob": ORIGINAL_GIT_BLOB,
                "original_sha256": before_digest,
                "original_size": ORIGINAL_SIZE,
                "v6_original_source": V6_SOURCE,
                "v7_reviewed_source": V7_REVIEWED_SOURCE,
                "events": event_count,
                "report_source": verified["source_sha"],
                "report_status": verified["status"],
                "research_candidates": len(verified["reuse_candidates"]),
                "observed_comparisons": len(verified["repository_changes"]),
                "observed_changes": len(current_changes),
                "human_review_items": len(queue["items"]),
                "proposal_categories": dict(sorted(kinds.items())),
                "candidate_target_counts": dict(sorted(targets.items())),
                "no_network_queries": True,
                "original_binary_unchanged": True,
                "canonical_json_unchanged": True,
                "preview_permissions_private": True,
                "production_written": False,
                "production_accepted": False,
            }), flush=True)


if __name__ == "__main__":
    unittest.main()
