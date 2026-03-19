from io import BytesIO
from struct import pack, unpack
from typing import Any

from server.photon.param.base import ParameterBase


class CustomParameter(ParameterBase[Any]):
    @classmethod
    def from_stream(cls, stream: BytesIO):
        custom_id = unpack(">B", stream.read(1))[0]
        length = unpack(">h", stream.read(2))[0]
        data = stream.read(length)
        return cls({"id": custom_id, "data": data})

    def serialize(self) -> bytes:
        custom_id = self.value["id"]
        data = self.value["data"]
        return pack(">Bh", custom_id, len(data)) + data
