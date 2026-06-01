"""Wenet transcription wrapper for queued audio tasks.

This module is deliberately thin: it bridges queued NumPy audio to
temporary wav files so the existing model.transcribe(path) API can be
used without modification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

import soundfile as sf

from audio_queue import AudioTask


@dataclass(frozen=True)
class TranscriptionConfig:
    """Configuration for Wenet file-based transcription.

    Attributes:
        temp_suffix: Temporary audio file suffix.
        unlink_temp_file: Whether temporary files are removed after use.
    """

    temp_suffix: str = ".wav"
    unlink_temp_file: bool = True


@dataclass(frozen=True)
class TranscriptionResult:
    """Text produced from one audio task.

    Attributes:
        segment_id: Segment identifier copied from the audio task.
        window_index: Window index copied from the audio task.
        text: Recognized text, or an empty string on failure.
        duration_ms: Source audio duration in milliseconds.
        is_final_window: Whether this result completes its segment.
        error: Optional error message when Wenet transcription fails.
    """

    segment_id: int
    window_index: int
    text: str
    duration_ms: float
    is_final_window: bool
    error: str | None = None


class WenetTranscriber:
    """Runs Wenet transcription for queued audio tasks."""

    def __init__(self, model, config: TranscriptionConfig | None = None):
        """Initializes the transcriber.

        Args:
            model: Loaded Wenet model exposing transcribe(path).
            config: Optional transcription configuration.
        """

        self.model = model
        self.config = config or TranscriptionConfig()

    def transcribe(self, task: AudioTask) -> TranscriptionResult:
        """Transcribes one queued audio task with Wenet.

        Args:
            task: Audio task produced by the audio_queue module.

        Returns:
            Transcription result for the task.
        """

        duration_ms = task.audio.size / task.sample_rate * 1000.0
        temp_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                suffix=self.config.temp_suffix, delete=False
            ) as f:
                temp_path = Path(f.name)
                sf.write(f.name, task.audio, task.sample_rate)

            result = self.model.transcribe(str(temp_path))
            return TranscriptionResult(
                segment_id=task.segment_id,
                window_index=task.window_index,
                text=result.text,
                duration_ms=duration_ms,
                is_final_window=task.is_final_window,
            )
        except (
            Exception
        ) as exc:  # noqa: BLE001 - keep worker alive after Wenet failures.
            return TranscriptionResult(
                segment_id=task.segment_id,
                window_index=task.window_index,
                text="",
                duration_ms=duration_ms,
                is_final_window=task.is_final_window,
                error=str(exc),
            )
        finally:
            if self.config.unlink_temp_file and temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _postprocess():
        pass
