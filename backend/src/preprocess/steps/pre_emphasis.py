"""Pre-emphasis filter step."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from preprocess.steps.registry import register_step
from preprocess.types import AudioData


@dataclass(frozen=True)
class PreEmphasisConfig:
    """Configuration for pre-emphasis."""

    coeff: float = 0.97


@register_step
class PreEmphasis:
    """Applies a pre-emphasis filter to audio."""

    def __init__(self, config: PreEmphasisConfig | None = None):
        self.config = config or PreEmphasisConfig()

    def process(self, data: AudioData) -> AudioData:
        if data.samples.size <= 1:
            return data
        emphasized = np.empty_like(data.samples)
        emphasized[0] = data.samples[0]
        emphasized[1:] = data.samples[1:] - self.config.coeff * data.samples[:-1]
        data.samples = emphasized.astype(np.float32, copy=False)
        return data
