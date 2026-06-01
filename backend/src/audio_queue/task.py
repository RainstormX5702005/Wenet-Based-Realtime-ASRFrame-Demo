"""Internal audio queue task protocol.

The dataclasses defined here are a small Python-native protocol that connects
preprocessing and transcription.  They are not a network protocol.
"""

from __future__ import annotations
import numpy as np

from dataclasses import dataclass
from enum import Enum


class QueueDropPolicy(str, Enum):
    """Supported bounded-queue overflow policies."""

    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


@dataclass(frozen=True)
class AudioTask:
    """Audio payload scheduled for Wenet transcription.

    Attributes:
        segment_id: Monotonic speech segment identifier within one connection.
        window_index: Zero-based index for windows from the same segment.
        audio: Mono float32 audio samples at sample_rate.
        sample_rate: Audio sample rate in Hz.
        is_final_window: Whether this is the final task for the segment.
        created_at: Monotonic timestamp used for latency diagnostics.
    """

    segment_id: int
    window_index: int
    audio: np.ndarray
    sample_rate: int
    is_final_window: bool
    created_at: float
