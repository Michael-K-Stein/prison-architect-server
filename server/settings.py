from typing import Any, Literal, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from server.log import Verbosity


class Settings:
    _instance: Optional["Settings"] = None

    def __new__(cls, *args: Any, **kwargs: Any):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set(
        self,
        verbosity: "Verbosity",
        listen_host: Union[Literal["0.0.0.0"], Literal["127.0.0.1"], str],
        ip: Union[Literal["127.0.0.1"], str],
        timeout: int,
        region_name: str,
    ):
        self._verbosity = verbosity
        self._listen_host = listen_host
        self._ip = ip
        self._timeout = timeout
        self._region_name = region_name

    def get_verbosity(self) -> "Verbosity":
        return self._verbosity

    def get_listen_host(self) -> str:
        return self._listen_host

    def get_ip(self) -> str:
        return self._ip

    def get_timeout(self) -> int:
        return self._timeout

    def get_region_name(self) -> str:
        return self._region_name
