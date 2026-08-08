from __future__ import annotations

import pytest

from denser.container.packet_v2 import McV2TilePacket


def test_mcv2_packet_round_trip_binds_every_section() -> None:
    packet = McV2TilePacket(
        "denser-eam-dct-v2", "q4", b"map", b"payload", b"repair", b"cert", False
    )
    encoded = packet.encode()
    assert McV2TilePacket.decode(encoded) == packet


@pytest.mark.parametrize("offset", [0, 8, -1])
def test_mcv2_packet_rejects_corruption(offset: int) -> None:
    encoded = bytearray(McV2TilePacket("codec", "profile", b"a", b"b", b"c", b"d", True).encode())
    encoded[offset] ^= 1
    with pytest.raises(ValueError):
        McV2TilePacket.decode(bytes(encoded))


def test_mcv2_packet_rejects_unknown_codec_identity() -> None:
    with pytest.raises(ValueError, match="codec"):
        McV2TilePacket("", "profile", b"", b"x", b"", b"x", False)
