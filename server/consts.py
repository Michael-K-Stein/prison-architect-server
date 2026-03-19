from enum import Enum

MSG_MAGIC = 0xF3
FIRST_SERVER_TO_CLIENT_PACKET = b"\xfb\x00\x00\x00\x0a\x00\x01\xf3\x01\x00"
NAMESERVER_IP = "216.120.180.54"
NAMESERVER_PORT = 4533

OAKLEY_PRIME_768_HEX = "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A63A3620FFFFFFFFFFFFFFFF"
OAKLEY_PRIME_768 = int(OAKLEY_PRIME_768_HEX, 16)
DH_GENERATOR = 22
PRISON_ARCHITECT_APP_ID = "6f869876-bfbc-491e-8fff-4210c966f145"


class ServerType(Enum):
    NameServer = "NameServer"
    MasterServer = "MasterServer"
    GameServer = "GameServer"

    ProxyServer = "ProxyServer"
    UpstreamProxyServer = "UpstreamProxyServer"
    DownstreamProxyServer = "DownstreamProxyServer"


def check_app_id(app_id: str) -> None:
    if app_id != PRISON_ARCHITECT_APP_ID:
        raise ValueError(
            f"Server only support Prison Architect, not the app by id {app_id}"
        )
