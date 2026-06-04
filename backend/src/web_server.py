import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from asr_logging import AsrLogConfig, AsrResultLogger
from audio_queue import AudioTaskQueue, build_audio_tasks
from preprocess import (
    PreprocessPipeline,
    DCRemover,
    StreamingVadSegmenter,
    RmsNormalizer,
    AudioPeakLimiter,
)
from transcription import (
    TranscriberFactoryConfig,
    TranscriptionWorker,
    create_transcriber,
)

CHANNELS = 1
SAMPLE_RATE = 16000
CHUNK_SIZE = 512

SRC_DIR = Path(__file__).resolve().parent
MODEL_DIR = SRC_DIR.parent / "models"
SCRIPT_DIR = SRC_DIR.parent / "scripts"
LOG_DIR = SRC_DIR.parent / "logs"


@asynccontextmanager
async def lifespan(app: FastAPI):
    asr_logger = AsrResultLogger(AsrLogConfig(log_dir=LOG_DIR))
    await asr_logger.start()
    app.state.asr_logger = asr_logger
    transcriber = None

    try:
        transcriber = create_transcriber(
            TranscriberFactoryConfig(
                backend="wenet",
                model_dir=MODEL_DIR,
                device="cuda",
                beam_size=10,
                script_path=SCRIPT_DIR / "wenet_serve.sh",
            )
        )
        app.state.transcriber = transcriber
        asr_logger.record_event("transcriber_ready", backend="wenet")

        yield
    finally:
        if transcriber is not None:
            transcriber.close()
            asr_logger.record_event("transcriber_closed", backend="wenet")
        await asr_logger.stop()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    preprocess = PreprocessPipeline(
        [
            DCRemover(),
            StreamingVadSegmenter(sample_rate=SAMPLE_RATE, chunk_size=CHUNK_SIZE),
            RmsNormalizer(),
            AudioPeakLimiter(),
        ]
    )
    task_queue = AudioTaskQueue()
    worker = TranscriptionWorker(task_queue, ws.app.state.transcriber)

    async def send_result(result):
        """Sends successful transcription text to the current WebSocket."""

        ws.app.state.asr_logger.record_result(result)
        if result.error:
            ws.app.state.asr_logger.record_event(
                "transcription_error",
                segment_id=result.segment_id,
                window_index=result.window_index,
                error=result.error,
            )
            return
        if result.text:
            await ws.send_text(result.text)

    worker_task = asyncio.create_task(worker.run(send_result))
    segment_id = 0

    try:
        while True:
            data = await ws.receive_bytes()
            samples = np.frombuffer(data, dtype=np.float32).copy()

            if len(samples) != CHUNK_SIZE:
                continue

            prepared = preprocess.process_chunk(samples)
            if prepared is None:
                continue

            prepared = preprocess.validate_segment(prepared)
            if not prepared.accepted:
                continue

            for task in build_audio_tasks(prepared, segment_id=segment_id):
                await task_queue.push(task)
            segment_id += 1

    except WebSocketDisconnect:
        pass
    finally:
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task


static_dir = SRC_DIR / "static"
app.mount(
    "/",
    StaticFiles(directory=str(static_dir), html=True),
    name="static",
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=1557)
