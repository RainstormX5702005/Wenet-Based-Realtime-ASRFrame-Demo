"""Noise reduction step."""

from __future__ import annotations

from dataclasses import dataclass

import noisereduce as nr
import numpy as np

from preprocess.steps.registry import register_step
from preprocess.types import AudioData


@dataclass(frozen=True)
class NoiseReducerConfig:
    """Configuration for noise reduction."""

    enabled: bool = True
    stationary: bool = False
    prop_decrease: float = 0.8
    n_fft: int = 512


@register_step
class NoiseReducer:
    """Applies conservative noise reduction."""

    def __init__(self, config: NoiseReducerConfig | None = None):
        self.config = config or NoiseReducerConfig()

    def process(self, data: AudioData) -> AudioData:
        if not self.config.enabled or data.samples.size < self.config.n_fft:
            return data

        reduced = nr.reduce_noise(
            y=data.samples,
            sr=data.sample_rate,
            y_noise=data.noise_reference,
            stationary=self.config.stationary,
            prop_decrease=self.config.prop_decrease,
            n_fft=self.config.n_fft,
            use_tqdm=False,
        )
        data.samples = np.asarray(reduced, dtype=np.float32)
        return data
