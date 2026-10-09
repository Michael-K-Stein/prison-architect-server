from typing import cast

from server.photon.command_code import CommandCode
from server.photon.enum_lookups import CommandParams
from server.photon.operation_code import OperationCode
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.operation_payload import PhotonPacketPayload
from server.photon.param.int8_param import Int8Parameter
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.parameter_key import ParameterKey
from server.photon.queue.photon_client_socket import PhotonClientSocket


def raised_event_to_event_packet(
    from_player: PhotonClientSocket | int,
    raised_event: PhotonOperationPacket,
) -> PhotonOperationPacket:
    sender_num = (
        from_player.get_in_game_user_num()
        if isinstance(from_player, PhotonClientSocket)
        else from_player
    )

    operation_code = cast(
        OperationCode,
        cast(Int8Parameter, raised_event.get_payload().params[ParameterKey.Code]).value,
    )

    # Relay only the canonical event payload fields for client compatibility.
    params: CommandParams = {
        ParameterKey.ActorNr: Int32Parameter(sender_num),
        ParameterKey.Data: raised_event.get_payload().params[ParameterKey.Data],
    }

    # Preserve encryption mode from the incoming RaiseEvent payload.
    command = (
        CommandCode.EncryptedEvent
        if raised_event.get_header().is_encrypted()
        else CommandCode.Event
    )

    header = PhotonDataPacketHeader(command)
    event_packet = PhotonOperationPacket(
        header=header,
        payload=PhotonPacketPayload(
            operation_code=operation_code,
            params=params,
            header=header,
        ),
    )
    return event_packet
