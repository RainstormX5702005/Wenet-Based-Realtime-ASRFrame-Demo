"""Protocol for preprocess steps."""

from __future__ import annotations

from typing import Protocol

from preprocess.types import AudioData


class PreprocessStep(Protocol):
    """Protocol used for static checking only."""

    def process(self, data: AudioData):
        ...
