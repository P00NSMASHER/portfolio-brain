import unittest
from unittest.mock import patch
from brain.adapters import GitHub
from brain.core import BrainError

class DiscoveryRetry(unittest.TestCase):
    def test_incomplete_then_complete_uses_only_complete_result(self):
        responses=iter([{'incomplete_results':True,'items':[{'untrusted':True}]},
                        {'incomplete_results':False,'items':[]}])
        api=GitHub(transport=lambda path:next(responses))
        with patch('brain.adapters.time.sleep'):
            self.assertEqual(api.discover({'query':'example'}),[])
        self.assertEqual(api.requests,2)

    def test_exhaustion_remains_failure(self):
        api=GitHub(transport=lambda path:{'incomplete_results':True,'items':[]})
        with patch('brain.adapters.time.sleep'), self.assertRaisesRegex(BrainError,'DISCOVERY_INCOMPLETE'):
            api.discover({'query':'example'})
        self.assertEqual(api.requests,2)

    def test_missing_marker_is_not_retried(self):
        api=GitHub(transport=lambda path:{'items':[]})
        with self.assertRaisesRegex(BrainError,'DISCOVERY_INCOMPLETE'):
            api.discover({'query':'example'})
        self.assertEqual(api.requests,1)

    def test_shared_budget_cannot_be_reset(self):
        api=GitHub(transport=lambda path:{'incomplete_results':True,'items':[]},max_requests=1)
        with patch('brain.adapters.time.sleep'), self.assertRaisesRegex(BrainError,'DISCOVERY_INCOMPLETE'):
            api.discover({'query':'example'})
        self.assertEqual(api.requests,1)
