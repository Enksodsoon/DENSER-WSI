from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlideByteLedger:
    categories: dict[str, int]

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or value < 0 for value in self.categories.values()):
            raise ValueError("byte-ledger categories must be non-negative integers")

    @property
    def complete_bytes(self) -> int:
        return sum(self.categories.values())
