"""Behavior-level journal controls: real state advancement, no invented success."""
import copy
import json
import tempfile
import unittest
from itertools import permutations
from pathlib import Path

from agents.heartbeat_state import heartbeat, seed_state
from scheduler.autonomous_scheduler import load_state as scheduler_seed
from runtime.state import bootstrap_state, canonical_hash, cycle_id_for, advance_cycle
from state_journal.contracts import Conflict, JournalError, MissingPredecessor, digest, strict_load
from state_journal.events import make_change, make_event, validate_event
from state_journal.reducer import checkpoint, replay, make_snapshot, advance, commit_file, validate_snapshot

SHA = "a" * 40
RUNTIME_PROOFS = {}


def tick(before, agent="AGT-DATA-STEWARD", run="101", at="2026-09-29T14:00:00Z", producer="runtime-worker"):
    return heartbeat(before, agent_ids=[agent], activity_kind="RUNTIME_OBSERVATION", source_workflow=producer, source_run_id=run, at=at)


def runtime_tick(state, rid="REPO-001", at="2026-09-29T14:00:00Z"):
    cursor = state["repositories"][rid]["cursor_sha"]
    observations = [{"repository_id": rid, "status": "UNCHANGED", "source_ref": "main", "prior_sha": cursor,
                     "current_sha": cursor, "observed_at": at}]
    receipt = {"schema_version": "1.0.0", "cycle_id": cycle_id_for(state, mode="observe", target_repository_id=rid, observations=observations),
               "mode": "observe", "started_at": at, "finished_at": at, "status": "PASS", "reason": None,
               "observations": observations, "api_requests": 1}
    receipt["receipt_hash"] = canonical_hash(receipt)
    out = advance_cycle(state, receipt)
    RUNTIME_PROOFS[digest(out)] = {"cycle_receipt":receipt}
    return out


def fixture_evidence(event):
    return {"kind": "FIXTURE", "event_hash": event["event_hash"], "fixture_id": "fixture:unit-test"}


class StateJournalTests(unittest.TestCase):
    def setUp(self):
        self.hb = seed_state()
        self.rt = bootstrap_state(now="2026-09-29T13:00:00Z")
        self.base = checkpoint({"heartbeat": self.hb, "runtime": self.rt}, {"heartbeat": "fixture:heartbeat", "runtime": "fixture:runtime"})
        self.empty = make_snapshot(self.base, [], sequence=0, evidence={})

    def event(self, before=None, after=None, run="101", producer="runtime-worker", domain="heartbeat"):
        before = self.hb if before is None else before
        after = tick(before, run=run, producer=producer) if after is None else after
        return make_event(producer, run, SHA, [make_change(domain, before, after, proofs=RUNTIME_PROOFS.get(digest(after)))])

    def test_two_same_sequence_real_heartbeat_writers_preserve_both_events(self):
        one = self.event()
        two = self.event(after=tick(self.hb, agent="AGT-HUNTER", run="102", producer="hunter-autonomous-cycle", at="2026-09-29T14:00:01Z"), run="102", producer="hunter-autonomous-cycle")
        self.assertEqual(one["changes"][0]["after"]["sequence"], two["changes"][0]["after"]["sequence"])
        self.assertNotEqual(one["changes"][0]["after_hash"], two["changes"][0]["after_hash"])
        expected = tick(tick(self.hb), agent="AGT-HUNTER", run="102", producer="hunter-autonomous-cycle", at="2026-09-29T14:00:01Z")
        for order in permutations([one, two]):
            out = replay(self.base, list(order))
            self.assertEqual(out["states"]["heartbeat"], expected)
            self.assertEqual({e["source_run_id"] for e in out["states"]["heartbeat"]["recent_events"]}, {"101", "102"})

    def test_runtime_fork_is_not_arbitrarily_resolved_by_event_sort_order(self):
        a = self.event(self.rt, runtime_tick(self.rt), domain="runtime")
        b = self.event(self.rt, runtime_tick(self.rt, rid="REPO-002"), run="102", domain="runtime")
        for order in permutations([a,b]):
            with self.assertRaises(Conflict):
                replay(self.base,list(order))

    def test_ordered_runtime_mutations_retain_both_cycle_receipts(self):
        r1=runtime_tick(self.rt);r2=runtime_tick(r1,rid="REPO-002",at="2026-09-29T14:00:01Z")
        a=self.event(self.rt,r1,domain="runtime");b=self.event(r1,r2,run="102",domain="runtime")
        for order in permutations([a,b]):
            out=replay(self.base,list(order))
            self.assertEqual(out["states"]["runtime"],r2)
            self.assertEqual(out["states"]["runtime"]["sequence"],self.rt["sequence"]+2)

    def test_same_identity_different_bytes_fails_closed(self):
        a=self.event();b=self.event(after=tick(self.hb,agent="AGT-HUNTER"))
        self.assertEqual(a["event_id"],b["event_id"])
        for order in permutations([a,b]):
            with self.assertRaises(Conflict):replay(self.base,list(order))

    def test_exact_duplicate_delivery_is_idempotent(self):
        e=self.event();evidence=fixture_evidence(e)
        once=advance(self.empty,[(e,evidence)])
        twice=advance(once,[(copy.deepcopy(e),copy.deepcopy(evidence))])
        self.assertEqual(once,twice)
        self.assertEqual(once["sequence"],1)
        self.assertEqual(once["event_count"],1)

    def test_new_provider_delivery_preserves_evidence_without_double_application(self):
        e=self.event();s1=advance(self.empty,[(e,fixture_evidence(e))])
        s2=advance(s1,[(e,dict(fixture_evidence(e),fixture_id="fixture:second-delivery"))])
        self.assertEqual(s2["sequence"],2)
        self.assertEqual(s2["projection"],s1["projection"])
        self.assertEqual(len(s2["evidence"][e["event_id"]]),2)

    def test_event_identity_binds_run_kind_and_source_sha(self):
        e=self.event();other=make_event("runtime-worker","101","b"*40,e["changes"])
        self.assertNotEqual(e["event_id"],other["event_id"])
        self.assertNotEqual(e["event_id"],self.event(run="102")["event_id"])

    def test_hash_does_not_allow_domain_authority_smuggling(self):
        with self.assertRaises(JournalError):
            make_event("agent-heartbeat-sweep","101",SHA,[make_change("runtime",self.rt,runtime_tick(self.rt),proofs=RUNTIME_PROOFS[digest(runtime_tick(self.rt))])])

    def test_changed_producer_run_in_heartbeat_payload_is_rejected(self):
        with self.assertRaisesRegex(JournalError,"provenance"):
            make_event("runtime-worker","999",SHA,[make_change("heartbeat",self.hb,tick(self.hb))])

    def test_unknown_domain_is_rejected(self):
        with self.assertRaises(JournalError):make_change("invented",self.hb,self.hb)

    def test_missing_predecessor_does_not_seed_or_skip(self):
        first=runtime_tick(self.rt);second=runtime_tick(first,at="2026-09-29T14:00:01Z")
        e=self.event(first,second,domain="runtime")
        with self.assertRaises(MissingPredecessor):replay(self.base,[e])

    def test_snapshot_publication_is_atomic_on_conflict(self):
        e=self.event(self.rt,runtime_tick(self.rt),domain="runtime")
        state=advance(self.empty,[(e,fixture_evidence(e))])
        fork=self.event(self.rt,runtime_tick(self.rt,rid="REPO-002"),run="102",domain="runtime")
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"snapshot.json";output.write_bytes(b"EXISTING-CANONICAL-BYTES")
            with self.assertRaises(Conflict):commit_file(output,state,[(fork,fixture_evidence(fork))])
            self.assertEqual(output.read_bytes(),b"EXISTING-CANONICAL-BYTES")

    def test_cross_domain_event_is_all_or_nothing(self):
        prior=runtime_tick(self.rt)
        e=make_event("runtime-worker","101",SHA,[make_change("heartbeat",self.hb,tick(self.hb)),make_change("runtime",prior,runtime_tick(prior,at="2026-09-29T14:00:01Z"),proofs=RUNTIME_PROOFS[digest(runtime_tick(prior,at="2026-09-29T14:00:01Z"))])])
        before=copy.deepcopy(self.empty)
        with self.assertRaises(MissingPredecessor):advance(self.empty,[(e,fixture_evidence(e))])
        self.assertEqual(self.empty,before)

    def test_tampered_projection_is_recomputed_not_trusted(self):
        state=advance(self.empty,[(self.event(),fixture_evidence(self.event()))])
        state["projection"]["states"]["heartbeat"]["sequence"]+=10
        core={k:v for k,v in state.items() if k!="state_hash"};state["state_hash"]=digest(core)
        with self.assertRaises(JournalError):validate_snapshot(state)

    def test_rehashed_checkpoint_tampering_does_not_keep_old_projection(self):
        state=copy.deepcopy(self.empty)
        state["checkpoint"]["states"]["runtime"]=runtime_tick(self.rt)
        state["checkpoint"]=checkpoint(state["checkpoint"]["states"],state["checkpoint"]["source_refs"])
        with self.assertRaises(JournalError):validate_snapshot(state)

    def test_missing_checkpoint_domain_is_rejected(self):
        base=checkpoint({"runtime":self.rt},{"runtime":"fixture:only-runtime"})
        with self.assertRaisesRegex(JournalError,"missing"):
            replay(base,[self.event()])

    def test_equal_time_conflicting_heartbeat_writes_cannot_choose_a_winner(self):
        one=self.event();two=self.event(after=tick(self.hb,run="102"),run="102")
        with self.assertRaises(Conflict):replay(self.base,[one,two])

    def test_equal_time_disjoint_agents_commute(self):
        one=self.event();two=self.event(after=tick(self.hb,agent="AGT-HUNTER",run="102"),run="102")
        self.assertEqual(replay(self.base,[one,two]),replay(self.base,[two,one]))

    def test_inferred_heartbeat_operations_must_reproduce_the_after_state(self):
        change=make_change("heartbeat",self.hb,tick(self.hb))
        change["batches"][0]["activity_kind"]="FAKE"
        with self.assertRaises(JournalError):make_event("runtime-worker","101",SHA,[change])

    def test_ordered_heartbeat_chain_is_exact_native_replay(self):
        one=tick(self.hb);two=tick(one,agent="AGT-HUNTER",run="102",at="2026-09-29T14:00:01Z")
        a=self.event(self.hb,one);b=self.event(one,two,run="102")
        self.assertEqual(replay(self.base,[b,a])["states"]["heartbeat"],two)

    def test_event_input_is_not_mutated(self):
        e=self.event();before=copy.deepcopy(e);replay(self.base,[e]);self.assertEqual(e,before)

    def test_emitted_event_is_deep_copied(self):
        before=copy.deepcopy(self.hb);after=tick(before);e=self.event(before,after)
        after["sequence"]=999;self.assertNotEqual(e["changes"][0]["after"]["sequence"],999)

    def test_event_rejects_unknown_fields(self):
        e=self.event();e["authority_granted"]=True
        with self.assertRaises(JournalError):validate_event(e)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in [b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}',b'[]']:
            with self.subTest(raw=raw),self.assertRaises(JournalError):strict_load(raw)

    def test_boolean_and_mutable_source_identity_are_rejected(self):
        for run,source in [(True,SHA),("1","main"),("0",SHA),("1","A"*40)]:
            with self.assertRaises(JournalError):make_event("runtime-worker",run,source,self.event()["changes"])

    def test_canonical_sequence_is_only_advanced_by_reducer(self):
        e=self.event();e["sequence"]=100
        with self.assertRaises(JournalError):validate_event(e)

    def test_source_evidence_is_required_for_every_event(self):
        with self.assertRaises(JournalError):make_snapshot(self.base,[self.event()],sequence=1,evidence={})

    def test_replay_keeps_checkpoint_and_all_event_payloads(self):
        e=self.event();out=advance(self.empty,[(e,fixture_evidence(e))])
        self.assertEqual(out["checkpoint"],self.base)
        self.assertEqual(out["events"],[e])
        self.assertFalse(out["production_authority"])

    def test_boolean_number_substitution_cannot_bypass_snapshot_hash(self):
        state=copy.deepcopy(self.empty);state['production_authority']=0
        with self.assertRaises(JournalError):validate_snapshot(state)

    def test_capacity_limit_does_not_silently_prune_events(self):
        from unittest.mock import patch
        before=copy.deepcopy(self.empty)
        with patch('state_journal.reducer.MAX_EVENTS',0),self.assertRaises(JournalError):
            advance(self.empty,[(self.event(),fixture_evidence(self.event()))])
        self.assertEqual(self.empty,before)

    def test_runtime_transition_requires_original_companion_receipt(self):
        with self.assertRaises(JournalError):
            make_change('runtime',self.rt,runtime_tick(self.rt))

    def test_snapshot_serialization_round_trip(self):
        e=self.event();s=advance(self.empty,[(e,fixture_evidence(e))]);validate_snapshot(strict_load(json.dumps(s).encode()))


if __name__ == "__main__":unittest.main()
