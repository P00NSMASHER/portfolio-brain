import unittest

from operations.liveness_artifact_state import LivenessArtifactError, validate_receipt


def receipt():
    return {
        'api_requests': 11,
        'authority_granted': False,
        'checked_at': '2026-09-28T13:51:22Z',
        'dispatches': [],
        'hard_stop_reason': None,
        'schema_version': '1.0.0',
        'status': 'HEALTHY_VERIFIED_WORK',
        'targets': [{
            'workflow_name':'runtime-hourly-sync',
            'workflow_file':'runtime-hourly-sync.yml',
            'status':'HEALTHY_VERIFIED_WORK',
            'dispatch_required':False,
            'latest_run_id':42,
            'work_proof_status':'VERIFIED_WORK',
        }],
        'verified_work_target_count': 1,
    }


class LivenessArtifactStateTests(unittest.TestCase):
    def test_valid_exact_run_receipt_is_accepted(self):
        validate_receipt(receipt())

    def test_authority_widening_is_rejected(self):
        value=receipt(); value['authority_granted']=True
        with self.assertRaises(LivenessArtifactError):
            validate_receipt(value)

    def test_verified_count_mismatch_is_rejected(self):
        value=receipt(); value['verified_work_target_count']=0
        with self.assertRaises(LivenessArtifactError):
            validate_receipt(value)


if __name__ == '__main__':
    unittest.main()
