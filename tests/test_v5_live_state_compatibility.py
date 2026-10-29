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
import sys
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


def physical_ledger_snapshot(path, expected_source=PRODUCTION):
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
        assert last["source_sha"] == expected_source
        assert old_report["source_sha"] == expected_source
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

        # Historical pre-promotion rehearsal is valid only when V4 is
        # still protected main. Post-release and subsequent PRs receive a
        # separate live-source/state replay; do not relabel archived V4 proof.
        if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
            self.skipTest("V4_PREPROMOTION_ONLY: use deployed-source state proof")
        if git("ls-remote", "origin", "refs/heads/main").split()[0] != PRODUCTION:
            self.skipTest("V4_PREPROMOTION_ONLY: main has advanced")
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

                # Exercise the REAL downstream provider, not only StubGitHub
                # fixtures. This is a bounded, unauthenticated PUBLIC GitHub
                # API read against an immutable real-ledger candidate and a
                # pinned RETALLY PR head. A draft with green checks is NEVER
                # evidence of deployment, customer adoption or realized value.
                from brain.adapters import GitHub
                from brain.transfer import review_transfer
                originating_key = (
                    "Jacob-Met/workflow-checks:"
                    "freight_packets/freightpkt/invoice_match.py"
                )
                origin_match = [
                    x for x in v5_report["reuse_candidates"]
                    if x.get("key") == originating_key
                ]
                self.assertEqual(
                    len(origin_match), 1,
                    "Production ledger does not contain one exact discovery",
                )
                self.assertEqual(origin_match[0]["data_kind"], "ACTUAL")
                self.assertEqual(origin_match[0]["freshness"], "CURRENT")
                self.assertEqual(
                    origin_match[0]["head_sha"],
                    "a5fd61b0c361c8a9b8a6737b33ecc9efab46e0ad",
                )
                self.assertEqual(
                    origin_match[0]["code_sha256"],
                    "37a9e0801de948c3b558ca7c9846b3d0eb76ec062703ee3e5132df273ff569ab",
                )
                expected_target_head = (
                    "9f68a2a0d22abd671ce7be353506a8b8cf9e5a52"
                )
                transfer_request = {
                    "schema_version": 1,
                    "candidate_key": originating_key,
                    "target_repository": "P00NSMASHER/github-value-hunt-ledger",
                    "pull_request_number": 343,
                    "expected_head_sha": expected_target_head,
                }
                public_api = GitHub(private=False)
                observed_transfer = review_transfer(
                    v5_report, transfer_request, api=public_api
                )
                self.assertEqual(
                    observed_transfer["status"],
                    "DRAFT_PR_CHECKS_PASSED_NOT_ADOPTED",
                )
                self.assertEqual(
                    observed_transfer["checks"]["status"],
                    "GITHUB_REPORTED_REQUIRED_CHECKS_SUCCESS",
                )
                self.assertEqual(
                    observed_transfer["target"]["pr_head_sha"],
                    expected_target_head,
                )
                self.assertEqual(
                    observed_transfer["origin"]["code_sha256"],
                    origin_match[0]["code_sha256"],
                )
                self.assertEqual(
                    observed_transfer["origin"]["attribution"],
                    "EXACT_SOURCE_LINK_CLAIMED_IN_PR",
                )
                self.assertTrue(observed_transfer["target"]["draft"])
                self.assertFalse(observed_transfer["target"]["merged_pr_metadata"])
                self.assertFalse(observed_transfer["event_written"])
                self.assertEqual(observed_transfer["github_mutations"], 0)
                self.assertEqual(
                    observed_transfer["integration"],
                    "NOT_VERIFIED_BY_PULL_REQUEST_CHECKS",
                )
                self.assertEqual(observed_transfer["revenue"], "NOT_VERIFIED")
                self.assertEqual(
                    observed_transfer["realized_recovery"], "NOT_VERIFIED"
                )
                self.assertEqual(observed_transfer["operator_feedback"], "NOT_COLLECTED")
                self.assertGreaterEqual(public_api.requests, 5)
                self.assertLessEqual(public_api.requests, 24)

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
                    "real_retally_provider_transfer": {
                        "status": observed_transfer["status"],
                        "scope": "PUBLIC_GITHUB_GET_ONLY_FROM_REAL_LEDGER",
                        "origin_candidate_key": originating_key,
                        "origin_code_sha256": origin_match[0]["code_sha256"],
                        "pr_number": 343,
                        "target_pr_head_sha": expected_target_head,
                        "provider_checks_reported": observed_transfer["checks"]["provider_check_count"],
                        "required_checks_passed": True,
                        "public_get_requests": public_api.requests,
                        "target_remains_draft": True,
                        "adoption_proven": False,
                        "deployment_proven": False,
                        "customer_value_proven": False,
                        "revenue_proven": False,
                        "feedback_event_written": False,
                        "production_state_mutated": False,
                    },
                }
            finally:
                store.close()

            # Exercise a real source rollback on a DIFFERENT disposable copy.
            # A v5-derived report is intentionally incompatible with v4's
            # derived schema; source rollback must fail closed on the stale
            # report, then generate a new v4 projection without losing events.
            rollback_copy = Path(temp) / "rollback-copy.sqlite"
            shutil.copyfile(disposable, rollback_copy)
            rollback_root = Path(temp) / "v4-reviewed-source"
            git("fetch", "--quiet", "--no-tags", "origin", PRODUCTION)
            original_paths = git(
                "ls-tree", "-r", "--name-only", PRODUCTION, "brain"
            ).splitlines()
            self.assertGreater(len(original_paths), 5)
            for name in original_paths:
                self.assertTrue(name.startswith("brain/") and ".." not in name.split("/"))
                destination = rollback_root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(git("show", f"{PRODUCTION}:{name}", raw=True))
            v5_copy_before = hashlib.sha256(disposable.read_bytes()).hexdigest()

            old_runtime = r"""
import json, sqlite3, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from brain.core import Store, BrainError, utcnow
path, expected_sha, expected_sequence, expected_chain = (
    Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5]
)
store = Store(path, visibility="PUBLIC")
try:
    events, seq, chain = store._verified_events()
    assert seq == expected_sequence and chain == expected_chain
    before_attempts = store.db.execute("SELECT count(*) FROM attempts").fetchone()[0]
    before_reports = store.db.execute("SELECT count(*) FROM reports").fetchone()[0]
    previous = store.db.execute(
        "SELECT source_sha,body FROM reports ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert json.loads(previous["body"])["repository_changes"] is not None
    assert previous["source_sha"] != expected_sha
    # A new source cannot reinterpret a previous source's derived report
    # as current canonical state. Fail closed rather than silently accept.
    rejected_old_projection = False
    try:
        store.read_report(expected_sha, now=utcnow())
    except BrainError:
        rejected_old_projection = True
    assert rejected_old_projection, "stale v5 report accepted by old v4 implementation"
    now = utcnow()
    report = store.report(expected_sha, now=now)
    assert report["status"] == "PASS"
    assert report["source_sha"] == expected_sha
    assert "repository_changes" not in report
    assert report["state_sequence"] == expected_sequence
    assert report["canonical_hash"] == expected_chain
    assert report["pending_events"] == 0
    assert store.read_report(expected_sha, now=now) == report
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == seq
    assert store.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == before_attempts
    assert store.db.execute("SELECT count(*) FROM reports").fetchone()[0] == before_reports + 1
    prior = store.db.execute(
        "SELECT source_sha FROM reports ORDER BY id DESC LIMIT 1 OFFSET 1"
    ).fetchone()
    assert prior["source_sha"] != expected_sha
    print("V4_DISPOSABLE_ROLLBACK_REPLAY=" + json.dumps({
        "status": "PASS_V4_DISPOSABLE_ROLLBACK",
        "v5_report_refused_under_v4": rejected_old_projection,
        "v4_report_regenerated": True,
        "v4_report_replayed": True,
        "canonical_event_chain_retained": True,
        "event_sequence": seq,
        "canonical_hash": chain,
        "attempts_added": 0,
        "production_deployed": False,
    }, sort_keys=True))
finally:
    store.close()
"""
            rollback_process = subprocess.run(
                [
                    sys.executable, "-I", "-c", old_runtime,
                    str(rollback_root), str(rollback_copy),
                    PRODUCTION, str(before["sequence"]), before["canonical_hash"],
                ],
                cwd=temp, capture_output=True, text=True, timeout=35,
                check=False,
            )
            self.assertEqual(
                rollback_process.returncode, 0,
                "V4 rollback rehearsal failed: "
                + (rollback_process.stderr + rollback_process.stdout)[-2500:],
            )
            rollback_line = next(
                (line for line in rollback_process.stdout.splitlines()
                 if line.startswith("V4_DISPOSABLE_ROLLBACK_REPLAY=")),
                None,
            )
            self.assertIsNotNone(rollback_line, rollback_process.stdout[-1200:])
            rollback_proof = json.loads(rollback_line.split("=", 1)[1])
            self.assertEqual(rollback_proof["status"], "PASS_V4_DISPOSABLE_ROLLBACK")
            self.assertEqual(hashlib.sha256(disposable.read_bytes()).hexdigest(), v5_copy_before)
            receipt["v4_disposable_rollback"] = rollback_proof
            receipt["v4_original_source_code"] = PRODUCTION
            receipt["rollback_source_files"] = len(original_paths)
            receipt["rollback_isolated_no_production_writes"] = True

            # Separately rehearse the FULL first V5 workload on a disposable
            # copy of the authentic ledger. Reuse old immutable source facts
            # ONLY as explicitly SIMULATED mock responses, never current
            # provider observations or commercial outcomes. This proves
            # application wiring, not an automatic production run or soak.
            from copy import deepcopy
            from unittest.mock import patch
            from brain.__main__ import monitor, research, experiment, doctor
            from brain.adapters import event as make_event, policy as brain_policy

            shadow_copy = Path(temp) / "shadow-first-cycle.sqlite"
            shutil.copyfile(disposable, shadow_copy)
            os.chmod(shadow_copy, 0o600)
            shadow = Store(shadow_copy, visibility="PUBLIC")
            try:
                historical_events, initial_seq, initial_hash = shadow._verified_events()
                self.assertEqual(initial_seq, before["sequence"])
                self.assertEqual(initial_hash, before["canonical_hash"])
                recent_repos = {}
                historical_candidates = []
                for item in historical_events:
                    if item["kind"] == "repository":
                        prior = recent_repos.get(item["key"])
                        if prior is None or item["observed_at"] > prior["observed_at"]:
                            recent_repos[item["key"]] = item
                    elif item["kind"] == "candidate":
                        historical_candidates.append(item)
                required_repos = brain_policy()["repositories"]
                self.assertEqual(
                    set(required_repos) - set(recent_repos), set(),
                    "Real input snapshot lacks configured monitored repositories",
                )
                self.assertTrue(historical_candidates,
                                "No true prior source record for rehearsal")

                class SimulatedReplayAPI:
                    requests = 0
                    def observe(self, repository):
                        if repository not in recent_repos:
                            raise AssertionError("Unrecognized monitor fixture source")
                        return deepcopy(recent_repos[repository]["payload"]), False

                    def discover(self, target, repository=None):
                        if repository is not None:
                            raise AssertionError("Rehearsal cannot override repository")
                        match = next(
                            (e for e in historical_candidates
                             if e["payload"]["target"] == target["project"]), None
                        )
                        return [(deepcopy(match["payload"]), False)] if match else []

                # The original code's event default is ACTUAL; force every
                # fixture-created event to SIMULATED. This prevents a green
                # rehearsal receipt from claiming a real fresh GitHub read.
                def simulated_fixture_event(kind, key, payload, source_sha, **options):
                    return make_event(
                        kind, key, payload, source_sha,
                        private=options.get("private", False),
                        data_kind="SIMULATED", now=options.get("now"),
                    )

                with patch("brain.__main__.event", side_effect=simulated_fixture_event):
                    shadow_api = SimulatedReplayAPI()
                    monitor_report = monitor(
                        shadow, candidate, Path(temp) / "shadow-monitor",
                        api=shadow_api,
                    )
                    research_report = research(
                        shadow, candidate, Path(temp) / "shadow-research",
                        api=shadow_api,
                    )
                    experiment_report = experiment(
                        shadow, candidate, Path(temp) / "shadow-experiment",
                    )
                    doctor_report = doctor(
                        shadow, candidate, Path(temp) / "shadow-doctor",
                    )
                self.assertEqual(monitor_report["status"], "PASS")
                self.assertEqual(research_report["status"], "PASS")
                self.assertEqual(experiment_report["status"], "PASS")
                self.assertEqual(doctor_report["status"], "PASS")
                self.assertEqual(shadow_api.requests, 0)
                self.assertEqual(
                    doctor_report["mandatory_workloads"],
                    {"monitor": "PASS", "research": "PASS", "experiment": "PASS"},
                )
                self.assertEqual(shadow.pending(), 0)
                self.assertTrue((Path(temp) / "shadow-doctor" / "report.json").exists())
                resulting_events, final_seq, final_hash = shadow._verified_events()
                self.assertGreater(final_seq, initial_seq)
                self.assertNotEqual(final_hash, initial_hash)
                self.assertEqual(
                    resulting_events[:initial_seq], historical_events,
                    "Shadow run modified v4-origin immutable event prefix",
                )
                new_events = resulting_events[initial_seq:]
                self.assertEqual(
                    {e["data_kind"] for e in new_events}, {"SIMULATED"},
                    "Fixture data leaked into an ACTUAL source record",
                )
                self.assertEqual(
                    {e["kind"] for e in new_events},
                    {"repository", "candidate", "experiment"}
                    if any(e["kind"] == "candidate" for e in new_events)
                    else {"repository", "experiment"},
                )
                self.assertEqual(
                    sum(e["kind"] == "repository" for e in new_events),
                    len(required_repos),
                )
                self.assertTrue(
                    all(e["source_sha"] == candidate for e in new_events),
                )
                live_report = shadow.read_report(candidate)
                self.assertEqual(live_report["pending_events"], 0)
                self.assertEqual(live_report["canonical_hash"], final_hash)
                self.assertIsNone(live_report["learning"]["verified_revenue"])
                self.assertEqual(live_report["learning"]["outcomes"], [])
                receipt["isolated_shadow_full_core"] = {
                    "status": "PASS_SIMULATED_INPUT_FIRST_CYCLE_REHEARSAL",
                    "mandatory_workloads": doctor_report["mandatory_workloads"],
                    "original_event_sequence": initial_seq,
                    "new_simulated_event_count": len(new_events),
                    "resulting_disposable_sequence": final_seq,
                    "resulting_disposable_chain": final_hash,
                    "all_added_events_labelled_simulated": True,
                    "remote_api_calls": shadow_api.requests,
                    "state_branch_writes": 0,
                    "source_events_preserved": True,
                    "customer_value_claimed": False,
                    "production_deployed": False,
                    "v5_runtime_acceptance": False,
                }
            finally:
                shadow.close()
            self.assertEqual(
                hashlib.sha256(disposable.read_bytes()).hexdigest(),
                v5_copy_before,
                "Shadow cycle modified original V5 compatibility copy",
            )

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
