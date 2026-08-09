from __future__ import annotations

from denser.data.gdc import build_gdc_query


def test_gdc_query_serialization_contains_no_credentials() -> None:
    payload = build_gdc_query(("TCGA-BRCA",)).as_api_params()
    encoded = repr(payload).lower()
    assert "token" not in encoded
    assert "authorization" not in encoded
    assert "tcga-brca" in encoded
