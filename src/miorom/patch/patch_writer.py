"""
miorom.patch.patch_writer
~~~~~~~~~~~~~~~~~~~~~~~~~
Fluent Binary Patch Writer & Precision Emitter Primitive.
Provides chainable methods for applying in-memory patches, struct writes,
and assembly NOPs with automatic cursor and modification tracking.
"""

from dataclasses import dataclass, field
import struct
from typing import List, Optional, Tuple, Union


@dataclass
class PatchRecord:
    """Record of a single contiguous write in the buffer."""
    offset: int
    data: bytes


class PatchWriter:
    """
    Fluent binary patch builder and IPS generator.
    """

    def __init__(
        self,
        buffer: bytearray,
        base_address: int = 0,
        endian: str = "<",
    ):
        self.buffer = buffer
        self.base_address = base_address
        self.default_endian = endian
        self._cursor: int = 0
        self._records: List[PatchRecord] = []

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def records(self) -> List[PatchRecord]:
        return list(self._records)

    def seek_to(self, offset: int) -> "PatchWriter":
        """Moves cursor to specified offset."""
        self._cursor = max(0, offset)
        return self

    def skip(self, count: int) -> "PatchWriter":
        """Advances cursor forward by count bytes."""
        self._cursor += count
        return self

    def align_to(self, alignment: int, pad_byte: int = 0) -> "PatchWriter":
        """Aligns cursor up to the specified boundary, filling gap with pad_byte."""
        if alignment <= 1:
            return self
        rem = self._cursor % alignment
        if rem != 0:
            pad_len = alignment - rem
            self.write_bytes(bytes([pad_byte] * pad_len))
        return self

    def _ensure_capacity(self, needed_size: int) -> None:
        """Grows buffer if write exceeds current length."""
        if needed_size > len(self.buffer):
            self.buffer.extend(b"\x00" * (needed_size - len(self.buffer)))

    def write_bytes(self, data: Union[bytes, bytearray]) -> "PatchWriter":
        """Writes raw bytes at current cursor and advances cursor."""
        b = bytes(data)
        if not b:
            return self
        end = self._cursor + len(b)
        self._ensure_capacity(end)
        self.buffer[self._cursor : end] = b
        self._records.append(PatchRecord(offset=self._cursor, data=b))
        self._cursor = end
        return self

    def write_u8(self, val: int) -> "PatchWriter":
        return self.write_bytes(bytes([val & 0xFF]))

    def write_u16(self, val: int, endian: Optional[str] = None) -> "PatchWriter":
        fmt = f"{endian or self.default_endian}H"
        return self.write_bytes(struct.pack(fmt, val & 0xFFFF))

    def write_u32(self, val: int, endian: Optional[str] = None) -> "PatchWriter":
        fmt = f"{endian or self.default_endian}I"
        return self.write_bytes(struct.pack(fmt, val & 0xFFFFFFFF))

    def write_i32(self, val: int, endian: Optional[str] = None) -> "PatchWriter":
        fmt = f"{endian or self.default_endian}i"
        return self.write_bytes(struct.pack(fmt, val))

    def write_str(
        self,
        text: str,
        encoding: str = "utf-8",
        null_terminated: bool = True,
    ) -> "PatchWriter":
        """Encodes and writes string at cursor."""
        payload = text.encode(encoding)
        if null_terminated:
            term = b"\x00\x00" if "16" in encoding.lower() else b"\x00"
            payload += term
        return self.write_bytes(payload)

    def write_arm_nop(self, count: int = 1, endian: Optional[str] = None) -> "PatchWriter":
        """Writes ARM MOV r0, r0 (0xE1A00000) instructions."""
        end = endian or self.default_endian
        fmt = f"{end}I"
        nop_bytes = struct.pack(fmt, 0xE1A00000) * count
        return self.write_bytes(nop_bytes)

    def write_mips_nop(self, count: int = 1) -> "PatchWriter":
        """Writes MIPS NOP (0x00000000) instructions."""
        return self.write_bytes(b"\x00\x00\x00\x00" * count)

    def generate_ips(self) -> bytes:
        """
        Compiles all tracked patch records into standard IPS binary patch format.
        """
        out = bytearray(b"PATCH")
        for rec in self._records:
            off = rec.offset
            sz = len(rec.data)
            # IPS record format: 3-byte offset (BE), 2-byte size (BE), payload
            out.extend(bytes([(off >> 16) & 0xFF, (off >> 8) & 0xFF, off & 0xFF]))
            out.extend(struct.pack(">H", sz))
            out.extend(rec.data)
        out.extend(b"EOF")
        return bytes(out)

    def to_bytes(self) -> bytes:
        return bytes(self.buffer)
