from __future__ import annotations

import numpy as np


def uniform_quantize(values: np.ndarray, step: float) -> np.ndarray:
    if not np.isfinite(step) or step <= 0:
        raise ValueError("quantization step must be finite and positive")
    return np.rint(np.asarray(values, dtype=np.float64) / step).astype(np.int32)


def sensitivity_weighted_steps(
    sensitivity: np.ndarray, base_step: float, trust_ratio: float
) -> np.ndarray:
    if not np.isfinite(base_step) or base_step <= 0:
        raise ValueError("base quantization step must be finite and positive")
    if not np.isfinite(trust_ratio) or trust_ratio < 1:
        raise ValueError("trust ratio must be at least one")
    weights = np.asarray(sensitivity, dtype=np.float64)
    if weights.size == 0 or not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError("sensitivity weights must be finite and non-negative")
    positive = np.maximum(weights, 1e-12)
    normalizer = float(np.median(positive))
    raw = base_step / np.sqrt(positive / max(normalizer, 1e-12))
    return np.clip(raw, base_step / trust_ratio, base_step * trust_ratio)
