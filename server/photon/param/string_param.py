from io import BytesIO
from struct import pack, unpack

from server.photon.param.base import ParameterBase


class StringParameter(ParameterBase[str]):
    def __init__(self, value: str):
        if not isinstance(value, str):  # type: ignore
            raise TypeError("Value of StringParameter must be a string!")
        super().__init__(value)

    @classmethod
    def from_stream(cls, stream: BytesIO):
        length = unpack(">h", stream.read(2))[0]
        if length == 0:
            return cls("")
        return cls(stream.read(length).decode("utf-8"))

    def serialize(self) -> bytes:
        encoded = self.value.encode("utf-8")
        return pack(">h", len(encoded)) + encoded
