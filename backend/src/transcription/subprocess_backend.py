"""Persistent subprocess-backed ASR transcriber."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import selectors
import subprocess
import tempfile
import threading
from typing import Any

import soundfile as sf

from audio_queue import AudioTask
from transcription.base import RawTranscriptionResult, TranscriptionResult


@dataclass(frozen=True)
class SubprocessTranscriberConfig:
    """Configuration for a JSONL subprocess ASR backend."""

    command: list[str]
    model_name: str = "wenet"
    ready_timeout_s: float = 60.0
    close_timeout_s: float = 5.0
    temp_suffix: str = ".wav"
    unlink_temp_file: bool = True


class SubprocessTranscriber:
    """Sends temp wav requests to one persistent JSONL child process."""

    def __init__(self, config: SubprocessTranscriberConfig):
        self.config = config
        self._lock = threading.Lock()
        self._closed = False
        self._process = subprocess.Popen(
            config.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            daemon=True,
        )
        self._stderr_thread.start()
        try:
            ready = self._read_json_line(timeout_s=config.ready_timeout_s)
            if ready.get("status") != "ready":
                raise RuntimeError(
                    f"ASR subprocess did not become ready: {ready}"
                )
        except Exception:
            self._terminate_process()
            raise

    def transcribe(self, task: AudioTask) -> TranscriptionResult:
        duration_ms = task.audio.size / task.sample_rate * 1000.0
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=self.config.temp_suffix, delete=False
            ) as f:
                temp_path = Path(f.name)
                sf.write(f.name, task.audio, task.sample_rate)

            raw = self._request(temp_path, task.sample_rate)
            return TranscriptionResult(
                segment_id=task.segment_id,
                window_index=task.window_index,
                text=raw.text,
                duration_ms=duration_ms,
                is_final_window=task.is_final_window,
                raw=raw,
            )
        except Exception as exc:  # noqa: BLE001
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

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            try:
                if self._process.poll() is None:
                    self._write_json_line({"command": "shutdown"})
            except Exception:
                pass
        try:
            self._process.wait(timeout=self.config.close_timeout_s)
        except subprocess.TimeoutExpired:
            self._terminate_process()

    def _request(
        self, wav_path: Path, sample_rate: int
    ) -> RawTranscriptionResult:
        with self._lock:
            self._write_json_line(
                {"wav": str(wav_path), "sample_rate": sample_rate}
            )
            response = self._read_json_line()

        status = response.get("status", "ok")
        if status == "error":
            message = response.get("error") or response.get("message")
            raise RuntimeError(str(message or "ASR error"))
        if status not in {"ok", "result"}:
            raise RuntimeError(f"Unexpected ASR response status: {status}")

        return RawTranscriptionResult(
            text=str(response.get("text", "")),
            nbest_tokens=self._list_of_int_lists(
                response.get("nbest_tokens", [])
            ),
            nbest_scores=[
                float(score) for score in response.get("nbest_scores", [])
            ],
            model_name=str(response.get("model_name", self.config.model_name)),
        )

    def _write_json_line(self, payload: dict[str, Any]) -> None:
        if self._process.stdin is None:
            raise RuntimeError("ASR subprocess stdin is closed")
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()

    def _read_json_line(
        self,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        if self._process.stdout is None:
            raise RuntimeError("ASR subprocess stdout is closed")
        if timeout_s is not None:
            selector = selectors.DefaultSelector()
            selector.register(self._process.stdout, selectors.EVENT_READ)
            try:
                if not selector.select(timeout_s):
                    raise TimeoutError(
                        "Timed out waiting for ASR ready response"
                    )
            finally:
                selector.close()
        line = self._process.stdout.readline()
        if not line:
            raise RuntimeError("ASR subprocess closed stdout")
        return json.loads(line)

    def _terminate_process(self) -> None:
        if self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=self.config.close_timeout_s)
        except subprocess.TimeoutExpired:
            self._process.kill()
            try:
                self._process.wait(timeout=self.config.close_timeout_s)
            except subprocess.TimeoutExpired:
                pass

    def _drain_stderr(self) -> None:
        if self._process.stderr is None:
            return
        for _line in self._process.stderr:
            pass

    @staticmethod
    def _list_of_int_lists(value: Any) -> list[list[int]]:
        return [[int(token) for token in tokens] for tokens in value]
