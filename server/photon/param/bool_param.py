from io import BytesIO
from struct import pack, unpack

from server.photon.param.base import ParameterBase


class BooleanParameter(ParameterBase[bool]):
    @classmethod
    def from_stream(cls, stream: BytesIO):
        val = unpack(">B", stream.read(1))[0]
        return cls(val != 0)

    def serialize(self) -> bytes:
        return pack(">B", 1 if self.value else 0)
