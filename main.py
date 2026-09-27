from argparse import ArgumentParser

from server.consts import NAMESERVER_IP, NAMESERVER_PORT, ServerType
from server import run_local_server
from server.log import Verbosity
from server.settings import Settings


def _add_common_arguments(p):
    """Options shared by every subcommand.

    Registered on both the top-level parser and each subcommand, so they are
    accepted before *and* after the subcommand name (e.g. both
    `main.py -l 0.0.0.0 local` and the README's `main.py local -l 0.0.0.0` work).
    """
    p.add_argument(
        "-v",
        "--verbose",
        # Accept lowercase; main() capitalizes before the Verbosity lookup.
        choices=[name.lower() for name in Verbosity._member_names_],
        default="info",
        required=False,
    )
    p.add_argument(
        "-l",
        "--listen",
        type=str,
        default="0.0.0.0",
        help="IP address to bind to",
        required=False,
    )
    p.add_argument(
        "-i",
        "--ip",
        type=str,
        help="IP to redirect to. This should either be 127.0.0.1 or your public IP.",
        default="127.0.0.1",
        required=False,
    )
    p.add_argument(
        "--timeout",
        type=int,
        help="Grace period between client keep alives before closing sockets.",
        default=60,
        required=False,
    )
    p.add_argument(
        "-r",
        "--region",
        type=str,
        default="local",
        required=False,
        help='The name shown in the "Region" selection box.',
    )


if __name__ == "__main__":
    parser = ArgumentParser()
    _add_common_arguments(parser)

    subparsers = parser.add_subparsers(dest="mode")

    local = subparsers.add_parser("local", help="Run server locally")
    _add_common_arguments(local)
    local.add_argument(
        "--upstream",
        type=str,
        default=None,
        required=False,
        help="Upstream Photon name server (host or host:port) that "
        "non-Prison Architect clients are transparently proxied to. "
        "If omitted, the current IP of ns.exitgames.com is resolved "
        "automatically.",
    )

    proxy = subparsers.add_parser(
        "proxy", help="Proxy traffic, allowing reading and injecting packets"
    )
    _add_common_arguments(proxy)
    proxy.add_argument("-p", "--port", default=NAMESERVER_PORT, type=int)
    proxy.add_argument("-u", "--upstream", default=NAMESERVER_IP)
    proxy.add_argument("-t", "--type", choices=ServerType._member_names_, required=True)

    args = parser.parse_args()

    Settings().set(
        listen_host=args.listen,
        verbosity=Verbosity[args.verbose.capitalize()],
        ip=args.ip,
        timeout=args.timeout,
        region_name=args.region,
        # Only the `local` subparser defines --upstream; the `proxy` mode has
        # its own unrelated -u/--upstream flag and is currently a no-op anyway.
        upstream=getattr(args, "upstream", None) if args.mode != "proxy" else None,
    )

    if args.mode == "proxy":
        # run_proxy(args.upstream, args.port, ServerType[args.type])
        pass
    else:  # default
        run_local_server()
