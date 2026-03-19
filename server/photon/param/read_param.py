from io import BytesIO
from struct import unpack
from typing import TYPE_CHECKING, Any, Optional

from server.photon.param.parameter_type import ParameterType

if TYPE_CHECKING:
    from server.photon.param.base import ParameterBase


def read_parameter(
    stream: BytesIO, type_code: Optional[int] = None
) -> "ParameterBase[Any]":
    """Factory function to instantiate the correct ParameterBase subclass."""
    from server.photon.param.type_registry import TYPE_REGISTRY

    if type_code is None:
        type_bytes = stream.read(1)
        if not type_bytes:
            raise EOFError("Unexpected end of stream while reading type code.")
        type_code = unpack(">B", type_bytes)[0]

    param_type = ParameterType(type_code)
    param_class = TYPE_REGISTRY[param_type]
    param = param_class.from_stream(stream)
    return param


def get_type_for_instance(instance: "ParameterBase[Any]") -> ParameterType:
    """Utility to map an instance back to its Enum type (needed for serialization)."""
    from server.photon.param.type_registry import TYPE_REGISTRY

    for p_type, p_class in TYPE_REGISTRY.items():
        if isinstance(instance, p_class):
            return p_type
    raise ValueError(f"Unknown parameter class: {type(instance)}")
