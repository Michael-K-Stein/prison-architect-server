import json
from socket import socket
from typing import Generator, Optional, Tuple, cast

from server.consts import ServerType
from server.models.actor_properties import ActorProperties
from server.photon.command_code import CommandCode
from server.photon.operation_code import OperationCode
from server.photon.packet.base import PhotonDataPacket, PhotonPacket
from server.photon.packet.factory import PacketFactory
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.operation_payload import PhotonPacketPayload
from server.photon.param.nil_param import NilParameter
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.string_param import StringParameter
from server.photon.queue.photon_queue import PhotonQueue


class PhotonClientSocket:
    _sock: socket
    _addr: Tuple[str, int]
    _user_id: Optional[int]
    _aes_key: Optional[bytes]
    _queue: PhotonQueue
    _connected_to_game_id: Optional[str]
    _user_name: Optional[str]
    _custom_proeperties: ActorProperties
    _in_game_user_num: Optional[int]
    _server_type: ServerType
    _app_version: Optional[str]
    _region: Optional[str]

    def __init__(self, sock: socket, addr: Tuple[str, int], server_type: ServerType):
        self._sock = sock
        self._addr = addr
        self._user_id = None
        self._aes_key = None
        self._queue = PhotonQueue(
            sock, str(f"{addr[0]}:{addr[1]}"), server_type=server_type
        ).__enter__()
        self._server_type = server_type
        self._connected_to_game_id = None
        self._user_name = None
        self._custom_proeperties = ActorProperties()
        self._in_game_user_num = None
        self._app_version = None
        self._region = None

    def update_custom_properties(self, custom_properties: ActorProperties):
        self._custom_proeperties.update(custom_properties)

    def get_custom_properties(self) -> ActorProperties:
        return self._custom_proeperties

    def get_aes_key(self) -> bytes | None:
        return self._queue.get_aes_key()

    def set_user_id(self, user_id: int) -> None:
        self._user_id = user_id

    def get_user_id(self) -> int:
        if self._user_id is None:
            raise ValueError("UserId not yet set for client!")
        return self._user_id

    def set_app_version(self, version: str) -> None:
        self._app_version = version

    def set_region(self, region: str) -> None:
        self._region = region

    def get_user_name(self) -> str:
        if self._user_name is None:
            raise ValueError("UserName not yet set for client!")
        return self._user_name

    def set_user_name(self, user_name: str) -> None:
        self._user_name = user_name

    def join_game(self, game_id: str, in_game_num: int) -> None:
        if self._connected_to_game_id is not None:
            raise TypeError("Client is already connected to a game!")
        self._connected_to_game_id = game_id
        self._in_game_user_num = in_game_num

    def leave_game(self) -> None:
        if self._connected_to_game_id is None:
            raise TypeError("Client is not in a game!")
        self._connected_to_game_id = None
        self._in_game_user_num = None

    def get_in_game_user_num(self) -> int:
        if self._in_game_user_num is None:
            raise ValueError("InGameUserNum not yet set for client!")
        return self._in_game_user_num

    def get_game_id(self) -> str:
        if self._connected_to_game_id is None:
            raise ValueError("GameId not yet set for client!")
        return self._connected_to_game_id

    def __hash__(self) -> int:
        return hash(self._sock)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PhotonClientSocket):
            return False
        return hash(self) == hash(other) and self.get_user_id() == other.get_user_id()

    def process(
        self, do_not_handle: Optional[Tuple[OperationCode, ...]] = None
    ) -> Generator[PhotonDataPacket, None, None]:
        incoming_packet = self._queue.pop()
        while incoming_packet is not None:
            packet_for_outer_handling = self._handle_incoming_packet(
                incoming_packet, do_not_handle=do_not_handle
            )
            if packet_for_outer_handling is not None:
                yield packet_for_outer_handling
            incoming_packet = self._queue.pop()

    def _handle_incoming_packet(
        self,
        packet: PhotonDataPacket,
        do_not_handle: Optional[Tuple[OperationCode, ...]] = None,
    ) -> Optional[PhotonDataPacket]:
        if isinstance(packet, PhotonOperationPacket):
            if (
                do_not_handle is not None
                and packet.get_payload().operation_code in do_not_handle
            ):
                return packet
            if packet.get_payload().operation_code == OperationCode.Authenticate:
                return self._handle_auth_request(packet)
        return packet

    def _handle_auth_request(
        self, packet: PhotonOperationPacket
    ) -> Optional[PhotonOperationPacket]:
        if ParameterKey.Token in packet.get_payload().params:
            auth_request_token = cast(
                StringParameter, packet.get_payload().params[ParameterKey.Token]
            )

            PhotonClientSocket.enrich_with_token_data(self, auth_request_token.value)
        else:
            user_id = cast(
                StringParameter, packet.get_payload().params[ParameterKey.UserId]
            )
            self.set_user_id(int(user_id.value))

        self._queue.push(
            PacketFactory.operation(
                CommandCode.OperationResponse, OperationCode.Authenticate, return_code=0
            )
        )

    def send(self, packet: "PhotonPacket") -> None:
        self._queue.push(packet)

    def to_token(self) -> str:
        return json.dumps(
            {
                "user_id": self.get_user_id(),
                "connected_to_game_id": self._connected_to_game_id,
            }
        )

    @classmethod
    def from_token(
        cls, sock: socket, addr: Tuple[str, int], token: str, server_type: ServerType
    ):
        client = cls(sock, addr, server_type)
        PhotonClientSocket.enrich_with_token_data(client, token)
        return client

    @staticmethod
    def enrich_with_token_data(client: "PhotonClientSocket", token: str) -> None:
        token_data = json.loads(token)

        client._connected_to_game_id = token_data.get(
            "connected_to_game_id", client._connected_to_game_id
        )
        client._user_id = token_data.get("user_id", client._user_id)

    def get_address(self) -> str:
        return f"{self._addr[0]}:{self._addr[1]}"
