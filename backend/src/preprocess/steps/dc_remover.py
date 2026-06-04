"""DC offset removal step."""

from __future__ import annotations

import numpy as np

from preprocess.steps.registry import register_step
from preprocess.types import AudioData


@register_step
class DCRemover:
    """Removes constant offset from audio samples."""

    def process(self, data: AudioData) -> AudioData:
        if data.samples.size == 0:
            return data
        centered = data.samples - np.mean(data.samples, dtype=np.float32)
        data.samples = centered.astype(np.float32, copy=False)
        return data
