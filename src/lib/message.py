from enum import Enum
from lib.constants import (
    LENGTH_FILTER,
    MAX_ACK,
    MAX_LENGTH,
    MIN_ACK,
    PAYLOAD_START,
    TYPE_DEC_SHIFT,
    TYPE_ENC_SHIFT,
)


class MessageType(Enum):
    UPLOAD: int = 0
    DOWNLOAD: int = 1
    OK: int = 2
    ERROR: int = 3
    FIN: int = 4
    ACK: int = 5


class Message:
    def __init__(self, type: MessageType, pos: int, payload: bytes = bytes()):
        if pos < MIN_ACK or MAX_ACK < pos:
            raise ValueError(
                f"Message pos number ({pos}) is not within 0 to 4294967295 range"
            )

        if len(payload) > MAX_LENGTH:
            raise ValueError(
                f"Message payload size ({len(payload)}) is greater than its maximum ({MAX_LENGTH})"
            )

        self.type = type
        self.pos = pos
        self.length = len(payload)
        self.payload = payload

    @classmethod
    def decode(cls, message_bytes: bytes):
        type = int.from_bytes(message_bytes[:1], "big") >> TYPE_DEC_SHIFT
        length = int.from_bytes(message_bytes[:2], "big") & LENGTH_FILTER
        pos = int.from_bytes(message_bytes[2:6], "big")

        payload_end = PAYLOAD_START + length
        payload = message_bytes[PAYLOAD_START:payload_end]

        return cls(MessageType(type), pos, payload)

    def encode(self) -> bytes:
        type_plus_length = (self.type.value << TYPE_ENC_SHIFT) | self.length

        message_bytes = type_plus_length.to_bytes(2, "big")
        message_bytes += self.pos.to_bytes(4, "big")
        message_bytes += self.payload

        return message_bytes

    def __gt__(self, other):
        return self.pos > other.pos

    def __repr__(self):
        return f"{self.type}. \n\tlen={self.length} \n\tpos={self.pos}"
