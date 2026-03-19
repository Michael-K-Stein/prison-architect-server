from enum import Enum
from typing import Optional, Tuple, cast

from server.consts import ServerType, check_app_id
from server.local_servers.server_base import ServerBase
from server.photon.command_code import CommandCode
from server.photon.operation_code import OperationCode
from server.photon.packet.factory import PacketFactory
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.slice_param import SliceParameter
from server.photon.param.string_param import StringParameter
from server.photon.queue.photon_client_socket import PhotonClientSocket
from server.settings import Settings


class InstanceState(Enum):
    Disconnected = 0
    AwaitingInit = 1
    AwaitingKeyExchange = 2
    AwaitingRegionListRequest = 3
    AwaitingAuthenticationRequest = 4
    Complete = 5


class NameServer(ServerBase):
    def __init__(self):
        super().__init__(Settings().get_listen_host(), 4533)

    def __enter__(self):
        super().__enter__()
        return self

    def process(self, do_not_handle: Optional[Tuple[OperationCode, ...]] = None):
        for client, packet in super().process(
            do_not_handle=(
                *(do_not_handle if do_not_handle is not None else []),
                OperationCode.Authenticate,
            )
        ):
            if (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.GetRegions
            ):
                self._handle_get_regions_request(client, packet)
                continue
            elif (
                isinstance(packet, PhotonOperationPacket)
                and packet.get_payload().operation_code == OperationCode.Authenticate
            ):
                self._handle_authenticate_request(client, packet)
                continue
            yield client, packet

    def _handle_get_regions_request(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ) -> None:
        app_id = cast(  # TODO: Maybe we can support multiple app ids...?
            StringParameter, packet.get_payload().params.get(ParameterKey.ApplicationId)
        )
        check_app_id(app_id.value)
        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.GetRegions,
                params={
                    ParameterKey.Region: SliceParameter(
                        [
                            StringParameter(Settings().get_region_name()),
                        ]
                    ),
                    ParameterKey.Address: SliceParameter(
                        [
                            StringParameter(f"{Settings().get_ip()}:4530"),
                        ]
                    ),
                },
                return_code=0,
            )
        )

    def _handle_authenticate_request(
        self, client: PhotonClientSocket, packet: PhotonOperationPacket
    ) -> None:
        region = cast(
            StringParameter, packet.get_payload().params.get(ParameterKey.Region)
        )
        app_version = cast(
            StringParameter, packet.get_payload().params.get(ParameterKey.AppVersion)
        )
        app_id = cast(
            StringParameter, packet.get_payload().params.get(ParameterKey.ApplicationId)
        )
        check_app_id(app_id.value)
        user_id = cast(
            StringParameter, packet.get_payload().params.get(ParameterKey.UserId)
        )
        client.set_user_id(int(user_id.value))
        client.set_region(region.value)
        client.set_app_version(app_version.value)

        client.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperationResponse,
                OperationCode.Authenticate,
                params={
                    ParameterKey.Cluster: StringParameter("default"),
                    ParameterKey.Address: StringParameter(Settings().get_ip()),
                    ParameterKey.UserId: user_id,
                    ParameterKey.Token: StringParameter(client.to_token()),
                },
                return_code=0,
            )
        )

    @classmethod
    def get_type(cls) -> ServerType:
        return ServerType.NameServer
