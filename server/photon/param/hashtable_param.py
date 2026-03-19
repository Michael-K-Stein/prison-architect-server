from io import BytesIO
from struct import pack, unpack
from typing import Any, Dict, TypeVar, cast

from server.photon.param.base import ParameterBase
from server.photon.param.dictionary_param_base import DictionaryParameterBase
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.int8_param import Int8Parameter
from server.photon.param.read_param import get_type_for_instance, read_parameter
from server.photon.param.string_param import StringParameter

K = TypeVar("K", bound=ParameterBase[Any])
V = TypeVar("V", bound=ParameterBase[Any])


class HashtableParameter(DictionaryParameterBase[K, V]):
    """Untyped dictionary ('h'). Every key/val has a type prefix."""

    @classmethod
    def from_stream(cls, stream: BytesIO) -> "HashtableParameter[Any, Any]":
        length = unpack(">h", stream.read(2))[0]

        # Explicitly declare the dictionary with ParameterBase[Any]
        result: Dict[ParameterBase[Any], ParameterBase[Any]] = {}
        for _ in range(length):
            key = read_parameter(stream)
            val = read_parameter(stream)

            # Runtime type validation to catch stream corruption
            if not isinstance(key, ParameterBase):
                raise TypeError(
                    f"Expected key to be ParameterBase, got {type(key).__name__}"
                )
            if not isinstance(val, ParameterBase):
                raise TypeError(
                    f"Expected value to be ParameterBase, got {type(val).__name__}"
                )

            result[key] = val

        return cls(cast(Any, result))

    def serialize(self) -> bytes:
        payload = bytearray(pack(">h", len(self.value)))

        for key, val in self.value.items():
            payload.append(get_type_for_instance(key))
            payload.extend(key.serialize())

            payload.append(get_type_for_instance(val))
            payload.extend(val.serialize())

        return bytes(payload)


def foo():
    my_hashtable = HashtableParameter(
        {
            Int8Parameter(4): StringParameter("Bar"),
            Int32Parameter(4): StringParameter("Conflict"),
        }
    )
    assert StringParameter("Bar") == my_hashtable[Int8Parameter(4)]
    assert StringParameter("Conflict") == my_hashtable[Int32Parameter(4)]
