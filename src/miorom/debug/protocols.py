"""Structural interfaces for emulator clients without mandatory inheritance."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmulatorClientProtocol(Protocol):
    """A structural read/write emulator memory client."""

    def read_bytes(self, address: int, size: int) -> bytes:
        ...

    def write_bytes(self, address: int, data: bytes) -> None:
        ...

