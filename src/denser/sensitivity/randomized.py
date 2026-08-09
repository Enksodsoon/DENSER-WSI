from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from denser.sensitivity.jvp import JvpVjpOperator


@dataclass(frozen=True, slots=True)
class SensitivitySpectrum:
    values: tuple[float, ...]
    approximation_error: float
    seed: int
    rank: int
    iterations: int
    converged: bool
    residual_history: tuple[float, ...]


def estimate_spectrum(
    operator: JvpVjpOperator,
    basis: np.ndarray,
    seed: int,
    rank: int,
) -> SensitivitySpectrum:
    selected_basis = np.asarray(basis, dtype=np.float64)
    if selected_basis.ndim != 2 or selected_basis.shape[0] != operator.input_dim:
        raise ValueError("basis rows must equal operator input dimension")
    if not np.isfinite(selected_basis).all():
        raise ValueError("basis must be finite")
    maximum_rank = min(operator.output_dim, selected_basis.shape[1])
    if not 1 <= rank <= maximum_rank:
        raise ValueError("requested rank exceeds operator-basis dimensions")
    projected = np.column_stack(
        [operator.jvp(selected_basis[:, index]) for index in range(selected_basis.shape[1])]
    )
    norm = float(np.linalg.norm(projected, ord="fro"))
    if rank == maximum_rank:
        singular_values = np.linalg.svd(projected, compute_uv=False)
        approximation_error = 0.0
        residuals = (0.0,)
        iterations = 0
    else:
        rng = np.random.default_rng(seed)
        sketch_rank = min(selected_basis.shape[1], rank + 4)
        omega = rng.standard_normal((selected_basis.shape[1], sketch_rank))
        sketch = projected @ omega
        q, _ = np.linalg.qr(sketch, mode="reduced")
        residuals_list: list[float] = []
        for _iteration in range(2):
            sketch = projected @ (projected.T @ q)
            q, _ = np.linalg.qr(sketch, mode="reduced")
            residuals_list.append(
                float(np.linalg.norm(projected - q @ (q.T @ projected), ord="fro") / max(norm, 1e-20))
            )
        compact = q.T @ projected
        left, singular_values, right_t = np.linalg.svd(compact, full_matrices=False)
        approximation = (q @ left[:, :rank]) @ (
            singular_values[:rank, None] * right_t[:rank, :]
        )
        approximation_error = float(
            np.linalg.norm(projected - approximation, ord="fro") / max(norm, 1e-20)
        )
        singular_values = singular_values[:rank]
        residuals = tuple(round(value, 15) for value in residuals_list)
        iterations = 2
    cleaned = tuple(0.0 if abs(value) < 1e-14 else float(value) for value in singular_values)
    return SensitivitySpectrum(
        cleaned,
        round(approximation_error, 15),
        seed,
        rank,
        iterations,
        bool(np.isfinite(approximation_error) and approximation_error <= 1.0 + 1e-12),
        residuals,
    )
