from __future__ import annotations

import pytest

from denser.core.canonical import canonical_json_bytes
from denser.core.hashes import sha256_bytes


def test_canonical_json_sorts_keys_and_uses_compact_utf8() -> None:
    encoded = canonical_json_bytes({"z": 1, "a": "µ"})
    assert encoded == b'{"a":"\xc2\xb5","z":1}'


def test_canonical_json_rejects_nonfinite_numbers() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"invalid": float("nan")})


def test_sha256_bytes_matches_known_vector() -> None:
    assert sha256_bytes(b"denser") == "e3c9bf8c250688343cf1835997f6dddeb941ad2800d1dc97fd88ea52c843ea66"
