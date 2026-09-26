import unittest

from dashboard.history_state import append_point,daily_trends,project_momentum,public_history,validate_state


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


if __name__=="__main__":
    unittest.main()
