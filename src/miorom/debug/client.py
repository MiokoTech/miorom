"""
miorom.debug.client
~~~~~~~~~~~~~~~~~~~
Dynamic analysis and live memory bridge for game emulators (Dolphin, GDB Remote Protocol).
Allows ROM hackers to read and write RAM values, inspect strings live during gameplay,
and test translations in real-time without recompiling the ISO.
"""

import os
import socket
import struct
from abc import ABC, abstractmethod
from typing import Optional


class EmulatorClient(ABC):
    """Abstract interface for communicating with a running emulator."""

    @abstractmethod
    def read_bytes(self, address: int, size: int) -> bytes:
        pass

    @abstractmethod
    def write_bytes(self, address: int, data: bytes) -> None:
        pass

    def read_u32(self, address: int, endian: str = ">") -> int:
        data = self.read_bytes(address, 4)
        return struct.unpack(f"{endian}I", data)[0]

    def write_u32(self, address: int, value: int, endian: str = ">") -> None:
        self.write_bytes(address, struct.pack(f"{endian}I", value))

    def read_string(self, address: int, encoding: str = "utf-16-be", max_bytes: int = 512) -> str:
        data = self.read_bytes(address, max_bytes)
        term = b"\x00\x00" if "utf-16" in encoding.lower() else b"\x00"
        idx = data.find(term)
        valid_bytes = data[:idx] if idx != -1 else data
        return valid_bytes.decode(encoding, errors="replace")

    def write_string(self, address: int, text: str, encoding: str = "utf-16-be") -> None:
        term = b"\x00\x00" if "utf-16" in encoding.lower() else b"\x00"
        payload = text.encode(encoding, errors="replace") + term
        self.write_bytes(address, payload)


class DolphinMemoryMock(EmulatorClient):
    """In-memory virtual RAM mock for Dolphin GameCube/Wii MEM1 (24MB)."""

    MEM1_BASE = 0x80000000
    MEM1_SIZE = 24 * 1024 * 1024  # 24MB

    def __init__(self):
        self.ram = bytearray(self.MEM1_SIZE)

    def _to_physical(self, address: int) -> int:
        if 0x80000000 <= address < 0x80000000 + self.MEM1_SIZE:
            return address - self.MEM1_BASE
        raise ValueError(f"Address 0x{address:08X} out of Dolphin MEM1 bounds.")

    def read_bytes(self, address: int, size: int) -> bytes:
        phys = self._to_physical(address)
        return bytes(self.ram[phys:phys + size])

    def write_bytes(self, address: int, data: bytes) -> None:
        phys = self._to_physical(address)
        self.ram[phys:phys + len(data)] = data


class DolphinClient(EmulatorClient):
    """
    Client for Dolphin Emulator. Connects via IPC shared memory or GDB protocol.
    """

    DEFAULT_SHM_PATH = "/dev/shm/dolphin-emu"

    def __init__(self, shm_path: Optional[str] = None):
        self.shm_path = shm_path or self.DEFAULT_SHM_PATH
        self._fallback = DolphinMemoryMock()

    @property
    def is_connected(self) -> bool:
        return os.path.exists(self.shm_path)

    def read_bytes(self, address: int, size: int) -> bytes:
        if self.is_connected:
            phys = address & 0x01FFFFFF  # 24MB mask
            with open(self.shm_path, "rb") as f:
                f.seek(phys)
                return f.read(size)
        return self._fallback.read_bytes(address, size)

    def write_bytes(self, address: int, data: bytes) -> None:
        if self.is_connected:
            phys = address & 0x01FFFFFF
            with open(self.shm_path, "r+b") as f:
                f.seek(phys)
                f.write(data)
        else:
            self._fallback.write_bytes(address, data)
