"""Ingress validation before audio preprocessing and transcription."""

from dataclasses import dataclass
from uuid import uuid4

from configs.yaml_loader import BackendConfig
from protocols.messages import ActivateMessage, AudioChunkHeader, ErrorMessage
from protocols.status import ProtocolCode, ProtocolStatus


@dataclass(frozen=True)
class ProtocolSession:
    """Server-owned protocol session state."""

    client_id: str
    session_id: str
    stream_id: str
    codec: str
    sample_rate: int
    channels: int
    chunk_duration_ms: int
    expected_chunk_seq: int = 0


@dataclass(frozen=True)
class IngressError:
    """Validation error returned before audio preprocessing."""

    status: ProtocolStatus
    code: ProtocolCode
    message: str

    def to_message(
        self,
        header: AudioChunkHeader | None = None,
    ) -> ErrorMessage:
        return ErrorMessage(
            status=self.status,
            code=self.code,
            message=self.message,
            client_id=header.client_id if header else None,
            session_id=header.session_id if header else None,
            stream_id=header.stream_id if header else None,
        )


@dataclass(frozen=True)
class ActivationResult:
    """Activation result containing either a session or an error."""

    value: ProtocolSession | None = None
    error: IngressError | None = None


class IngressValidator:
    """Validate activation, sequence, timestamp, duration, and payload size."""

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self.sessions: dict[str, ProtocolSession] = {}

    def activate(self, message: ActivateMessage) -> ActivationResult:
        expected = {
            "codec": self.config.audio_codec,
            "sample_rate": self.config.audio_sample_rate,
            "channels": self.config.audio_channels,
            "chunk_duration_ms": self.config.chunk_duration_ms,
        }
        actual = {
            "codec": message.audio_format.codec,
            "sample_rate": message.audio_format.sample_rate,
            "channels": message.audio_format.channels,
            "chunk_duration_ms": message.chunk_duration_ms,
        }
        if actual != expected:
            return ActivationResult(
                error=IngressError(
                    ProtocolStatus.NOT_ACCEPTABLE,
                    ProtocolCode.NOT_ACCEPTABLE,
                    "audio contract mismatch: "
                    f"expected {expected}, got {actual}",
                )
            )

        session = ProtocolSession(
            client_id=message.client_id,
            session_id=f"sess_{uuid4().hex}",
            stream_id=message.stream_id,
            codec=message.audio_format.codec,
            sample_rate=message.audio_format.sample_rate,
            channels=message.audio_format.channels,
            chunk_duration_ms=message.chunk_duration_ms,
        )
        self.sessions[session.session_id] = session
        return ActivationResult(value=session)

    def validate_header(self, header: AudioChunkHeader) -> IngressError | None:
        session = self.sessions.get(header.session_id)
        if session is None:
            return IngressError(
                ProtocolStatus.BAD_REQUEST,
                ProtocolCode.INVALID_STATE,
                "audio_chunk received before activate",
            )
        if (
            session.client_id != header.client_id
            or session.stream_id != header.stream_id
        ):
            return IngressError(
                ProtocolStatus.FORBIDDEN,
                ProtocolCode.FORBIDDEN,
                "audio_chunk does not match the active session owner",
            )
        if header.chunk_seq != session.expected_chunk_seq:
            return IngressError(
                ProtocolStatus.BAD_REQUEST,
                ProtocolCode.INVALID_SEQUENCE,
                "expected chunk_seq "
                f"{session.expected_chunk_seq}, got {header.chunk_seq}",
            )
        expected_timestamp_ms = header.chunk_seq * session.chunk_duration_ms
        if header.timestamp_ms != expected_timestamp_ms:
            return IngressError(
                ProtocolStatus.BAD_REQUEST,
                ProtocolCode.INVALID_TIMESTAMP,
                "expected timestamp_ms "
                f"{expected_timestamp_ms}, got {header.timestamp_ms}",
            )
        if header.duration_ms != session.chunk_duration_ms:
            return IngressError(
                ProtocolStatus.BAD_REQUEST,
                ProtocolCode.BAD_REQUEST,
                "expected duration_ms "
                f"{session.chunk_duration_ms}, got {header.duration_ms}",
            )

        self.sessions[session.session_id] = ProtocolSession(
            client_id=session.client_id,
            session_id=session.session_id,
            stream_id=session.stream_id,
            codec=session.codec,
            sample_rate=session.sample_rate,
            channels=session.channels,
            chunk_duration_ms=session.chunk_duration_ms,
            expected_chunk_seq=session.expected_chunk_seq + 1,
        )
        return None

    def validate_payload(
        self,
        header: AudioChunkHeader,
        payload: bytes,
    ) -> IngressError | None:
        session = self.sessions.get(header.session_id)
        if session is None:
            return IngressError(
                ProtocolStatus.BAD_REQUEST,
                ProtocolCode.INVALID_STATE,
                "payload received before activate",
            )
        expected_size = int(
            session.sample_rate
            * session.channels
            * header.duration_ms
            / 1000
            * 2
        )
        if len(payload) != header.chunk_size:
            return IngressError(
                ProtocolStatus.BAD_REQUEST,
                ProtocolCode.PAYLOAD_SIZE_MISMATCH,
                "expected "
                f"{header.chunk_size} payload bytes, got {len(payload)}",
            )
        if header.chunk_size != expected_size:
            return IngressError(
                ProtocolStatus.BAD_REQUEST,
                ProtocolCode.PAYLOAD_SIZE_MISMATCH,
                "expected pcm_s16le chunk_size "
                f"{expected_size}, got {header.chunk_size}",
            )
        return None
