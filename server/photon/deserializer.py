import struct
from io import BytesIO
from typing import TYPE_CHECKING, Dict, Tuple, cast

from server.photon.command_code import CommandCode
from server.photon.operation_code import OperationCode
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.read_param import read_parameter

if TYPE_CHECKING:
    from typing import Any

    from server.photon.packet.header import PhotonDataPacketHeader
    from server.photon.param.base import ParameterBase


def deserialize_photon_payload(
    header: "PhotonDataPacketHeader",
    data: bytes,
) -> Tuple[
    "OperationCode",
    Dict["ParameterKey", "ParameterBase[Any]"],
    Tuple[int, "ParameterBase[Any]"] | None,
]:
    stream = BytesIO(data)

    is_response = header.command in (
        CommandCode.OperationResponse,
        CommandCode.KeyExchangeResponse,
        CommandCode.EncryptedOperationResponse,
        CommandCode.DisconnectMessage,
    )
    skip_operation_code = header.command == CommandCode.DisconnectMessage

    operation_code = OperationCode.DiffieHellmanRequest
    if not skip_operation_code:
        operation_code = cast(OperationCode, struct.unpack(">B", stream.read(1))[0])

    response_debug_data = None
    if is_response:
        return_code = struct.unpack(">h", stream.read(2))[0]

        debug_message_param = read_parameter(stream)

        response_debug_data = (return_code, debug_message_param)

        # debug_message = ""
        # if (
        #     debug_message_param
        #     and hasattr(debug_message_param, "value")
        #     and debug_message_param.value
        # ):
        #     debug_message = debug_message_param.value

        # # if return_code != 0:
        # #     print_error(
        # #         f"Photon Server Error {return_code}{(': ' + debug_message) if debug_message else ''}"
        # #     )

    param_count = struct.unpack(">h", stream.read(2))[0]

    params: Dict[ParameterKey, ParameterBase[Any]] = {}
    for _ in range(param_count):
        key_bytes = stream.read(1)
        if not key_bytes:
            break
        param_key = cast(ParameterKey, struct.unpack(">B", key_bytes)[0])

        params[param_key] = read_parameter(stream)

    return operation_code, params, response_debug_data
