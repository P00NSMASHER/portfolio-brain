import io
import unittest
import urllib.error
from brain.v8 import repair_core_origin as origin

class TransportTests(unittest.TestCase):
    def test_temporary_failure_recovers(self):
        class Provider:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                if self.calls < 3:
                    raise urllib.error.HTTPError(request.full_url, 503, 'secret', {}, None)
                return io.BytesIO(b'{"ok": true}')
        provider = Provider()
        self.assertEqual(origin.read_json(provider, 'token', origin.ROOT + 'branches/main', sleep=lambda _: None), {'ok': True})
        self.assertEqual(provider.calls, 3)

    def test_denial_is_not_retried_or_leaked(self):
        class Provider:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise urllib.error.HTTPError(request.full_url, 403, 'SECRET', {}, None)
        provider = Provider()
        with self.assertRaisesRegex(origin.OriginError, '^ORIGIN_HTTP_403$'):
            origin.read_json(provider, 'token', origin.ROOT + 'branches/main', sleep=lambda _: None)
        self.assertEqual(provider.calls, 1)

    def test_timeout_exhaustion_is_bounded(self):
        class Provider:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise TimeoutError('SECRET')
        provider = Provider()
        with self.assertRaisesRegex(origin.OriginError, '^ORIGIN_TRANSPORT_UNAVAILABLE$'):
            origin.read_json(provider, 'token', origin.ROOT + 'branches/main', sleep=lambda _: None)
        self.assertEqual(provider.calls, 3)

    def test_malformed_json_is_not_retried(self):
        class Provider:
            def open(self, request, timeout):
                return io.BytesIO(b'SECRET')
        with self.assertRaisesRegex(origin.OriginError, '^ORIGIN_JSON_INVALID$'):
            origin.read_json(Provider(), 'token', origin.ROOT + 'branches/main')
