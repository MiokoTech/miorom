"""
miorom.patch.patch_writer
~~~~~~~~~~~~~~~~~~~~~~~~~
Fluent Binary Patch Writer & Precision Emitter Primitive.
Provides chainable methods for applying in-memory patches, struct writes,
and assembly NOPs with automatic cursor and modification tracking.

Transactional usage (v0.13+):
    rom = bytearray(open("arm9.bin", "rb").read())

    with PatchWriter(rom) as w:          # commits only on clean exit
        w.seek_to(0x14000).write_str("Translated text")
        w.write_u32_at(...)              # any exception rolls the buffer back

    with PatchWriter(rom, staged=True) as w:
        ...                              # journal mode: nothing touches the
                                         # buffer until commit; w.journal()
                                         # exposes pending writes pre-commit.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class PatchRecord(MioRomResult):
    """Record of a single contiguous write in the buffer."""
    offset: int
    data: bytes


class PatchWriter:
    """
    Fluent binary patch builder and IPS generator.

    Immediate mode (default): every write mutates the backing buffer at once.
    When used as a context manager, a snapshot is taken on __enter__ and
    restored on any exception (rollback), so a partially applied patch never
    escapes the ``with`` block.

    Staged mode (``staged=True``): writes accumulate in an internal journal
    and the buffer stays untouched until the context exits cleanly.
    """

    def __init__(
        self,
        buffer: bytearray,
        base_address: int = 0,
        endian: str = "<",
        staged: bool = False,
    ):
        self.buffer = buffer
        self.base_address = base_address
        self.default_endian = endian
        self._cursor: int = 0
        self._records: List[PatchRecord] = []
        self._staged = staged
        self._snapshot: Optional[bytearray] = None
        self._in_context = False

    # ------------------------------------------------------------------
    # Transaction support
    # ------------------------------------------------------------------

    def __enter__(self) -> "PatchWriter":
        self._snapshot = bytearray(self.buffer)
        self._in_context = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self._snapshot = None
            self._in_context = False
        return False  # never swallow exceptions

    def commit(self) -> "PatchWriter":
        """Apply staged journal writes to the buffer (staged mode)."""
        if self._staged:
            for rec in self._records:
                end = rec.offset + len(rec.data)
                self._ensure_capacity(end)
                self.buffer[rec.offset : end] = rec.data
            self._staged = False
        return self

    def rollback(self) -> "PatchWriter":
        """
        Discard pending writes.

        Staged mode: clears the journal; buffer was never touched.
        Immediate mode inside a context: restores the __enter__ snapshot.
        """
        if self._staged:
            self._records.clear()
        elif self._snapshot is not None:
            self.buffer[:] = self._snapshot
        return self

    def journal(self) -> List[Dict[str, Any]]:
        """
        Returns the pending write journal as plain dicts:
        ``{"offset": int, "data": bytes, "size": int}``.
        """
        return [
            {"offset": r.offset, "data": r.data, "size": len(r.data)}
            for r in self._records
        ]

    # ------------------------------------------------------------------
    # Cursor control
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Write primitives
    # ------------------------------------------------------------------

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
        if not self._staged:
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

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

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
