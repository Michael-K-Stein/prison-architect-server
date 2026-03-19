import struct
from io import BytesIO
from typing import TYPE_CHECKING, Any, Dict, Tuple

from server.photon.command_code import CommandCode
from server.photon.operation_code import OperationCode
from server.photon.param.read_param import get_type_for_instance

if TYPE_CHECKING:
    from server.photon.packet.header import PhotonDataPacketHeader
    from server.photon.param.base import ParameterBase
    from server.photon.param.parameter_key import ParameterKey


def serialize_photon_payload(
    operation_code: "OperationCode",
    params: Dict["ParameterKey", "ParameterBase[Any]"],
    response_debug_data: Tuple[int, "ParameterBase[Any]"] | None,
    header: "PhotonDataPacketHeader",
) -> bytes:
    """
    Serializes an Operation Code and a dictionary of parameters back into a binary payload.
    """
    stream = BytesIO()

    if operation_code == OperationCode.DiffieHellmanResponse:
        stream.write(b"\x00\x00\x00")

    if header.command != CommandCode.DisconnectMessage:
        stream.write(struct.pack(">B", operation_code))

    if response_debug_data is not None:
        stream.write(struct.pack(">h", response_debug_data[0]))
        response_debug_data_type_code = get_type_for_instance(response_debug_data[1])
        stream.write(struct.pack(">B", response_debug_data_type_code.value))
        stream.write(response_debug_data[1].serialize())

    stream.write(struct.pack(">h", len(params)))

    for param_key, param_obj in params.items():
        stream.write(struct.pack(">B", param_key))

        type_code = get_type_for_instance(param_obj)
        stream.write(struct.pack(">B", type_code.value))

        stream.write(param_obj.serialize())

    return stream.getvalue()
