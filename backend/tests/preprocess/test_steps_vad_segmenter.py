from __future__ import annotations

from unittest.mock import patch

import numpy as np

from preprocess.steps.vad_streamer import StreamingVadSegmenter


def test_vad_segmenter_loads_model_when_not_provided(monkeypatch):
    calls = {"count": 0}

    def fake_load_silero_vad():
        calls["count"] += 1
        return object()

    monkeypatch.setattr("preprocess.steps.vad_streamer.load_silero_vad", fake_load_silero_vad)
    monkeypatch.setattr(
        "preprocess.steps.vad_streamer.VADIterator",
        lambda *args, **kwargs: (lambda chunk: None),
    )

    seg = StreamingVadSegmenter(sample_rate=16000, chunk_size=4)

    from preprocess.types import AudioData

    seg.process(AudioData(samples=np.zeros(4, dtype=np.float32), sample_rate=16000))
    assert calls["count"] == 1


def test_vad_segmenter_emits_segment_on_end(monkeypatch):
    iterator_calls: list[np.ndarray] = []
    decisions = [
        {},
        {"start": 10},
        {"end": 20},
    ]

    def fake_vad_iterator(_model):
        return lambda chunk: decisions.pop(0)

    monkeypatch.setattr("preprocess.steps.vad_streamer.VADIterator", fake_vad_iterator)

    class DummyIterator:
        def __call__(self, data):
            return decisions.pop(0)

    monkeypatch.setattr("preprocess.steps.vad_streamer.VADIterator", lambda *args, **kwargs: DummyIterator())

    seg = StreamingVadSegmenter(sample_rate=16000, chunk_size=4, model=object())
    from preprocess.types import AudioData

    first = seg.process(AudioData(samples=np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32), sample_rate=16000))
    assert first is None

    second = seg.process(AudioData(samples=np.array([0.2, 0.3, 0.4, 0.5], dtype=np.float32), sample_rate=16000))
    assert second is None

    third = seg.process(AudioData(samples=np.array([1.0, 1.1, 1.2, 1.3], dtype=np.float32), sample_rate=16000))
    assert third is not None
    assert third.accepted is True
    assert (third.samples == np.array([0.1, 0.2, 0.3, 0.4, 0.2, 0.3, 0.4, 0.5, 1.0, 1.1, 1.2, 1.3], dtype=np.float32)).all()
    assert (third.noise_reference == np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)).all()
