from time import sleep

from server.consts import PRISON_ARCHITECT_APP_ID, ServerType
from server.proxy_servers.proxy_tunnel import ProxyTunnel


def run_proxy(upstream_ip: str, port: int, server_type: ServerType):
    with ProxyTunnel(
        local_port=port,
        remote_ip=upstream_ip,
        remote_port=port,
        app_id=PRISON_ARCHITECT_APP_ID,
    ) as tunnel:
        while True:
            tunnel.process()
            sleep(0.1)
