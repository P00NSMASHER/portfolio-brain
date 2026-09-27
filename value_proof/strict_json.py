"""Strict JSON decoding for untrusted model and evidence boundaries.

The standard-library decoder intentionally accepts duplicate object keys and
non-finite numbers.  Both are ambiguous across JSON implementations and must
not enter canonical hashes, receipts, or verification decisions.
"""
from __future__ import annotations

import json
import math
from typing import Any


class StrictJSONError(ValueError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> None:
    raise StrictJSONError(f"non-finite JSON number: {token}")


def _validate_strings(value: Any) -> None:
    if isinstance(value, str):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise StrictJSONError("JSON string contains control characters")
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise StrictJSONError("JSON string contains an unpaired surrogate")
        return
    if isinstance(value, list):
        for item in value:
            _validate_strings(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_strings(key)
            _validate_strings(item)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise StrictJSONError("JSON number is not finite")


def strict_json_loads(text: str) -> Any:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_non_finite,
        )
    except json.JSONDecodeError as exc:
        raise StrictJSONError("invalid JSON") from exc
    _validate_strings(value)
    return value
