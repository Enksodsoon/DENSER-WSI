from __future__ import annotations

import pytest

from denser.codecs.base import EncodedCandidate
from denser.core.models import ByteBreakdown


def test_encoded_candidate_requires_complete_payload_accounting() -> None:
    candidate = EncodedCandidate(
        codec_id="lossless-zlib-fixed",
        profile_id="fallback-v1",
        payload=b"abc",
        breakdown=ByteBreakdown(payload=3),
    )
    assert candidate.complete_bytes == 3
    with pytest.raises(ValueError, match="breakdown"):
        EncodedCandidate("x", "y", b"abc", ByteBreakdown(payload=2))
