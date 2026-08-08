from __future__ import annotations

import math


def diagnostic_nullity_spectrum(
    singular_values: list[float] | tuple[float, ...],
    thresholds: list[float] | tuple[float, ...],
) -> dict[float, float]:
    """Return empirical near-null fractions, not preservation guarantees."""
    values = tuple(float(value) for value in singular_values)
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("singular values must be finite, non-negative, and non-empty")
    result: dict[float, float] = {}
    for raw_threshold in thresholds:
        threshold = float(raw_threshold)
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("DNS thresholds must be finite and non-negative")
        result[threshold] = sum(value <= threshold for value in values) / len(values)
    return result
