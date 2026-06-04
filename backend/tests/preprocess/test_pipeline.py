from __future__ import annotations

import pytest
from unittest.mock import patch

import numpy as np

import preprocess
from preprocess.pipeline import PreprocessPipeline
from preprocess.steps import DCRemover


class BadStep:
    pass


def test_pipeline_rejects_step_without_process():
    with pytest.raises(TypeError, match="missing callable process"):
        PreprocessPipeline(steps=[BadStep()])


class UnknownStep:
    def process(self, data):
        return data


def test_pipeline_rejects_unregistered_step():
    with pytest.raises(TypeError, match="unregistered"):
        PreprocessPipeline(steps=[UnknownStep()])


class LabelStep:
    def __init__(self, name):
        self.name = name

    def process(self, data):
        data.metadata.setdefault("labels", []).append(self.name)
        return data


def test_pipeline_executes_steps_in_provided_order(monkeypatch):
    class FirstStep: 
        def __init__(self, name):
            self.name = name
            self._name = None

        def process(self, data):
            data.metadata.setdefault("labels", []).append(self._name or self.name)
            return data

    class SecondStep(FirstStep):
        pass

    monkeypatch.setattr(preprocess.pipeline, "is_registered", lambda _step: True)

    steps = [FirstStep("first"), SecondStep("second")]
    pipeline = PreprocessPipeline(steps=steps)

    data = preprocess.types.AudioData(samples=np.zeros(2, dtype=np.float32), sample_rate=16)
    output = pipeline.process(data)
    assert output is not None
    assert output.metadata["labels"] == ["first", "second"]


def test_pipeline_rejects_duplicates_without_registry():
    with pytest.raises(ValueError, match="Duplicate preprocess step"):
        PreprocessPipeline(steps=[DCRemover(), DCRemover()])


def test_default_pipeline_is_empty_when_steps_not_provided():
    pipeline = PreprocessPipeline(steps=None)
    assert pipeline.steps == []
    assert pipeline.default_step_names == []


def test_validate_segment_rejects_short_segments():
    class Noop:
        def process(self, data):
            return data

    with patch.object(preprocess.pipeline, "is_registered", lambda _step: True):
        pipeline = PreprocessPipeline(steps=[Noop()])

    data = preprocess.types.AudioData(
        samples=np.zeros(100, dtype=np.float32),
        sample_rate=16000,
    )
    result = pipeline.validate_segment(data)

    assert result.accepted is False
    assert result.reason == "too_short"


def test_validate_segment_rejects_too_quiet_segments(monkeypatch):
    class Noop:
        def process(self, data):
            return data

    monkeypatch.setattr(preprocess.pipeline, "is_registered", lambda _step: True)
    pipeline = PreprocessPipeline(steps=[Noop()])

    # A long but near-silent segment should fail loudness gate.
    data = preprocess.types.AudioData(
        samples=np.full(10000, 1e-8, dtype=np.float32),
        sample_rate=16000,
    )
    result = pipeline.validate_segment(data)

    assert result.accepted is False
    assert result.reason == "too_quiet"
