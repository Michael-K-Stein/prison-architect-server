from io import BytesIO
from struct import pack, unpack

from server.photon.param.base import ParameterBase


class DoubleParameter(ParameterBase[float]):
    @classmethod
    def from_stream(cls, stream: BytesIO):
        return cls(unpack(">d", stream.read(8))[0])

    def serialize(self) -> bytes:
        return pack(">d", self.value)
