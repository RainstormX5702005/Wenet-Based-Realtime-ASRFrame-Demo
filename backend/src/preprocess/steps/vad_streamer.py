"""Streaming VAD + chunk buffering step."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from silero_vad import VADIterator, load_silero_vad

from preprocess.steps.registry import register_step
from preprocess.types import AudioData


@dataclass(frozen=True)
class StreamingVadConfig:
    """Configuration for streaming Silero VAD."""

    threshold: float = 0.35
    min_silence_duration_ms: int = 120
    speech_pad_ms: int = 40
    pre_speech_ms: int = 300


@register_step
class StreamingVadSegmenter:
    """Segments audio stream into utterances using Silero VAD."""

    def __init__(
        self,
        sample_rate: int,
        chunk_size: int,
        config: StreamingVadConfig | None = None,
        model: object | None = None,
    ):
        self.config = config or StreamingVadConfig()
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.model = model or load_silero_vad()
        self.vad_iter = VADIterator(
            self.model,
            threshold=self.config.threshold,
            min_silence_duration_ms=self.config.min_silence_duration_ms,
            speech_pad_ms=self.config.speech_pad_ms,
        )
        self._speaking = False
        self._audio_chunks: list[np.ndarray] = []
        self._prev_chunks: list[np.ndarray] = []
        self._prev_max = int(self.config.pre_speech_ms * sample_rate / 1000 / chunk_size)

    def process(self, data: AudioData) -> AudioData | None:
        if data.samples.size != self.chunk_size:
            return None

        speech_dict = self.vad_iter(data.samples)

        if speech_dict and "start" in speech_dict and not self._speaking:
            self._speaking = True

        if self._speaking:
            self._audio_chunks.append(data.samples)
        else:
            self._prev_chunks.append(data.samples)
            if len(self._prev_chunks) > self._prev_max:
                self._prev_chunks.pop(0)

        if not (speech_dict and "end" in speech_dict):
            return None

        self._speaking = False
        raw_audio = np.concatenate(self._prev_chunks + self._audio_chunks)
        noise_reference = (
            np.concatenate(self._prev_chunks) if self._prev_chunks else None
        )
        self._audio_chunks = []
        return AudioData(
            samples=raw_audio.astype(np.float32, copy=False),
            sample_rate=data.sample_rate,
            noise_reference=None if noise_reference is None else noise_reference,
            accepted=True,
            reason="accepted",
            metadata=dict(data.metadata),
        )
