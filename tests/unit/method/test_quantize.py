from __future__ import annotations

import numpy as np

from denser.method.quantize import sensitivity_weighted_steps, uniform_quantize


def test_uniform_quantization_is_deterministic() -> None:
    values = np.array([-3.2, -1.1, 0.0, 1.1, 3.2], dtype=np.float64)
    first = uniform_quantize(values, 2.0)
    second = uniform_quantize(values.copy(), 2.0)
    np.testing.assert_array_equal(first, second)
    assert first.dtype == np.int32


def test_sensitive_coefficients_receive_finer_steps_with_trust_caps() -> None:
    sensitivity = np.array([0.01, 1.0, 100.0], dtype=np.float64)
    steps = sensitivity_weighted_steps(sensitivity, base_step=8.0, trust_ratio=4.0)
    assert steps[2] < steps[1] < steps[0]
    assert steps.min() >= 2.0
    assert steps.max() <= 32.0


def test_invalid_quantization_parameters_fail_closed() -> None:
    for step, ratio in ((0.0, 4.0), (1.0, 0.5)):
        try:
            sensitivity_weighted_steps(np.ones(2), step, ratio)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid quantization parameters accepted")
