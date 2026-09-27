"""Synthetic Photon client smoke test for the local Prison Architect server.

Performs a real Photon TCP handshake against the NameServer (127.0.0.1:4533),
then follows the real client flow: Authenticate on the NameServer, take the
token, connect to the MasterServer (127.0.0.1:4530), and authenticate there.

Steps:
  1. TCP connect to NameServer
  2. Init request  -> expect Init response
  3. Diffie-Hellman key exchange -> derive AES session key
  4. Encrypted GetRegions -> expect Region + Address
  5. Encrypted Authenticate (UserId/Region/AppVersion/AppId) -> expect Token
  6. New TCP connection to MasterServer, handshake + token Authenticate
     -> expect an Authenticate response carrying a token

This exercises the server's packet parser, DH encryption, operation routing,
and the Name/Master server handlers end to end. No game client needed.
"""

import socket
import sys

sys.path.insert(0, ".")

from server.consts import PRISON_ARCHITECT_APP_ID
from server.photon.command_code import CommandCode
from server.photon.operation_code import OperationCode
from server.photon.packet.factory import PacketFactory
from server.photon.packet.init import InitRequestPacket
from server.photon.packet.operation_packet import PhotonOperationPacket
from server.photon.packet.packet_stream import PhotonStreamParser
from server.photon.param.parameter_key import ParameterKey
from server.photon.param.string_param import StringParameter
from server.photon.photon_enc import build_dh_request, process_dh_response


class Client:
    def __init__(self, host, port):
        self.parser = PhotonStreamParser()
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(5)
        self.aes = None

    def read_one(self):
        while True:
            chunk = self.sock.recv(0x1000)
            if not chunk:
                raise RuntimeError("Server closed the connection")
            self.parser.feed(chunk)
            for packet in self.parser.parse(
                expect_responses=True, aes_key=self.aes
            ):
                return packet

    def send(self, packet):
        if isinstance(packet, PhotonOperationPacket) and self.aes is not None:
            packet.set_aes_key(self.aes)
        self.sock.sendall(packet.serialize())

    def handshake(self):
        self.send(InitRequestPacket(app_id=PRISON_ARCHITECT_APP_ID))
        resp = self.read_one()
        assert resp.get_header().get_command_name() == "InitResponse", resp.get_header()
        priv, dh_req = build_dh_request()
        self.send(dh_req)
        resp = self.read_one()
        assert (
            resp.get_header().get_command_name() == "KeyExchangeResponse"
        ), resp.get_header()
        self.aes = process_dh_response(priv, resp)
        assert len(self.aes) == 32

    def operation(self, op_code, params):
        self.send(
            PacketFactory.operation(
                CommandCode.EncryptedOperation, op_code, params=params
            )
        )
        resp = self.read_one()
        assert isinstance(resp, PhotonOperationPacket), type(resp)
        assert (
            resp.get_header().get_command_name() == "EncryptedOperationResponse"
        ), resp.get_header()
        return resp.get_payload()

    def close(self):
        self.sock.close()


# --- NameServer: handshake + GetRegions + Authenticate ---
ns = Client("127.0.0.1", 4533)
print("STEP 1: TCP connect to NameServer 127.0.0.1:4533 ... OK")
ns.handshake()
print("STEP 2: Init handshake + DH key exchange ... OK")

payload = ns.operation(
    OperationCode.GetRegions,
    {ParameterKey.ApplicationId: StringParameter(PRISON_ARCHITECT_APP_ID)},
)
region = payload.params[ParameterKey.Region].value[0].value
address = payload.params[ParameterKey.Address].value[0].value
print(f"STEP 3: GetRegions -> region={region!r}, address={address!r} ... OK")

payload = ns.operation(
    OperationCode.Authenticate,
    {
        ParameterKey.UserId: StringParameter("12345"),
        ParameterKey.Region: StringParameter(region),
        ParameterKey.AppVersion: StringParameter("1.0"),
        ParameterKey.ApplicationId: StringParameter(PRISON_ARCHITECT_APP_ID),
    },
)
token = payload.params[ParameterKey.Token].value
ns_addr = payload.params[ParameterKey.Address].value
print(f"STEP 4: Authenticate -> got token ({len(token)} chars), master={ns_addr!r} ... OK")
ns.close()

# --- MasterServer: handshake + token Authenticate ---
ms = Client("127.0.0.1", 4530)
print("STEP 5: TCP connect to MasterServer 127.0.0.1:4530 ... OK")
ms.handshake()
print("STEP 6: Init handshake + DH key exchange ... OK")
payload = ms.operation(
    OperationCode.Authenticate,
    {ParameterKey.Token: StringParameter(token)},
)
new_token = payload.params[ParameterKey.Token].value
print(f"STEP 7: Token authenticate -> accepted, new token ({len(new_token)} chars) ... OK")
ms.close()

print("ALL STEPS PASSED - server handled the full client flow without errors")
