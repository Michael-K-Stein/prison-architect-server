from collections import defaultdict
from enum import Enum
from typing import Any, Dict, Type, TypeVar

from server.photon.command_code import CommandCode
from server.photon.event_code import EventCode
from server.photon.operation_code import OperationCode
from server.photon.param.base import ParameterBase
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.parameter_type import ParameterType
from server.photon.serialization_protocol import SerializationProtocol

E = TypeVar("E", bound=Enum)


def build_value_lookup(enum_cls: Type[E]) -> dict[E, list[str]]:
    lookup: dict[E, list[str]] = defaultdict(list)

    for name, member in enum_cls.__members__.items():
        lookup[int(member.value)].append(name)

    return dict(lookup)


OPERATION_CODE_LOOKUP = build_value_lookup(OperationCode)
EVENT_CODE_LOOKUP = build_value_lookup(EventCode)
PARAMETER_KEY_LOOKUP = build_value_lookup(ParameterKey)
PARAMETER_TYPE_LOOKUP = build_value_lookup(ParameterType)
COMMAND_CODE_LOOKUP = build_value_lookup(CommandCode)
SERIALIZATION_PROTOCOL_LOOKUP = build_value_lookup(SerializationProtocol)

CommandParams = Dict[ParameterKey, ParameterBase[Any]]


XT = TypeVar("XT")


def _get_x_name(lookup_table: Dict[XT, list[str]], v: XT) -> str:
    n = lookup_table.get(v, None)
    if n is None:
        return f"UNKNOWN[{str(v)}]"
    if len(n) == 1:
        return n[0]
    return "/".join(n)


def get_parameter_key_name(key: "ParameterKey") -> str:
    return _get_x_name(PARAMETER_KEY_LOOKUP, key)


def get_parameter_type_name(param_type: "ParameterType") -> str:
    return _get_x_name(PARAMETER_TYPE_LOOKUP, param_type)


def get_operation_name(operation_code: "OperationCode") -> str:
    return _get_x_name(OPERATION_CODE_LOOKUP, operation_code)


def get_event_name(event_code: "EventCode") -> str:
    return _get_x_name(EVENT_CODE_LOOKUP, event_code)


def get_command_name(command_code: "CommandCode") -> str:
    return _get_x_name(COMMAND_CODE_LOOKUP, command_code)


def get_serialization_protocol_name(protocol: "SerializationProtocol") -> str:
    return _get_x_name(SERIALIZATION_PROTOCOL_LOOKUP, protocol)
