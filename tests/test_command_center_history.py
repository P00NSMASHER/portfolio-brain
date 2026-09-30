import hashlib
import io
import json
import unittest
import zipfile
from itertools import permutations

from dashboard.history_artifact_state import _merge_history_fork
from dashboard.history_state import (
    append_point,daily_trends,history_observation,project_momentum,public_history,
    replay_history_observation,validate_state,
)
from runtime.artifact_restore import InvalidStateArtifact
from state_journal.contracts import Conflict
from state_journal.events import make_change,make_event
from state_journal.reducer import checkpoint,replay


def seed():
    return {"schema_version":"1.0.0","state_id":"portfolio-command-center-history","sequence":0,"updated_at":None,"points":[]}


def telemetry(at,*,open_work=3,completed=5,cancelled=1,cost=1.25,model_calls=2,candidates=10,retained=3,actions=1,failures=0,verified=0):
    project={f"PRJ-{i:03d}":{"open_work":0,"completed_work":0,"cancelled_work":0,"sent_actions":0,"verified_outcomes":0} for i in range(12)}
    project["PRJ-001"]={"open_work":open_work,"completed_work":completed,"cancelled_work":cancelled,"sent_actions":actions,"verified_outcomes":verified}
    return {
        "generated_at":at,
        "queue":{"open_total":open_work,"counts":{"QUEUED":open_work,"ACTIVE":0,"COMPLETE":completed,"CANCELLED":cancelled},"completed_fingerprint_count":completed},
        "cost":{"actual_usage_today":{"cost_usd":cost,"model_calls":model_calls,"api_calls":1,"github_runner_minutes":7}},
        "hunter":{"totals":{"candidates":candidates,"retained":retained}},
        "actions":{"total_sent":actions},
        "failures":{"count":failures},
        "verified_external_outcomes":verified,
        "project_activity":project,
    }


class CommandCenterHistoryTests(unittest.TestCase):
    def test_same_hour_replaces_point_instead_of_inflating_history(self):
        state=append_point(seed(),telemetry("2026-09-26T12:05:00Z"),source_commit="a"*40)
        state=append_point(state,telemetry("2026-09-26T12:55:00Z",open_work=4),source_commit="b"*40)
        validate_state(state)
        self.assertEqual(len(state["points"]),1)
        self.assertEqual(state["points"][0]["metrics"]["open_work"],4)
        self.assertEqual(state["points"][0]["source_commit"],"b"*40)

    def test_first_day_does_not_claim_preexisting_cumulative_work_as_new(self):
        state=append_point(seed(),telemetry("2026-09-26T23:00:00Z",completed=20,actions=7,verified=2),source_commit="a"*40)
        day=daily_trends(state)[0]
        self.assertEqual(day["completed_work"],0)
        self.assertEqual(day["action_executions"],0)
        self.assertEqual(day["verified_external_outcomes"],0)

    def test_second_day_reports_evidence_backed_deltas(self):
        state=append_point(seed(),telemetry("2026-09-26T23:00:00Z",completed=20,actions=7,verified=2,candidates=10,retained=2),source_commit="a"*40)
        state=append_point(state,telemetry("2026-09-27T23:00:00Z",completed=23,actions=9,verified=3,candidates=15,retained=4),source_commit="b"*40)
        day=daily_trends(state)[-1]
        self.assertEqual(day["completed_work"],3)
        self.assertEqual(day["action_executions"],2)
        self.assertEqual(day["verified_external_outcomes"],1)
        self.assertEqual(day["hunter_candidates"],5)
        self.assertEqual(day["hunter_retained"],2)

    def test_public_history_has_24h_project_momentum_without_score(self):
        state=append_point(seed(),telemetry("2026-09-26T12:00:00Z",completed=2,actions=1,verified=0),source_commit="a"*40)
        state=append_point(state,telemetry("2026-09-27T12:00:00Z",completed=5,actions=3,verified=1),source_commit="b"*40)
        pub=public_history(state)
        row=next(x for x in pub["project_momentum"] if x["project_id"]=="PRJ-001")
        self.assertEqual(row["completed_work_delta"],3)
        self.assertEqual(row["sent_actions_delta"],2)
        self.assertEqual(row["verified_outcomes_delta"],1)
        def assert_no_score_fields(value):
            if isinstance(value,dict):
                self.assertFalse({"score","weighted_score","composite_score"} & set(value))
                for child in value.values():assert_no_score_fields(child)
            elif isinstance(value,list):
                for child in value:assert_no_score_fields(child)
        assert_no_score_fields(pub)
        self.assertIn("not a score",pub["momentum_definition"].lower())


    def test_native_observation_round_trip_is_exact_and_tamper_rejected(self):
        before=append_point(seed(),telemetry("2026-09-26T12:05:00Z"),source_commit="a"*40)
        after=append_point(before,telemetry("2026-09-26T12:15:00Z",open_work=4),source_commit="b"*40)
        point=history_observation(before,after)
        self.assertIsNotNone(point)
        self.assertEqual(replay_history_observation(before,point),after)
        tampered=json.loads(json.dumps(after));tampered["points"][0]["metrics"]["open_work"]=99
        self.assertIsNone(history_observation(before,tampered))

    def test_reducer_losslessly_replays_same_predecessor_history_branches(self):
        before=append_point(seed(),telemetry("2026-09-26T12:05:00Z"),source_commit="a"*40)
        first=append_point(before,telemetry("2026-09-26T12:15:00Z",open_work=4),source_commit="b"*40)
        second=append_point(before,telemetry("2026-09-26T12:25:00Z",open_work=5),source_commit="c"*40)
        base=checkpoint({"history":before},{"history":"fixture:history"})
        events=[
          make_event("command-center-pages","101","d"*40,[make_change("history",before,first)]),
          make_event("command-center-pages","102","e"*40,[make_change("history",before,second)]),
        ]
        expected=replay_history_observation(
          replay_history_observation(before,history_observation(before,first)),
          history_observation(before,second),
        )
        for order in permutations(events):
            out=replay(base,list(order))
            self.assertEqual(out["states"]["history"],expected)
            self.assertEqual(out["states"]["history"]["sequence"],before["sequence"]+2)
            self.assertEqual(set(out["event_ids"]),{event["event_id"] for event in events})

    def test_reducer_continues_from_losslessly_merged_history_predecessor(self):
        before=append_point(seed(),telemetry("2026-09-26T12:05:00Z"),source_commit="a"*40)
        first=append_point(before,telemetry("2026-09-26T12:15:00Z",open_work=4),source_commit="b"*40)
        second=append_point(before,telemetry("2026-09-26T13:05:00Z",open_work=5),source_commit="c"*40)
        base=checkpoint({"history":before},{"history":"fixture:history"})
        branches=[
          make_event("command-center-pages","101","d"*40,[make_change("history",before,first)]),
          make_event("command-center-pages","102","e"*40,[make_change("history",before,second)]),
        ]
        merged=replay(base,branches)["states"]["history"]
        continued=append_point(merged,telemetry("2026-09-26T14:05:00Z",open_work=6),source_commit="f"*40)
        followup=make_event("command-center-pages","103","f"*40,[make_change("history",merged,continued)])

        out=replay(base,[followup,*branches])

        self.assertEqual(out["states"]["history"],continued)
        self.assertEqual(set(out["event_ids"]),{followup["event_id"],*(event["event_id"] for event in branches)})

    def test_reducer_rejects_equal_time_history_disagreement(self):
        before=append_point(seed(),telemetry("2026-09-26T12:05:00Z"),source_commit="a"*40)
        first=append_point(before,telemetry("2026-09-26T12:15:00Z",open_work=4),source_commit="b"*40)
        second=append_point(before,telemetry("2026-09-26T12:15:00Z",open_work=5),source_commit="c"*40)
        base=checkpoint({"history":before},{"history":"fixture:history"})
        events=[
          make_event("command-center-pages","101","d"*40,[make_change("history",before,first)]),
          make_event("command-center-pages","102","e"*40,[make_change("history",before,second)]),
        ]
        with self.assertRaisesRegex(Conflict,"equal-time history"):
            replay(base,events)

    def test_legacy_history_fork_merge_requires_exact_predecessor_and_preserves_observations(self):
        before=append_point(seed(),telemetry("2026-09-26T12:05:00Z"),source_commit="a"*40)
        first=append_point(before,telemetry("2026-09-26T12:15:00Z",open_work=4),source_commit="b"*40)
        second=append_point(before,telemetry("2026-09-26T13:05:00Z",open_work=5),source_commit="c"*40)

        def archive(state):
            out=io.BytesIO()
            with zipfile.ZipFile(out,"w") as z:z.writestr("history_state.json",json.dumps(state).encode())
            return out.getvalue()
        payloads={"first":archive(first),"second":archive(second),"before":archive(before)}
        def meta(artifact_id,key,at,run):
            raw=payloads[key]
            return {
              "id":artifact_id,"created_at":at,"expires_at":"2026-10-30T00:00:00Z",
              "archive_download_url":key,"digest":"sha256:"+hashlib.sha256(raw).hexdigest(),
              "workflow_run":{"id":run,"head_branch":"main","head_sha":str(run%10)*40},
            }
        data={"artifacts":[
          meta(3,"second","2026-09-26T13:06:00Z",13),
          meta(2,"first","2026-09-26T12:16:00Z",12),
          meta(1,"before","2026-09-26T12:06:00Z",11),
        ]}
        merged,sources,fork_ids,inspected=_merge_history_fork(
          data,current_run="99",expected_head_branch="main",download=payloads.__getitem__,
        )
        self.assertEqual(merged["sequence"],before["sequence"]+2)
        self.assertEqual([p["bucket_at"] for p in merged["points"][-2:]],["2026-09-26T12:00:00Z","2026-09-26T13:00:00Z"])
        self.assertEqual(fork_ids,[3,2]);self.assertEqual(inspected,3)
        self.assertEqual({item["id"] for item in sources},{1,2,3})

        with self.assertRaisesRegex(InvalidStateArtifact,"predecessor"):
            _merge_history_fork(
              {"artifacts":data["artifacts"][:2]},current_run="99",
              expected_head_branch="main",download=payloads.__getitem__,
            )

    def test_legacy_history_fork_merge_rejects_equal_time_disagreement(self):
        before=append_point(seed(),telemetry("2026-09-26T12:05:00Z"),source_commit="a"*40)
        first=append_point(before,telemetry("2026-09-26T12:15:00Z",open_work=4),source_commit="b"*40)
        second=append_point(before,telemetry("2026-09-26T12:15:00Z",open_work=5),source_commit="c"*40)
        states=[first,second,before];payloads={};artifacts=[]
        for index,state in enumerate(states,1):
            out=io.BytesIO()
            with zipfile.ZipFile(out,"w") as z:z.writestr("history_state.json",json.dumps(state).encode())
            raw=out.getvalue();key=f"a{index}";payloads[key]=raw
            artifacts.append({
              "id":index,"created_at":f"2026-09-26T12:{20-index:02d}:00Z","expires_at":"2026-10-30T00:00:00Z",
              "archive_download_url":key,"digest":"sha256:"+hashlib.sha256(raw).hexdigest(),
              "workflow_run":{"id":10+index,"head_branch":"main","head_sha":str(index)*40},
            })
        with self.assertRaisesRegex(InvalidStateArtifact,"equal-time"):
            _merge_history_fork(
              {"artifacts":artifacts},current_run="99",expected_head_branch="main",download=payloads.__getitem__,
            )


if __name__=="__main__":
    unittest.main()
