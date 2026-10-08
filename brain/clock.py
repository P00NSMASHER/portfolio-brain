"""Validate a bounded external-clock receipt without changing portfolio state."""
from datetime import datetime, timezone
import json
import re
import sys


def validate(receipt, source_sha, now=None):
    now = now or datetime.now(timezone.utc)
    required = {'schema_version', 'source_sha', 'issued_at', 'slot', 'producer', 'kind'}
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise ValueError('CLOCK_SCHEMA: exact receipt fields required')
    if receipt['schema_version'] != 1 or receipt['source_sha'] != source_sha or not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        raise ValueError('CLOCK_SOURCE: current protected main required')
    if receipt['producer'] != '6ac323fee9c88191bd31e9d4cfc554f8' or receipt['kind'] not in ('scheduled', 'manual_probe'):
        raise ValueError('CLOCK_PRODUCER: known worker and explicit provenance required')
    issued = datetime.fromisoformat(receipt['issued_at'].replace('Z', '+00:00'))
    if issued.tzinfo is None or issued.utcoffset().total_seconds() != 0:
        raise ValueError('CLOCK_TIME: UTC timestamp required')
    if not 0 <= (now - issued).total_seconds() <= 1200:
        raise ValueError('CLOCK_STALE: receipt must be at most twenty minutes old')
    if receipt['slot'] != issued.strftime('%Y%m%dT%H'):
        raise ValueError('CLOCK_SLOT: hourly UTC slot does not match timestamp')
    return receipt


if __name__ == '__main__':
    print(json.dumps(validate(json.load(sys.stdin), sys.argv[1]), sort_keys=True))
