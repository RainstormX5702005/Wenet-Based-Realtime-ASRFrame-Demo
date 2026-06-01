import asyncio
from contextlib import suppress
from pathlib import Path

import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from silero_vad import VADIterator, load_silero_vad
from wenet.cli.model import load_model

from audio_queue import AudioTaskQueue, build_audio_tasks
from preprocess import PreprocessPipeline
from transcription import TranscriptionWorker, WenetTranscriber

CHANNELS = 1
SAMPLE_RATE = 16000
CHUNK_SIZE = 512
# 300 ms pre-speech buffer gives Wenet more lead-in context.
PREV_CHUNKS = int(0.3 * SAMPLE_RATE / CHUNK_SIZE)

SRC_DIR = Path(__file__).resolve().parent
MODEL_DIR = SRC_DIR.parent / "models"

app = FastAPI()

print("Loading SenseVoice model...")
model = load_model(str(MODEL_DIR), device="cuda")
print("Model loaded.")

vad_model = load_silero_vad()
print("VAD loaded.")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    preprocess = PreprocessPipeline()
    vad_iter = VADIterator(vad_model, **preprocess.vad_kwargs)
    task_queue = AudioTaskQueue()
    transcriber = WenetTranscriber(model)
    worker = TranscriptionWorker(task_queue, transcriber)

    async def send_result(result):
        """Sends successful transcription text to the current WebSocket."""

        if result.error:
            print(f"Transcription failed: {result.error}")
            return
        if result.text:
            await ws.send_text(result.text)

    worker_task = asyncio.create_task(worker.run(send_result))
    audio_chunks = []
    prev_audio_chunks = []
    speaking = False
    segment_id = 0

    try:
        while True:
            data = await ws.receive_bytes()
            samples = np.frombuffer(data, dtype=np.float32).copy()

            if len(samples) != CHUNK_SIZE:
                continue

            speech_dict = vad_iter(samples)

            if speech_dict:
                if not speaking and "start" in speech_dict:
                    speaking = True

            if speaking:
                audio_chunks.append(samples)
            else:
                prev_audio_chunks.append(samples)
                if len(prev_audio_chunks) > PREV_CHUNKS:
                    prev_audio_chunks.pop(0)

            if speech_dict and "end" in speech_dict:
                speaking = False
                raw_audio = np.concatenate(prev_audio_chunks + audio_chunks)
                noise_reference = (
                    np.concatenate(prev_audio_chunks) if prev_audio_chunks else None
                )
                audio_chunks = []

                prepared = preprocess.process_segment(
                    raw_audio, noise_reference=noise_reference
                )
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
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=6975)
