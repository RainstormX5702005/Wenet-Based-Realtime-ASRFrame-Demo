"""RMS normalization step."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from preprocess.steps.registry import register_step
from preprocess.types import AudioData
from utils.audio_utils import db_to_linear, rms_db


@dataclass(frozen=True)
class RmsNormalizerConfig:
    """Configuration for RMS normalization."""

    target_rms_db: float = -23.0
    max_gain_db: float = 18.0


@register_step
class RmsNormalizer:
    """Normalizes RMS level toward a target with capped gain."""

    def __init__(self, config: RmsNormalizerConfig | None = None):
        self.config = config or RmsNormalizerConfig()

    def process(self, data: AudioData) -> AudioData:
        if data.samples.size == 0:
            return data
        current_db = rms_db(data.samples)
        gain_db = min(self.config.target_rms_db - current_db, self.config.max_gain_db)
        data.samples = (data.samples * db_to_linear(gain_db)).astype(
            np.float32, copy=False
        )
        return data
