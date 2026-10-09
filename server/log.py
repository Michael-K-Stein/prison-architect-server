from enum import IntEnum
import logging
import pprint
from collections.abc import Callable
from typing import Any, Dict, Optional, Union

from rich.console import Console
from rich.text import Text

from server.consts import ServerType
from server.photon.packet.base import PhotonDataPacket
from server.proxy_servers.proxy_queue_type import ProxyQueueType
from server.settings import Settings


class Verbosity(IntEnum):
    Debug = 0
    Info = 1
    Warning = 2
    Error = 3
    Critical = 4


# markup/highlight off: messages contain "[...]" and raw packet data that must
# print verbatim. Styling is applied explicitly via Text instead.
console = Console(markup=False, highlight=False, emoji=False, soft_wrap=True)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

SENDER_COLORS: Dict[ServerType | ProxyQueueType, str] = {
    ServerType.NameServer: "magenta",
    ServerType.MasterServer: "cyan",
    ServerType.GameServer: "white",
}


def _print_for_sender(
    sender: Union[ServerType, str, ProxyQueueType], msg: Any, *args: Any, **kwargs: Any
) -> None:
    sender_name = (
        sender.value.upper()
        if isinstance(
            sender,
            (
                ServerType,
                ProxyQueueType,
            ),
        )
        else sender.upper()
    )
    line = Text.assemble(
        f"[{sender_name}] \t",
        msg if isinstance(msg, Text) else str(msg),
        "\t",
        "\t".join(str(x) for x in args),
        style=SENDER_COLORS.get(sender, ""),
    )
    console.print(line, **kwargs)


def _print_with_prefix(
    prefix: str,
    sender: Union[ServerType, str, ProxyQueueType],
    msg: Any,
    *args: Any,
    **kwargs: Any,
) -> None:
    _print_for_sender(
        sender,
        Text.assemble(
            (f"[{prefix}]", "bold"), " ", msg if isinstance(msg, Text) else str(msg)
        ),
        *args,
        **kwargs,
    )


def print_critical(
    sender: ServerType | ProxyQueueType, msg: Any, *args: Any, **kwargs: Any
) -> None:
    if Settings().get_verbosity() <= Verbosity.Critical:
        _print_with_prefix("*", sender, msg, *args, **kwargs)


def print_debug(
    sender: Union[ServerType, str, ProxyQueueType], msg: Any, *args: Any, **kwargs: Any
) -> None:
    if Settings().get_verbosity() <= Verbosity.Debug:
        _print_with_prefix("~", sender, msg, *args, **kwargs)


def print_info(
    sender: ServerType | ProxyQueueType, msg: Any, *args: Any, **kwargs: Any
) -> None:
    if Settings().get_verbosity() <= Verbosity.Info:
        _print_with_prefix("i", sender, msg, *args, **kwargs)


def print_success(
    sender: ServerType | ProxyQueueType, msg: Any, *args: Any, **kwargs: Any
) -> None:
    if Settings().get_verbosity() <= Verbosity.Info:
        _print_with_prefix("+", sender, msg, *args, **kwargs)


def print_error(
    sender: ServerType | ProxyQueueType, msg: Any, *args: Any, **kwargs: Any
) -> None:
    if Settings().get_verbosity() <= Verbosity.Error:
        _print_with_prefix("!", sender, msg, *args, **kwargs)


def print_warning(
    sender: ServerType | ProxyQueueType, msg: Any, *args: Any, **kwargs: Any
) -> None:
    if Settings().get_verbosity() <= Verbosity.Warning:
        _print_with_prefix("?", sender, msg, *args, **kwargs)


def pprint_clean(val: Any) -> str:
    formatted = pprint.pformat(val, compact=True).replace(chr(0xA), "")
    return formatted[:200] + ("..." if len(formatted) > 200 else "")


def print_packet_log(
    server_type: ServerType | ProxyQueueType,
    packet: PhotonDataPacket,
    printer: Optional[Callable[[ServerType | ProxyQueueType, str], None]] = None,
) -> None:
    print_func = printer if printer is not None else print_debug
    print_func(
        server_type,
        f"Packet {hash(packet)}",
    )
    for line in packet.log():
        print_func(server_type, f"    {line}")
