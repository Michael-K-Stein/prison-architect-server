from typing import Any, Dict, Iterator, Optional, Tuple, TypeVar

from server.photon.param.base import ParameterBase

K = TypeVar("K", bound=ParameterBase[Any])
V = TypeVar("V", bound=ParameterBase[Any])


class DictionaryParameterBase(ParameterBase[Dict[K, V]]):
    value: Dict[K, V]

    def __init__(self, initial_dict: Optional[Dict[K, V]] = None):
        self.value = initial_dict if initial_dict is not None else {}

    def __getitem__(self, key: K) -> V:
        if not isinstance(key, ParameterBase):
            raise TypeError("Key must be derived from ParameterBase!")
        return self.value[key]

    def __setitem__(self, key: K, value: V) -> None:
        if not isinstance(key, ParameterBase):
            raise TypeError("Key must be derived from ParameterBase!")
        if not isinstance(value, ParameterBase):
            raise TypeError("Value must be derived from ParameterBase!")
        self.value[key] = value

    def __delitem__(self, key: K) -> None:
        if not isinstance(key, ParameterBase):
            raise TypeError("Key must be derived from ParameterBase!")
        del self.value[key]

    def __contains__(self, key: Any) -> bool:
        return key in self.value

    def __len__(self) -> int:
        return len(self.value)

    def __iter__(self) -> Iterator[K]:
        return iter(self.value)

    def keys(self) -> Iterator[K]:
        return iter(self.value.keys())

    def values(self) -> Iterator[V]:
        return iter(self.value.values())

    def items(self) -> Iterator[Tuple[K, V]]:
        return iter(self.value.items())

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        if not isinstance(key, ParameterBase):
            raise TypeError("Key must be derived from ParameterBase!")
        return self.value.get(key, default)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.value})"
