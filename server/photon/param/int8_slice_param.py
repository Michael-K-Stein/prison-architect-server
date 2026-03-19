from io import BytesIO
from struct import pack, unpack

from server.photon.param.base import ParameterBase


class Int8SliceParameter(ParameterBase[bytes]):
    """Represents a raw Byte Array."""

    @classmethod
    def from_stream(cls, stream: BytesIO):
        length = unpack(">i", stream.read(4))[0]
        return cls(stream.read(length))

    def serialize(self) -> bytes:
        return pack(">i", len(self.value)) + self.value
