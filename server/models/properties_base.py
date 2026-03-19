from abc import ABC
from typing import Any, Generic, Optional, TypeVar, Union, cast

from server.photon.param.hashtable_param import HashtableParameter

T = TypeVar("T", bound=HashtableParameter[Any, Any])


class PropertiesBase(ABC, Generic[T]):
    """Base Facade class for wrapping Photon Hashtables."""

    raw: T

    def __init__(self, hashtable: Optional[T] = None):
        self.raw = (
            hashtable if hashtable is not None else cast(Any, HashtableParameter({}))
        )

    def to_hashtable(self) -> T:
        return self.raw

    def update(self, other: "Union[PropertiesBase[T],T]") -> None:
        """Merges another properties facade into this one."""
        hashtable: Optional[T] = None

        if isinstance(other, PropertiesBase):
            hashtable = other.raw
        elif isinstance(other, HashtableParameter):
            hashtable = other

        if hashtable is None:  # pyright: ignore[reportUnnecessaryComparison]
            raise TypeError(
                f"Expected a PropertiesBase facade or HashtableParameter, got {type(other).__name__}"
            )

        self.raw.value.update(hashtable.value)
