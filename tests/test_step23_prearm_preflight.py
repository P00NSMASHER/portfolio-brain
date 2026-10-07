import unittest
from unittest.mock import patch

from acceptance import step23_prearm_preflight as preflight


class DummyAPI:
    pass


class PrearmPreflightTests(unittest.TestCase):
    def test_drain_never_uses_auth_token_as_correlation_material(self):
        drains=[]
        seen=[]
        secret="ghs_DO_NOT_PUT_THIS_IN_RUN_NAMES"

        def fake_dispatch(api, *, workflow, filename, exact_sha, correlation):
            seen.append(correlation)
            return {
                "workflow": workflow,
                "filename": filename,
                "run_id": 1,
                "event": "workflow_dispatch",
                "head_sha": exact_sha,
                "conclusion": "success",
                "created_at": "2026-10-07T00:00:00Z",
                "updated_at": "2026-10-07T00:00:01Z",
                "correlation": correlation,
                "acceptance_credit": False,
            }

        with patch.object(preflight, "dispatch", side_effect=fake_dispatch), \
             patch.object(preflight, "pending_event_count", return_value=0):
            result=preflight.drain(
                DummyAPI(),
                exact_sha="a"*40,
                prefix="initial",
                auth_token=secret,
                correlation_seed="run-123",
                drains=drains,
            )

        self.assertEqual(result,0)
        self.assertEqual(seen,["prearm-run-123-initial-drain-1"])
        self.assertNotIn(secret,seen[0])
        self.assertNotIn(secret,str(drains))


if __name__=="__main__":
    unittest.main()
