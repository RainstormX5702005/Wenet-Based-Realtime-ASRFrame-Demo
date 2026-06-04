from __future__ import annotations

import pytest
from fastapi import FastAPI

import web_server


def test_lifespan_cleans_up_logger_and_transcriber_when_vad_load_fails(
    monkeypatch,
):
    events = []

    class FakeLogger:
        def __init__(self, config):
            self.config = config

        async def start(self):
            events.append("logger_start")

        async def stop(self):
            events.append("logger_stop")

        def record_event(self, event, **fields):
            events.append(event)

    class FakeTranscriber:
        def close(self):
            events.append("transcriber_close")

    monkeypatch.setattr(web_server, "AsrResultLogger", FakeLogger)
    monkeypatch.setattr(
        web_server,
        "create_transcriber",
        lambda config: FakeTranscriber(),
    )

    def fail_vad_load():
        raise RuntimeError("vad failed")

    monkeypatch.setattr(web_server, "load_vad_model", fail_vad_load)

    app = FastAPI()
    manager = web_server.lifespan(app)

    with pytest.raises(RuntimeError, match="vad failed"):
        manager.__aenter__().send(None)

    assert "logger_start" in events
    assert "transcriber_close" in events
    assert "logger_stop" in events
