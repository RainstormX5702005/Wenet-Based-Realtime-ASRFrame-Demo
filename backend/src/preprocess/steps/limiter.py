"""Peak limiter step."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from preprocess.steps.registry import register_step
from preprocess.types import AudioData


@dataclass(frozen=True)
class PeakLimiterConfig:
    """Configuration for peak limiting."""

    peak: float = 0.95


@register_step
class AudioPeakLimiter:
    """Limits audio samples to a max peak value."""

    def __init__(self, config: PeakLimiterConfig | None = None):
        self.config = config or PeakLimiterConfig()

    def process(self, data: AudioData) -> AudioData:
        if data.samples.size == 0:
            return data

        data.samples = np.clip(
            data.samples, -self.config.peak, self.config.peak
        ).astype(np.float32, copy=False)
        return data
