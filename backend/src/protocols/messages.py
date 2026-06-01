"""Pydantic models for the real-time ASR protocol messages."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from protocols.status import ProtocolCode, ProtocolStatus


Metadata = dict[str, Any]


class ProtocolMessage(BaseModel):
    """Base model shared by all JSON protocol messages."""

    metadata: Metadata = Field(default_factory=dict)


class AudioFormat(BaseModel):
    """Audio format declared during protocol activation."""

    codec: Literal["pcm_s16le"]
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)


class ActivateMessage(ProtocolMessage):
    """Client request to create a new recognition session."""

    type: Literal["activate"] = "activate"
    client_id: str = Field(min_length=1)
    stream_id: str = Field(default="mic", min_length=1)
    audio_format: AudioFormat
    chunk_duration_ms: int = Field(gt=0)


class AckMessage(ProtocolMessage):
    """Server acknowledgement for a successful protocol operation."""

    type: Literal["ack"] = "ack"
    status: Literal[ProtocolStatus.OK] = ProtocolStatus.OK
    code: Literal[ProtocolCode.OK] = ProtocolCode.OK
    message: str
    client_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)


class AudioChunkHeader(ProtocolMessage):
    """Header that must be followed by a binary PCM payload frame."""

    type: Literal["audio_chunk"] = "audio_chunk"
    client_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)
    chunk_seq: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    chunk_size: int = Field(gt=0)


class EndStreamMessage(ProtocolMessage):
    """Client request to manually close the current session."""

    type: Literal["end_stream"] = "end_stream"
    client_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)
    reason: Literal["user_stop"] = "user_stop"


class TranscriptMessage(ProtocolMessage):
    """Server transcription result message."""

    type: Literal["transcript"] = "transcript"
    status: Literal[ProtocolStatus.OK] = ProtocolStatus.OK
    client_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)
    result_id: str = Field(min_length=1)
    text: str
    is_final: bool


class EventMessage(ProtocolMessage):
    """Server lifecycle event message."""

    type: Literal["event"] = "event"
    status: Literal[ProtocolStatus.OK] = ProtocolStatus.OK
    code: Literal[ProtocolCode.SESSION_CLOSED] = ProtocolCode.SESSION_CLOSED
    message: str
    client_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)


class ErrorMessage(ProtocolMessage):
    """Server protocol, validation, or service error message."""

    type: Literal["error"] = "error"
    status: ProtocolStatus
    code: ProtocolCode
    message: str
    client_id: str | None = None
    session_id: str | None = None
    stream_id: str | None = None
