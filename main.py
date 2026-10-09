from argparse import ArgumentParser

from server.consts import NAMESERVER_IP, NAMESERVER_PORT, ServerType
from server import run_local_server
from server.log import Verbosity
from server.proxy_servers.server import run_proxy
from server.settings import Settings


if __name__ == "__main__":
    # 1. Create a parent parser for shared arguments
    # add_help=False is crucial here so it doesn't conflict with the subparsers' own help flags
    shared_parser = ArgumentParser(add_help=False)

    shared_parser.add_argument(
        "-v",
        "--verbose",
        choices=Verbosity._member_names_,
        default="info",
        required=False,
    )
    shared_parser.add_argument(
        "-l",
        "--listen",
        type=str,
        default="0.0.0.0",
        help="IP address to bind to",
        required=False,
    )
    shared_parser.add_argument(
        "-i",
        "--ip",
        type=str,
        help="IP to redirect to. This should either be 127.0.0.1 or your public IP.",
        default="127.0.0.1",
        required=False,
    )
    shared_parser.add_argument(
        "--timeout",
        type=int,
        help="Grace period between client keep alives before closing sockets.",
        default=10,
        required=False,
    )
    shared_parser.add_argument(
        "-r",
        "--region",
        type=str,
        default="local",
        required=False,
        help='The name shown in the "Region" selection box.',
    )

    # 2. Main parser
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode")

    # 3. Add the shared_parser as a parent to the subparsers
    local = subparsers.add_parser(
        "local", help="Run server locally", parents=[shared_parser]
    )

    proxy = subparsers.add_parser(
        "proxy",
        help="Proxy traffic, allowing reading and injecting packets",
        parents=[shared_parser],
    )

    # 4. Add proxy-specific arguments
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
    )

    if args.mode == "proxy":
        run_proxy(args.upstream, args.port, ServerType[args.type])
    else:  # default
        run_local_server()
