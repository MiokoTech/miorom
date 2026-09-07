"""
miorom.helper.relocator
~~~~~~~~~~~~~~~~~~~~~~~
Helper for binary section relocation, buffer splicing, and pointer/size fixups.
Helps repacker scripts expand internal sections without breaking subsequent offsets.
"""

import struct
from typing import List, Optional, Union


class BinaryRelocator:
    """
    Manages binary buffer modification with automatic shift tracking.

    Example:
        reloc = BinaryRelocator(orig_data, endian=">")
        delta = reloc.replace_range(text_start, old_text_size, new_text_bytes)

        # Update affected header pointers/sizes
        reloc.shift_u32(0x04, delta)    # Total file size
        reloc.shift_u32(0x50, delta)    # Section 2 size
        reloc.shift_u32(0x60, delta)    # Section 3 start
        reloc.shift_u32(len(reloc) - 4, delta) # EOF reloc table ptr

        new_data = reloc.to_bytes()
    """

    def __init__(self, data: Union[bytes, bytearray], endian: str = ">"):
        self._buf = bytearray(data)
        self.endian = endian
        self.total_shift = 0

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def buffer(self) -> bytearray:
        return self._buf

    def replace_range(
        self,
        offset: int,
        old_size: int,
        new_data: Union[bytes, bytearray],
        align: Optional[int] = None,
        pad_byte: int = 0,
        dry_run: bool = False,
    ) -> int:
        """
        Replace old_size bytes at offset with new_data.
        Returns the shift delta (len(final_data) - old_size).

        Keyword Args:
            align: If set, pads new_data to a multiple of align before replacing.
            pad_byte: Byte value used for alignment padding (default: 0).
            dry_run: If True, computes the delta without mutating the internal buffer.
        """
        payload = bytearray(new_data)
        if align is not None and align > 1:
            rem = len(payload) % align
            if rem != 0:
                payload.extend(bytes([pad_byte]) * (align - rem))

        delta = len(payload) - old_size
        if not dry_run:
            self._buf[offset:offset + old_size] = payload
            self.total_shift += delta
        return delta

    def read_u32(self, offset: int) -> int:
        return struct.unpack_from(f"{self.endian}I", self._buf, offset)[0]

    def set_u32(self, offset: int, value: int) -> "BinaryRelocator":
        struct.pack_into(f"{self.endian}I", self._buf, offset, value)
        return self

    def shift_u32(self, offset: int, delta: int) -> int:
        """Add delta to the 32-bit integer stored at offset. Returns the new value."""
        cur = self.read_u32(offset)
        new_val = cur + delta
        self.set_u32(offset, new_val)
        return new_val

    def shift_multiple_u32(self, offsets: List[int], delta: int) -> None:
        """Shift multiple 32-bit values at the given offsets."""
        for off in offsets:
            self.shift_u32(off, delta)

    def read_u16(self, offset: int) -> int:
        return struct.unpack_from(f"{self.endian}H", self._buf, offset)[0]

    def set_u16(self, offset: int, value: int) -> "BinaryRelocator":
        struct.pack_into(f"{self.endian}H", self._buf, offset, value)
        return self

    def shift_u16(self, offset: int, delta: int) -> int:
        cur = self.read_u16(offset)
        new_val = cur + delta
        self.set_u16(offset, new_val)
        return new_val

    def align_to(self, boundary: int = 32, pad_byte: int = 0) -> int:
        """Pad buffer until its length is a multiple of boundary. Returns bytes added."""
        remainder = len(self._buf) % boundary
        if remainder != 0:
            pad_len = boundary - remainder
            self._buf.extend(bytes([pad_byte]) * pad_len)
            return pad_len
        return 0

    def to_bytes(self) -> bytes:
        return bytes(self._buf)
