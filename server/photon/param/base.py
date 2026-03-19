from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any, Generic, Iterator, List, Optional, Sequence, TypeVar

V = TypeVar("V")


class ParameterBase(ABC, Generic[V]):
    """Base class for all Photon parameters."""

    value: V

    def __init__(self, value: V):
        self.value = value

    @classmethod
    @abstractmethod
    def from_stream(cls, stream: BytesIO) -> "ParameterBase[Any]":
        """Reads from the byte stream and constructs the parameter object."""
        pass

    @abstractmethod
    def serialize(self) -> bytes:
        """Converts the internal value back into a byte payload."""
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({repr(self.value)})"

    def __hash__(self) -> int:
        return hash((type(self), self.value))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, type(self)):
            return False
        return self.value == other.value


T = TypeVar("T", bound=ParameterBase[Any])


class ArrayParameterBase(ParameterBase[List[T]]):
    """Base class for Photon Array/Slice parameters."""

    def __init__(self, value: Optional[Sequence[T]] = None):
        # Default to an empty list if nothing is provided
        super().__init__(list(value) if value is not None else [])

    def __setitem__(self, key: int, value: T) -> None:
        if not isinstance(key, int):
            raise TypeError(f"Key must be an index, got {type(key).__name__}")
        if not isinstance(value, ParameterBase):
            raise TypeError(
                f"Value must be derived from ParameterBase, got {type(value).__name__}"
            )
        self.value[key] = value

    def __getitem__(self, key: int) -> T:
        if not isinstance(key, int):
            raise TypeError(f"Key must be an index, got {type(key).__name__}")
        return self.value[key]

    def __len__(self) -> int:
        return len(self.value)

    def __iter__(self) -> Iterator[T]:
        return iter(self.value)

    def append(self, value: T) -> None:
        if not isinstance(value, ParameterBase):
            raise TypeError(
                f"Value must be derived from ParameterBase, got {type(value).__name__}"
            )
        self.value.append(value)
