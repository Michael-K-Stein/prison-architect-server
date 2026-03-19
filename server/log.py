from enum import IntEnum
import logging
import pprint
from collections.abc import Callable
from typing import Any, Dict, Optional, Union

import colorama

from server.consts import ServerType
from server.photon.packet.base import PhotonDataPacket
from server.settings import Settings


class Verbosity(IntEnum):
    Debug = 0
    Info = 1
    Warning = 2
    Error = 3
    Critical = 4


colorama.init()

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

SENDER_COLORS: Dict[ServerType, str] = {
    ServerType.NameServer: colorama.Fore.MAGENTA,
    ServerType.MasterServer: colorama.Fore.CYAN,
    ServerType.GameServer: colorama.Fore.WHITE,
}


def _print_for_sender(
    sender: Union[ServerType, str], msg: Any, *args: Any, **kwargs: Any
) -> None:
    full_message = (
        f"[{sender.value.upper() if isinstance(sender, ServerType) else sender.upper()}] \t"
        + msg
        + "\t"
        + "\t".join(str(x) for x in args)
    )
    print(
        f"{SENDER_COLORS[sender] if sender in SENDER_COLORS else ''}{full_message}{colorama.Style.RESET_ALL}",
        **kwargs,
    )


def _print_with_prefix(
    prefix: str, sender: Union[ServerType, str], msg: Any, *args: Any, **kwargs: Any
) -> None:
    _print_for_sender(
        sender,
        f"{colorama.Style.BRIGHT}[{prefix}]{colorama.Style.NORMAL} {msg}",
        *args,
        **kwargs,
    )


def print_critical(sender: ServerType, msg: Any, *args: Any, **kwargs: Any) -> None:
    if Settings().get_verbosity() <= Verbosity.Critical:
        _print_with_prefix("*", sender, msg, *args, **kwargs)


def print_debug(
    sender: Union[ServerType, str], msg: Any, *args: Any, **kwargs: Any
) -> None:
    if Settings().get_verbosity() <= Verbosity.Debug:
        _print_with_prefix("~", sender, msg, *args, **kwargs)


def print_info(sender: ServerType, msg: Any, *args: Any, **kwargs: Any) -> None:
    if Settings().get_verbosity() <= Verbosity.Info:
        _print_with_prefix("i", sender, msg, *args, **kwargs)


def print_success(sender: ServerType, msg: Any, *args: Any, **kwargs: Any) -> None:
    if Settings().get_verbosity() <= Verbosity.Info:
        _print_with_prefix("+", sender, msg, *args, **kwargs)


def print_error(sender: ServerType, msg: Any, *args: Any, **kwargs: Any) -> None:
    if Settings().get_verbosity() <= Verbosity.Error:
        _print_with_prefix("!", sender, msg, *args, **kwargs)


def print_warning(sender: ServerType, msg: Any, *args: Any, **kwargs: Any) -> None:
    if Settings().get_verbosity() <= Verbosity.Warning:
        _print_with_prefix("?", sender, msg, *args, **kwargs)


def pprint_clean(val: Any) -> str:
    formatted = pprint.pformat(val, compact=True).replace(chr(0xA), "")
    return formatted[:200] + ("..." if len(formatted) > 200 else "")


def print_packet_log(
    server_type: ServerType,
    packet: PhotonDataPacket,
    printer: Optional[Callable[[ServerType, str], None]] = None,
) -> None:
    print_func = printer if printer is not None else print_debug
    print_func(
        server_type,
        f"Packet {hash(packet)}",
    )
    for line in packet.log():
        print_func(server_type, f"    {line}")
