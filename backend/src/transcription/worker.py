"""Async worker for queued Wenet transcription.

The worker runs blocking transcription through asyncio.to_thread so the
WebSocket receive loop stays responsive.  It consumes tasks serially to
avoid GPU contention from concurrent Wenet calls.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from audio_queue import AudioTaskQueue
from transcription.wenet_transcriber import TranscriptionResult, WenetTranscriber


ResultCallback = Callable[[TranscriptionResult], Awaitable[None]]


class TranscriptionWorker:
    """Consumes queued audio tasks and emits transcription results."""

    def __init__(self, task_queue: AudioTaskQueue, transcriber: WenetTranscriber):
        """Initializes the worker.

        Args:
            task_queue: Queue that provides audio tasks.
            transcriber: Wenet transcriber used for each task.
        """

        self.task_queue = task_queue
        self.transcriber = transcriber

    async def run(self, on_result: ResultCallback) -> None:
        """Runs until cancelled and calls back with each transcription result.

        Args:
            on_result: Async callback that receives transcription results.
        """

        while True:
            task = await self.task_queue.get()
            try:
                result = await asyncio.to_thread(self.transcriber.transcribe, task)
                await on_result(result)
            finally:
                self.task_queue.task_done()
