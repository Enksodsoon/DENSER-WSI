from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from denser.core.models import ByteBreakdown


@dataclass(frozen=True, slots=True)
class EncodedCandidate:
    codec_id: str
    profile_id: str
    payload: bytes
    breakdown: ByteBreakdown
    attestation: tuple[tuple[str, str], ...] = ()
    basis_id: str = ""
    entropy_model_id: str = ""

    def __post_init__(self) -> None:
        if not self.codec_id or not self.profile_id:
            raise ValueError("codec and profile identifiers are required")
        if self.breakdown.complete != len(self.payload):
            raise ValueError("candidate breakdown must equal payload length")

    @property
    def complete_bytes(self) -> int:
        return self.breakdown.complete


class CodecCandidate(Protocol):
    codec_id: str
    profile_id: str

    def encode(self, rgb: np.ndarray) -> EncodedCandidate: ...

    def decode(self, payload: bytes, shape: tuple[int, int, int]) -> np.ndarray: ...
