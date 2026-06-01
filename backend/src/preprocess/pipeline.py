"""Speech segment preprocessing pipeline.

The pipeline owns VAD-adjacent audio preparation: it validates completed
speech segments, applies conservative enhancement, and returns prepared
segments for downstream queueing.  It does not own queueing, windowing,
or Wenet calls.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from preprocess.audio_enhance import AudioEnhanceConfig, AudioEnhancer
from utils.audio_utils import rms_db


@dataclass(frozen=True)
class PreprocessConfig:
    """Configuration for VAD-adjacent speech preprocessing.

    Attributes:
        sample_rate: Audio sample rate in Hz.
        chunk_size: Number of samples per incoming chunk.
        min_speech_duration_ms: Minimum accepted speech segment duration.
        min_active_rms_db: Minimum RMS level accepted as useful audio.
        target_rms_db: Target RMS level passed to the enhancer.
        noise_reduce_enabled: Whether to run conservative noise reduction.
    """

    sample_rate: int = 16000
    chunk_size: int = 512
    min_speech_duration_ms: int = 250
    min_active_rms_db: float = -45.0
    target_rms_db: float = -23.0
    noise_reduce_enabled: bool = True


@dataclass(frozen=True)
class PreparedSegment:
    """Preprocessed segment emitted to the audio_queue module.

    Attributes:
        accepted: Whether the segment should be queued for transcription.
        reason: Decision reason for diagnostics.
        audio: Enhanced mono float32 audio, empty when rejected.
        sample_rate: Audio sample rate in Hz.
        duration_ms: Segment duration in milliseconds.
        rms_db: Original segment RMS level in dB.
    """

    accepted: bool
    reason: str
    audio: np.ndarray
    sample_rate: int
    duration_ms: float
    rms_db: float


def recommended_vad_kwargs() -> dict[str, float | int]:
    """Returns Silero VAD defaults for the MVP pipeline."""

    return {
        "threshold": 0.35,
        "min_silence_duration_ms": 120,
        "speech_pad_ms": 40,
    }


class PreprocessPipeline:
    """Validates and enhances completed speech segments."""

    def __init__(self, config: PreprocessConfig | None = None):
        """Initializes the preprocessing pipeline.

        Args:
            config: Optional preprocessing configuration.
        """

        self.config = config or PreprocessConfig()
        self.vad_kwargs = recommended_vad_kwargs()
        self.enhancer = AudioEnhancer(
            AudioEnhanceConfig(
                sample_rate=self.config.sample_rate,
                target_rms_db=self.config.target_rms_db,
                noise_reduce_enabled=self.config.noise_reduce_enabled,
            )
        )

    def process_segment(
        self,
        samples: np.ndarray,
        noise_reference: np.ndarray | None = None,
    ) -> PreparedSegment:
        """Validates and enhances one completed speech segment.

        Args:
            samples: Raw mono float audio from VAD start to VAD end.
            noise_reference: Optional non-speech audio before the segment.

        Returns:
            Prepared segment for downstream queueing.
        """

        audio = np.asarray(samples, dtype=np.float32)
        duration_ms = audio.size / self.config.sample_rate * 1000.0
        level_db = rms_db(audio)

        if duration_ms < self.config.min_speech_duration_ms:
            return self._reject("too_short", duration_ms, level_db)

        if level_db < self.config.min_active_rms_db:
            return self._reject("too_quiet", duration_ms, level_db)

        enhanced = self.enhancer.enhance(audio, noise_reference=noise_reference)
        return PreparedSegment(
            accepted=True,
            reason="accepted",
            audio=enhanced,
            sample_rate=self.config.sample_rate,
            duration_ms=duration_ms,
            rms_db=level_db,
        )

    def _reject(self, reason: str, duration_ms: float, level_db: float) -> PreparedSegment:
        """Builds a rejected segment result with empty audio."""

        return PreparedSegment(
            accepted=False,
            reason=reason,
            audio=np.array([], dtype=np.float32),
            sample_rate=self.config.sample_rate,
            duration_ms=duration_ms,
            rms_db=level_db,
        )
