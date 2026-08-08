from __future__ import annotations

import numpy as np

from denser.sensitivity.dns import diagnostic_nullity_spectrum
from denser.sensitivity.jvp import identity_basis, linear_operator
from denser.sensitivity.randomized import estimate_spectrum


def test_randomized_spectrum_recovers_known_rank() -> None:
    matrix = np.diag([5.0, 2.0, 0.0, 0.0])
    spectrum = estimate_spectrum(
        linear_operator(matrix), identity_basis(4), seed=7, rank=4
    )
    np.testing.assert_allclose(spectrum.values, [5.0, 2.0, 0.0, 0.0], atol=1e-6)
    assert spectrum.approximation_error < 1e-12
    assert spectrum.converged


def test_randomized_spectrum_is_seed_deterministic() -> None:
    matrix = np.arange(30, dtype=np.float64).reshape(5, 6) / 10
    first = estimate_spectrum(linear_operator(matrix), identity_basis(6), seed=19, rank=3)
    second = estimate_spectrum(linear_operator(matrix), identity_basis(6), seed=19, rank=3)
    assert first == second
    assert first.seed == 19
    assert first.rank == 3
    assert 0 <= first.approximation_error <= 1


def test_dns_reports_fraction_below_declared_threshold_without_guarantee() -> None:
    result = diagnostic_nullity_spectrum([5.0, 2.0, 0.1, 0.0], [0.0, 0.2, 3.0])
    assert result == {0.0: 0.25, 0.2: 0.5, 3.0: 0.75}


def test_invalid_rank_or_threshold_fails_closed() -> None:
    operator = linear_operator(np.eye(2))
    try:
        estimate_spectrum(operator, identity_basis(2), seed=1, rank=3)
    except ValueError:
        pass
    else:
        raise AssertionError("oversized rank accepted")
    try:
        diagnostic_nullity_spectrum([1.0], [-1.0])
    except ValueError:
        pass
    else:
        raise AssertionError("negative DNS threshold accepted")
