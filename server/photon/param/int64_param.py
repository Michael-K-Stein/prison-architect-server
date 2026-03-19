from io import BytesIO
from struct import pack, unpack

from server.photon.param.int8_param import IntParameterBase


class Int64Parameter(IntParameterBase):
    @classmethod
    def from_stream(cls, stream: BytesIO):
        return cls(unpack(">q", stream.read(8))[0])

    def serialize(self) -> bytes:
        return pack(">q", self.value)
