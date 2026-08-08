from __future__ import annotations

from dataclasses import dataclass, field

from denser.evidence.types import AcceptanceContract


@dataclass(frozen=True, slots=True)
class PathLabAdapterContract:
    version: str = "PathLab-MCV1-adapter-1"
    media_type: str = "image/x-mcv1-tile"
    acceptance: AcceptanceContract = field(default_factory=AcceptanceContract)
    require_self_verifying_certificate: bool = True
