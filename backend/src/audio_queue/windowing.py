"""Window planning for prepared audio segments.

Splits long prepared segments into one or more AudioTask objects with
configurable overlap so downstream transcription does not need to know
whether a task came from a whole segment or a sliced window.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np

from audio_queue.task import AudioTask
from preprocess.types import AudioData


@dataclass(frozen=True)
class WindowingConfig:
    """Configuration for splitting long segments into ASR tasks.

    Attributes:
        window_duration_ms: Maximum duration of one transcription task.
        window_step_ms: Distance between adjacent window starts.
        min_window_duration_ms: Minimum trailing window duration to keep.
    """

    window_duration_ms: int = 8000
    window_step_ms: int = 6000
    min_window_duration_ms: int = 1200


def build_audio_tasks(
    segment: AudioData,
    segment_id: int,
    config: WindowingConfig | None = None,
) -> list[AudioTask]:
    """Builds transcription tasks from one accepted prepared segment.

    Args:
        segment: Accepted prepared audio segment.
        segment_id: Segment identifier assigned by the caller.
        config: Optional windowing configuration.

    Returns:
        One or more audio tasks in playback order.
    """

    if not segment.accepted or segment.samples.size == 0:
        return []

    window_config = config or WindowingConfig()
    sample_rate = segment.sample_rate
    window_samples = int(sample_rate * window_config.window_duration_ms / 1000)
    step_samples = int(sample_rate * window_config.window_step_ms / 1000)
    min_samples = int(sample_rate * window_config.min_window_duration_ms / 1000)

    # 音频长度不高于一个窗口是可以直接切分的，不需要考虑重叠
    if segment.samples.size <= window_samples:
        return [
            AudioTask(
                segment_id=segment_id,
                window_index=0,
                audio=segment.samples.astype(np.float32, copy=False),
                sample_rate=sample_rate,
                is_final_window=True,
                created_at=time.monotonic(),
            )
        ]

    tasks: list[AudioTask] = []
    start = 0
    window_index = 0
    while start < segment.samples.size:
        end = min(start + window_samples, segment.samples.size)
        chunk = segment.samples[start:end]
        if chunk.size < min_samples:
            break

        next_start = start + step_samples
        is_final = (
            end >= segment.samples.size or segment.samples.size - next_start < min_samples
        )
        tasks.append(
            AudioTask(
                segment_id=segment_id,
                window_index=window_index,
                audio=chunk.astype(np.float32, copy=False),
                sample_rate=sample_rate,
                is_final_window=is_final,
                created_at=time.monotonic(),
            )
        )
        if is_final:
            break
        start = next_start
        window_index += 1

    return tasks
