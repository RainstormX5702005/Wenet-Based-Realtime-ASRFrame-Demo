"""Shared audio DSP helpers used across pipeline modules."""

from __future__ import annotations

import math

import numpy as np


EPSILON = 1e-8


def db_to_linear(db: float) -> float:
    """Converts a dB value to linear amplitude."""

    return 10.0 ** (db / 20.0)


def linear_to_db(value: float) -> float:
    """Converts a linear amplitude value to dB."""

    return 20.0 * math.log10(max(value, EPSILON))


def rms_db(samples: np.ndarray) -> float:
    """Computes RMS level in dB for mono float audio."""

    if samples.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float32)))))
    return linear_to_db(rms)
