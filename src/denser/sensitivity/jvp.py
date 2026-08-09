from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


class JvpVjpOperator(Protocol):
    input_dim: int
    output_dim: int

    def jvp(self, vector: np.ndarray) -> np.ndarray: ...

    def vjp(self, vector: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class MatrixOperator:
    matrix: np.ndarray

    @property
    def input_dim(self) -> int:
        return int(self.matrix.shape[1])

    @property
    def output_dim(self) -> int:
        return int(self.matrix.shape[0])

    def jvp(self, vector: np.ndarray) -> np.ndarray:
        return self.matrix @ np.asarray(vector, dtype=np.float64)

    def vjp(self, vector: np.ndarray) -> np.ndarray:
        return self.matrix.T @ np.asarray(vector, dtype=np.float64)


def linear_operator(matrix: np.ndarray) -> MatrixOperator:
    values = np.asarray(matrix, dtype=np.float64)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("linear operator matrix must be finite and two-dimensional")
    return MatrixOperator(values.copy())


def identity_basis(dimension: int) -> np.ndarray:
    if dimension <= 0:
        raise ValueError("basis dimension must be positive")
    return np.eye(dimension, dtype=np.float64)
