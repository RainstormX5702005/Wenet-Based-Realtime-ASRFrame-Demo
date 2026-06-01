"""Bounded async queue for prepared audio transcription tasks.

The queue prevents unlimited latency and memory growth when model
transcription is slower than audio ingestion.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from audio_queue.task import AudioTask, QueueDropPolicy


@dataclass(frozen=True)
class AudioTaskQueueConfig:
    """Configuration for the segment-to-transcription queue.

    Attributes:
        max_queue_size: Maximum number of pending transcription tasks.
        drop_policy: Overflow policy used when the queue is full.
    """

    max_queue_size: int = 3
    drop_policy: QueueDropPolicy = QueueDropPolicy.DROP_OLDEST


class AudioTaskQueue:
    """Small wrapper around asyncio.Queue with explicit overflow behavior."""

    def __init__(self, config: AudioTaskQueueConfig | None = None):
        """Initializes the bounded task queue.

        Args:
            config: Optional queue configuration.
        """

        self.config = config or AudioTaskQueueConfig()
        self._queue: asyncio.Queue[AudioTask] = asyncio.Queue(
            maxsize=self.config.max_queue_size
        )

    async def push(self, task: AudioTask) -> bool:
        """pushs a task into the queue using the configured overflow policy.

        Args:
            task: Audio task to enqueue.

        Returns:
            True if the new task was queued, False if it was dropped.
        """

        if not self._queue.full():
            await self._queue.put(task)
            return True

        if self.config.drop_policy == QueueDropPolicy.DROP_NEWEST:
            return False

        dropped = self._queue.get_nowait()
        self._queue.task_done()
        del dropped
        await self._queue.put(task)
        return True

    async def get(self) -> AudioTask:
        """Gets the next queued audio task."""

        return await self._queue.get()

    def task_done(self) -> None:
        """Marks the current task as processed."""

        self._queue.task_done()

    def qsize(self) -> int:
        """Returns the current number of queued tasks."""

        return self._queue.qsize()
