from io import BytesIO
from struct import pack, unpack

from server.photon.param.int8_param import IntParameterBase


class Int32Parameter(IntParameterBase):
    @classmethod
    def from_stream(cls, stream: BytesIO):
        return cls(unpack(">i", stream.read(4))[0])

    def serialize(self) -> bytes:
        return pack(">i", self.value)
