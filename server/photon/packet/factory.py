from typing import TYPE_CHECKING, Literal, Optional, cast

from server.photon.command_code import CommandCode
from server.photon.enum_lookups import CommandParams
from server.photon.event_code import EventCode
from server.photon.operation_code import OperationCode
from server.photon.packet.base import PhotonDataPacket
from server.photon.packet.event_packet import PhotonEventPacket
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.operation_payload import PhotonPacketPayload
from server.photon.param.hashtable_param import HashtableParameter
from server.photon.param.nil_param import NilParameter
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.string_param import StringParameter

if TYPE_CHECKING:
    from server.local_servers.games_manager import GamesManager


class PacketFactory:
    @staticmethod
    def data(command_code: CommandCode) -> PhotonDataPacket:
        header = PhotonDataPacketHeader(command_code=command_code)
        return PhotonDataPacket(header)

    @staticmethod
    def operation(
        command: (
            Literal[CommandCode.Event]
            | Literal[CommandCode.EncryptedEvent]
            | Literal[CommandCode.Operation]
            | Literal[CommandCode.OperationResponse]
            | Literal[CommandCode.EncryptedOperation]
            | Literal[CommandCode.EncryptedOperationResponse]
        ),
        operation: OperationCode,
        params: Optional[CommandParams] = None,
        return_code: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> PhotonOperationPacket:
        if params is None:
            params = {}
        response_debug_data = None
        if return_code is not None:
            response_debug_data = (
                return_code,
                (
                    StringParameter(error_message)
                    if error_message is not None
                    else NilParameter()
                ),
            )
        header = PhotonDataPacketHeader(command_code=command)
        return PhotonOperationPacket(
            header=header,
            payload=PhotonPacketPayload(
                operation_code=operation,
                params=params,
                header=header,
                response_debug_data=response_debug_data,
            ),
        )

    @staticmethod
    def event(
        event: EventCode,
        params: Optional[CommandParams] = None,
        return_code: Optional[int] = None,
        error_message: Optional[str] = None,
        encrypted: bool = False,
    ) -> PhotonEventPacket:
        return cast(
            PhotonEventPacket,
            PacketFactory.operation(
                CommandCode.EncryptedEvent if encrypted else CommandCode.Event,
                operation=cast(OperationCode, event),
                params=params,
                return_code=return_code,
                error_message=error_message,
            ),
        )

    @staticmethod
    def encrypted_event(
        event: EventCode,
        params: Optional[CommandParams] = None,
        return_code: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> PhotonEventPacket:
        return PacketFactory.event(
            event=event,
            params=params,
            return_code=return_code,
            error_message=error_message,
            encrypted=True,
        )

    @staticmethod
    def game_list_params(games_manager: "GamesManager") -> CommandParams:
        game_list = HashtableParameter(
            {
                StringParameter(name): data.to_hashtable_entry()[1]
                for name, data in games_manager.get_games().items()
            }
        )
        params: CommandParams = {
            ParameterKey.GameList: game_list,
        }
        return params

    @staticmethod
    def game_list(games_manager: "GamesManager") -> PhotonOperationPacket:

        header = PhotonDataPacketHeader(command_code=CommandCode.Event)
        return PhotonOperationPacket(
            header=header,
            payload=PhotonPacketPayload(
                operation_code=OperationCode.GameList,
                params=PacketFactory.game_list_params(games_manager),
                header=header,
            ),
        )
