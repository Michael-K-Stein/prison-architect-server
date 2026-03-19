from typing import Any, List, Tuple, cast

import colorama

from server.consts import ServerType
from server.log import pprint_clean, print_critical
from server.models.game_properties import GamePropertiesTable
from server.photon.command_code import CommandCode
from server.photon.enum_lookups import CommandParams, get_parameter_key_name
from server.photon.operation_code import OperationCode
from server.photon.packet.header import PhotonDataPacketHeader
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.operation_payload import PhotonPacketPayload
from server.photon.param.base import ParameterBase
from server.photon.param.bool_param import BooleanParameter
from server.photon.param.dict_param import DictionaryParameter
from server.photon.param.hashtable_param import HashtableParameter
from server.photon.param.int8_param import Int8Parameter
from server.photon.param.int32_param import Int32Parameter
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.parameter_type import ParameterType
from server.photon.param.slice_param import SliceParameter
from server.photon.param.string_param import StringParameter
from server.settings import Settings


def hijack_regions_list(payload: PhotonPacketPayload):
    print_hijacked_payload_params(1, payload, [ParameterKey.Address])
    region_addresses_param = cast(
        SliceParameter[StringParameter], payload.params[ParameterKey.Address]
    )
    regions_addresses = region_addresses_param.value
    # regions_addresses.insert(0, StringParameter("127.0.0.1:4530"))

    region_names = cast(
        SliceParameter[StringParameter], payload.params[ParameterKey.Region]
    ).value
    regions_addresses[0] = StringParameter(f"{Settings().get_ip()}:4530")
    # region_names.insert(0, StringParameter("jp"))
    print_hijacked_payload_params(1, payload, [ParameterKey.Address])


def hijack_game_list(payload: PhotonPacketPayload):
    print_hijacked_payload_params(1, payload, [ParameterKey.Address])
    payload.params[ParameterKey.Address] = StringParameter(
        f"{Settings().get_ip()}:4530"
    )
    print_hijacked_payload_params(1, payload, [ParameterKey.Address])


def print_hijacked_payload_params(
    indentation: int,
    payload: "PhotonPacketPayload",
    hijacked_parameters: List[ParameterKey],
) -> None:
    print_critical(("    " * indentation) + f"Hijacked Params [{len(payload.params)}]:")
    for key, val in payload.params.items():
        key_name = get_parameter_key_name(key)
        if key in hijacked_parameters:
            print_critical(
                ("    " * 1)
                + f"  {key_name}({key}): {colorama.Fore.RED}{pprint_clean(val.value)}{colorama.Fore.RESET}"
            )
            continue
        print_critical(
            ("    " * indentation)
            + f"  {key_name}({key}): {pprint_clean(val.value)}"  # type: ignore
        )


def print_event_game_list_parameters(packet: PhotonOperationPacket):
    game_list = cast(
        DictionaryParameter[
            StringParameter, HashtableParameter[ParameterBase[Any], ParameterBase[Any]]
        ],
        packet.get_payload().params[ParameterKey.GameList],
    )
    print_critical("      Game List")
    for k, v in game_list.value.items():
        game_name = cast(StringParameter, k)
        game_params = cast(HashtableParameter, v)
        entry = GameListEntry.from_hashtable_entry(game_name, game_params)

        print_critical(f"        {entry.name}")
        print_critical(f"          Owner: {entry.owner}")
        print_critical(
            f"          Password: {'Required' if entry.password_required else 'Not Required'}"
        )
        print_critical(f"          Player Count: {entry.player_count}")
        print_critical(f"          Capacity: {entry.player_capacity}")
        print_critical(f"          Unknown(243): {entry.unknown243}")
        print_critical(f"          Unknown(253): {entry.unknown253}")


def hijack_event_join_lobby(packet: PhotonOperationPacket):
    if packet.get_header().get_command_code() != CommandCode.Event:
        return

    if packet.get_payload().operation_code != OperationCode.JoinLobby:
        return

    print_event_game_list_parameters(packet)


def hijack_event_game_list(packet: PhotonOperationPacket):
    if packet.get_header().get_command_code() != CommandCode.Event:
        return

    if packet.get_payload().operation_code != OperationCode.GameList:
        return

    game_list = cast(
        HashtableParameter, packet.get_payload().params[ParameterKey.GameList]
    )

    fake_entry = GameListEntry("MY FAKE GAME", "M", True).to_hashtable_entry()
    game_list[fake_entry[0]] = fake_entry[1]
    print_event_game_list_parameters(packet)


def do_hijacks(packet: Any, server_type: ServerType) -> None:
    if not isinstance(packet, PhotonOperationPacket):
        return

    if packet.get_header().is_response() and server_type == ServerType.NameServer:
        if packet.get_payload().operation_code == OperationCode.GetRegions:
            hijack_regions_list(packet.get_payload())
            return

        if packet.get_payload().operation_code == OperationCode.GameList:
            hijack_game_list(packet.get_payload())
            return

    if server_type in (
        ServerType.NameServer,
        ServerType.MasterServer,
    ):
        hijack_event_join_lobby(packet)
        hijack_event_game_list(packet)
        hijack_encrypted_response_join_game(packet)


def craft_create_game_packet(
    game_name: str, owner: str, broadcast: bool = True
) -> PhotonOperationPacket:
    params: CommandParams = {}
    params[ParameterKey.Broadcast] = BooleanParameter(broadcast)
    params[ParameterKey.DeleteCacheOnLeave] = BooleanParameter(True)
    params[232] = BooleanParameter(True)  # type: ignore Not sure what this parameter is...?
    params[ParameterKey.GroupsForRemove] = BooleanParameter(True)
    params[ParameterKey.GameId] = StringParameter(game_name)
    params[ParameterKey.ActorProperties] = HashtableParameter(
        {Int8Parameter(255): StringParameter(owner)}
    )
    params[ParameterKey.GameProperties] = HashtableParameter(
        {
            Int8Parameter(250): SliceParameter([], ParameterType.StringType),
            Int8Parameter(255): Int8Parameter(4),
        }
    )

    header = PhotonDataPacketHeader(
        command_code=CommandCode.Operation,
    )
    payload = PhotonPacketPayload(OperationCode.CreateGame, params, header=header)

    return PhotonOperationPacket(header, payload)


def hijack_encrypted_response_join_game(packet: PhotonOperationPacket):
    if packet.get_header().get_command_code() != CommandCode.EncryptedOperationResponse:
        return
    if packet.get_payload().operation_code not in (
        OperationCode.CreateGame,
        OperationCode.JoinGame,
    ):
        return

    packet.get_payload().params[ParameterKey.Address] = StringParameter(
        f"{Settings().get_ip()}:4532"
    )

    input("Press any key...")
