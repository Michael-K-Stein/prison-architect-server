from argparse import ArgumentParser

from server.consts import NAMESERVER_IP, NAMESERVER_PORT, ServerType
from server import run_local_server
from server.log import Verbosity
from server.settings import Settings


if __name__ == "__main__":
    parser = ArgumentParser()

    subparsers = parser.add_subparsers(dest="mode")

    subparsers.add_parser("local", help="Run server locally")

    proxy = subparsers.add_parser(
        "proxy", help="Proxy traffic, allowing reading and injecting packets"
    )
    proxy.add_argument("-p", "--port", default=NAMESERVER_PORT, type=int)
    proxy.add_argument("-u", "--upstream", default=NAMESERVER_IP)
    proxy.add_argument("-t", "--type", choices=ServerType._member_names_, required=True)

    parser.add_argument(
        "-v",
        "--verbose",
        choices=Verbosity._member_names_,
        default="info",
        required=False,
    )
    parser.add_argument(
        "-l",
        "--listen",
        type=str,
        default="0.0.0.0",
        help="IP address to bind to",
        required=False,
    )

    parser.add_argument(
        "-i",
        "--ip",
        type=str,
        help="IP to redirect to. This should either be 127.0.0.1 or your public IP.",
        default="127.0.0.1",
        required=False,
    )

    parser.add_argument(
        "--timeout",
        type=int,
        help="Grace period between client keep alives before closing sockets.",
        default=10,
        required=False,
    )

    parser.add_argument(
        "-r",
        "--region",
        type=str,
        default="local",
        required=False,
        help='The name shown in the "Region" selection box.',
    )

    args = parser.parse_args()

    Settings().set(
        listen_host=args.listen,
        verbosity=Verbosity[args.verbose.capitalize()],
        ip=args.ip,
        timeout=args.timeout,
        region_name=args.region,
    )

    if args.mode == "proxy":
        # run_proxy(args.upstream, args.port, ServerType[args.type])
        pass
    else:  # default
        run_local_server()
