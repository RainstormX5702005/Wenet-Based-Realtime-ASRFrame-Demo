"""Shared payload types for preprocess steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class AudioData:
    """Payload passed through preprocess steps."""

    samples: np.ndarray
    sample_rate: int
    noise_reference: np.ndarray | None = None
    accepted: bool = True
    reason: str = "accepted"
    metadata: dict[str, Any] = field(default_factory=dict)
