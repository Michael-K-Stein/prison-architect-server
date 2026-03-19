import hashlib
import os
from typing import Optional

from server.consts import DH_GENERATOR, OAKLEY_PRIME_768
from server.photon.packet.key_exchange import (
    InitEncryptionRequest,
    InitEncryptionResponse,
)


def compute_public_key(priv_key: bytes | int):
    priv_key = (
        priv_key
        if isinstance(priv_key, int)
        else int.from_bytes(priv_key, byteorder="big")
    )
    pub_key = pow(DH_GENERATOR, priv_key, OAKLEY_PRIME_768)
    return pub_key


def compute_shared_aes_key(pub_key: int | bytes, priv_key: int | bytes):
    pub_key_int = (
        pub_key
        if isinstance(pub_key, int)
        else int.from_bytes(pub_key, byteorder="big")
    )
    priv_key_int = (
        priv_key
        if isinstance(priv_key, int)
        else int.from_bytes(priv_key, byteorder="big")
    )
    shared_secret_int = pow(pub_key_int, priv_key_int, OAKLEY_PRIME_768)
    shared_len = (shared_secret_int.bit_length() + 7) // 8
    shared_secret_bytes = shared_secret_int.to_bytes(shared_len, byteorder="big")
    aes_key = hashlib.sha256(shared_secret_bytes).digest()
    return aes_key


def generate_dh_keys(client_pub_key: bytes):
    client_pub_key_int = int.from_bytes(client_pub_key, byteorder="big")
    server_priv_bytes = os.urandom(20)
    server_priv_int = int.from_bytes(server_priv_bytes, byteorder="big")
    server_pub_int = compute_public_key(server_priv_int)
    aes_key = compute_shared_aes_key(client_pub_key_int, server_priv_int)
    return server_pub_int.to_bytes((server_pub_int.bit_length() + 7) // 8), aes_key


def build_dh_request(priv_key_int: Optional[int] = None):
    if priv_key_int is None:
        priv_key = os.urandom(20)
        priv_key_int = int.from_bytes(priv_key, byteorder="big")
    pub_int = compute_public_key(priv_key_int)
    return priv_key_int, InitEncryptionRequest(
        public_key=pub_int.to_bytes((pub_int.bit_length() + 7) // 8)
    )


def process_dh_response(priv_int: int, response: InitEncryptionResponse):
    real_server_pub = response.get_public_key()
    aes_key = compute_shared_aes_key(real_server_pub, priv_int)
    return aes_key
