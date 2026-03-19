from io import BytesIO
from struct import pack, unpack
from typing import Any

from server.photon.param.base import ArrayParameterBase, ParameterBase
from server.photon.param.read_param import get_type_for_instance, read_parameter


class ObjectSliceParameter(ArrayParameterBase[ParameterBase[Any]]):
    """Untyped array (each element has its own type prefix)."""

    @classmethod
    def from_stream(cls, stream: BytesIO):
        length = unpack(">h", stream.read(2))[0]
        elements = [read_parameter(stream) for _ in range(length)]
        return cls(elements)

    def serialize(self) -> bytes:
        payload = pack(">h", len(self.value))
        for element in self.value:
            payload += pack(">B", get_type_for_instance(element))
            payload += element.serialize()
        return payload
