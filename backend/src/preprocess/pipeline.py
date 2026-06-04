"""Speech segment preprocessing pipeline.

The pipeline owns all preprocessing details including VAD-based segmentation
and enhancement/validation steps.  The public entrypoint is a shared
`process` method that forwards an ``AudioData`` payload through ordered steps.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from silero_vad import load_silero_vad
from preprocess.steps.base import PreprocessStep
from preprocess.steps.registry import is_registered
from preprocess.types import AudioData
from utils.audio_utils import rms_db


@dataclass(frozen=True)
class PreprocessConfig:
    """Runtime defaults used by composed preprocess steps."""

    sample_rate: int = 16000
    chunk_size: int = 512
    min_speech_duration_ms: float = 250.0
    min_active_rms_db: float = -45.0
    target_rms_db: float = -23.0
    noise_reduce_enabled: bool = True


class PreprocessPipeline:
    """Executes a caller-defined ordered list of preprocess steps."""

    def __init__(
        self,
        steps: list[PreprocessStep],
        config: PreprocessConfig | None = None,
    ):
        """Initializes the pipeline and validates step contracts.

        Args:
            steps: Ordered preprocess steps. If ``None``, a default chain is used.
            config: Optional pipeline configuration.
            vad_model: Shared Silero model instance for VAD step.
        """

        self.steps: list[PreprocessStep] = steps or []
        self.config = config or PreprocessConfig()
        self.vad_model = load_silero_vad()
        self._validate_steps(self.steps)

    @staticmethod
    def _validate_steps(steps: list[PreprocessStep]) -> None:
        """Fails fast when any step violates the public contract."""

        seen: set[str] = set()
        for step in steps:
            process = getattr(step, "process", None)
            if not callable(process):
                raise TypeError(
                    f"Invalid preprocess step {step!r}: missing callable process()"
                )
            if not is_registered(step):
                raise TypeError(
                    f"Invalid preprocess step {type(step).__name__}: unregistered"
                )

            step_name = type(step).__name__
            if step_name in seen:
                raise ValueError(f"Duplicate preprocess step detected: {step_name}")
            seen.add(step_name)

    def process(self, data: AudioData) -> AudioData | None:
        """Runs an ``AudioData`` payload through all configured steps."""

        if self.steps is []:
            return data

        for step in self.steps:
            if not data.accepted:
                return data

            result = step.process(data)
            if result is None:
                return None
            if result.accepted is False:
                return result

            data = result
        return data

    def process_chunk(
        self,
        samples: np.ndarray,
        noise_reference: np.ndarray | None = None,
        metadata: dict | None = None,
    ) -> AudioData | None:
        """Constructs ``AudioData`` and runs one incoming chunk."""

        data = AudioData(
            samples=np.asarray(samples, dtype=np.float32),
            sample_rate=self.config.sample_rate,
            noise_reference=noise_reference,
            metadata=metadata or {},
        )
        return self.process(data)

    def validate_segment(self, data: AudioData) -> AudioData:
        """Validates completed segment metadata before downstream queueing."""

        if not data.accepted:
            return data

        duration_ms = data.samples.size / self.config.sample_rate * 1000.0
        level_db = rms_db(data.samples)

        if duration_ms < self.config.min_speech_duration_ms:
            data.accepted = False
            data.reason = "too_short"
            data.samples = np.array([], dtype=np.float32)
            return data

        if level_db < self.config.min_active_rms_db:
            data.accepted = False
            data.reason = "too_quiet"
            data.samples = np.array([], dtype=np.float32)
            return data

        data.reason = "accepted"
        return data

    @property
    def default_step_names(self) -> list[str]:
        return [type(step).__name__ for step in self.steps]


__all__ = [
    "PreprocessConfig",
    "PreprocessPipeline",
]
