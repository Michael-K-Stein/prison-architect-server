from io import BytesIO
from struct import pack, unpack
from typing import Any, Union

from server.photon.param.base import ParameterBase


class IntParameterBase(ParameterBase[int]):
    """Base class for all integer-based Photon parameters."""

    def __int__(self) -> int:
        return self.value

    def __index__(self) -> int:
        """Allows the parameter to be used safely directly as a list/array index."""
        return self.value

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, ParameterBase):
            # If comparing to another Photon parameter, the types MUST match exactly
            return type(self) is type(other) and self.value == other.value  # type: ignore

        if isinstance(other, int):
            # If comparing to a raw Python integer, just compare the value
            return self.value == other

        return False

    def __add__(self, other: Union["IntParameterBase", int]) -> int:
        return self.value + int(other)

    def __sub__(self, other: Union["IntParameterBase", int]) -> int:
        return self.value - int(other)

    def __lt__(self, other: Union["IntParameterBase", int]) -> bool:
        return self.value < int(other)

    def __gt__(self, other: Union["IntParameterBase", int]) -> bool:
        return self.value > int(other)

    def __le__(self, other: Union["IntParameterBase", int]) -> bool:
        return self.value <= int(other)

    def __ge__(self, other: Union["IntParameterBase", int]) -> bool:
        return self.value >= int(other)

    def __hash__(self) -> int:
        # Hash both the class type and the value to prevent cross-type collisions
        return hash((type(self), self.value))


class Int8Parameter(IntParameterBase):
    @classmethod
    def from_stream(cls, stream: BytesIO):
        return cls(unpack(">B", stream.read(1))[0])

    def serialize(self) -> bytes:
        return pack(">B", self.value)
