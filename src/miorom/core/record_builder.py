"""
miorom.core.record_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~
Fluent Binary Record Builder & Struct Serializer Primitive.
Constructs binary records with exact byte layouts, fixed-length strings,
and alignment padding without brittle struct.pack format strings.
"""

import struct
from typing import Optional, Union


class RecordBuilder:
    """
    Fluent builder for binary records and structs.
    """

    def __init__(self, endian: str = "<"):
        self.endian = endian
        self._buffer = bytearray()

    @property
    def size(self) -> int:
        """Current length in bytes."""
        return len(self._buffer)

    def u8(self, val: int) -> "RecordBuilder":
        self._buffer.append(val & 0xFF)
        return self

    def i8(self, val: int) -> "RecordBuilder":
        self._buffer.extend(struct.pack("b", val))
        return self

    def u16(self, val: int) -> "RecordBuilder":
        self._buffer.extend(struct.pack(f"{self.endian}H", val & 0xFFFF))
        return self

    def i16(self, val: int) -> "RecordBuilder":
        self._buffer.extend(struct.pack(f"{self.endian}h", val))
        return self

    def u32(self, val: int) -> "RecordBuilder":
        self._buffer.extend(struct.pack(f"{self.endian}I", val & 0xFFFFFFFF))
        return self

    def i32(self, val: int) -> "RecordBuilder":
        self._buffer.extend(struct.pack(f"{self.endian}i", val))
        return self

    def u64(self, val: int) -> "RecordBuilder":
        self._buffer.extend(struct.pack(f"{self.endian}Q", val & 0xFFFFFFFFFFFFFFFF))
        return self

    def f32(self, val: float) -> "RecordBuilder":
        self._buffer.extend(struct.pack(f"{self.endian}f", val))
        return self

    def fixed_str(
        self,
        text: str,
        length: int,
        encoding: str = "utf-8",
        pad_byte: int = 0,
    ) -> "RecordBuilder":
        """
        Encodes string and pads or truncates to exact fixed length.
        """
        encoded = text.encode(encoding)
        if len(encoded) >= length:
            self._buffer.extend(encoded[:length])
        else:
            self._buffer.extend(encoded)
            pad_len = length - len(encoded)
            self._buffer.extend(bytes([pad_byte] * pad_len))
        return self

    def pascal_str(
        self,
        text: str,
        length_size: int = 1,
        encoding: str = "utf-8",
    ) -> "RecordBuilder":
        """
        Writes a Pascal string (length prefix followed by encoded string).
        """
        encoded = text.encode(encoding)
        if length_size == 1:
            self.u8(len(encoded))
        elif length_size == 2:
            self.u16(len(encoded))
        else:
            self.u32(len(encoded))
        self._buffer.extend(encoded)
        return self

    def bytes_field(self, data: Union[bytes, bytearray]) -> "RecordBuilder":
        self._buffer.extend(data)
        return self

    def align(self, alignment: int, pad_byte: int = 0) -> "RecordBuilder":
        """Aligns current record size up to alignment boundary."""
        if alignment <= 1:
            return self
        rem = len(self._buffer) % alignment
        if rem != 0:
            pad_len = alignment - rem
            self._buffer.extend(bytes([pad_byte] * pad_len))
        return self

    def build(self) -> bytes:
        """Returns the compiled record as immutable bytes."""
        return bytes(self._buffer)
