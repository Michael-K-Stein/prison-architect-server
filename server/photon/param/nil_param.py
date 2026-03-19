from io import BytesIO
from typing import Any, Optional

from server.photon.param.base import ParameterBase


class NilParameter(ParameterBase[None]):
    def __init__(self, value: Optional[Any] = None):
        super().__init__(None)

    @classmethod
    def from_stream(cls, stream: BytesIO):
        return cls(None)

    def serialize(self) -> bytes:
        return b""
