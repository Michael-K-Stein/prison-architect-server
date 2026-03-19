from io import BytesIO
from struct import pack, unpack

from server.photon.param.base import ParameterBase


class Float32Parameter(ParameterBase[float]):
    @classmethod
    def from_stream(cls, stream: BytesIO):
        return cls(unpack(">f", stream.read(4))[0])

    def serialize(self) -> bytes:
        return pack(">f", self.value)
