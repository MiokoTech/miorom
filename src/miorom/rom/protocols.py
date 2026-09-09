"""Structural interfaces for ROM handlers without mandatory inheritance."""

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class RomHandlerProtocol(Protocol):
    """A structural ROM handler accepted by :class:`RomManager.register`."""

    name: str

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        ...

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        ...

    def repack(self, input_dir: str, **kwargs) -> bytes:
        ...
