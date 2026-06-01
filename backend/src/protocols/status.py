"""Status and code values for the real-time ASR protocol."""

from enum import Enum, IntEnum


class ProtocolStatus(IntEnum):
    """HTTP-like numeric status codes used by protocol messages."""

    OK = 200
    BAD_REQUEST = 400
    FORBIDDEN = 403
    NOT_ACCEPTABLE = 406
    INTERNAL_ERROR = 500
    BAD_GATEWAY = 502


class ProtocolCode(str, Enum):
    """Machine-readable protocol result and error codes."""

    OK = "OK"
    BAD_REQUEST = "BAD_REQUEST"
    INVALID_STATE = "INVALID_STATE"
    INVALID_SEQUENCE = "INVALID_SEQUENCE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    PAYLOAD_SIZE_MISMATCH = "PAYLOAD_SIZE_MISMATCH"
    FORBIDDEN = "FORBIDDEN"
    NOT_ACCEPTABLE = "NOT_ACCEPTABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    BAD_GATEWAY = "BAD_GATEWAY"
    SESSION_CLOSED = "SESSION_CLOSED"
