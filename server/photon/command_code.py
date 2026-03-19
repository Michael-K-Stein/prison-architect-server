from enum import IntEnum


class CommandCode(IntEnum):
    Init = 0
    InitResponse = 1

    Operation = 2
    OperationResponse = 3

    Event = 4
    DisconnectMessage = 5

    KeyExchangeRequest = 6
    KeyExchangeResponse = 7

    Message = 8
    RawMessage = 9

    EncryptedOperation = 0x82
    EncryptedOperationResponse = 0x83

    EncryptedEvent = 0x84

    Unknown = 0xFF


def is_encrypted(command_code: CommandCode) -> bool:
    return command_code.value > 0x80
