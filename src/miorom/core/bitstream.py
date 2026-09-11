from typing import Union, BinaryIO
from io import BytesIO


class BitReader:
    """
    Arbitrary bitstream reader supporting MSB-first and LSB-first bit ordering.
    Enables reading arbitrary bit counts across byte boundaries for compression,
    packed dialogs, audio streams, and planar graphics.
    """

    def __init__(self, data: Union[bytes, bytearray, memoryview], bit_order: str = "msb"):
        self.buffer = bytes(data)
        self.bit_order = bit_order.lower()
        if self.bit_order not in ("msb", "lsb"):
            raise ValueError(f"Unsupported bit order '{bit_order}'. Expected 'msb' or 'lsb'.")

        self.byte_pos = 0
        self.bit_offset = 0

    @property
    def total_bits(self) -> int:
        return len(self.buffer) * 8

    @property
    def bits_read(self) -> int:
        return self.byte_pos * 8 + self.bit_offset

    @property
    def bits_remaining(self) -> int:
        return max(0, self.total_bits - self.bits_read)

    @property
    def is_eof(self) -> bool:
        return self.bits_remaining == 0

    def read_bit(self) -> int:
        """Reads a single bit (0 or 1)."""
        if self.byte_pos >= len(self.buffer):
            raise EOFError(f"Attempted to read bit past end of stream (byte {self.byte_pos})")

        b = self.buffer[self.byte_pos]
        if self.bit_order == "msb":
            bit = (b >> (7 - self.bit_offset)) & 1
        else:
            bit = (b >> self.bit_offset) & 1

        self.bit_offset += 1
        if self.bit_offset == 8:
            self.bit_offset = 0
            self.byte_pos += 1

        return bit

    def read_bits(self, count: int) -> int:
        """
        Reads unsigned integer of arbitrary bit count (1 to 64 bits).
        Returns 0 when count is 0.
        """
        if count < 0:
            raise ValueError(f"Bit count cannot be negative: {count}")
        if count == 0:
            return 0
        if count > self.bits_remaining:
            raise EOFError(f"Requested {count} bits, but only {self.bits_remaining} remain.")

        val = 0
        if self.bit_order == "msb":
            for _ in range(count):
                val = (val << 1) | self.read_bit()
        else:
            for i in range(count):
                val |= (self.read_bit() << i)

        return val

    def read_signed_bits(self, count: int) -> int:
        """Reads signed integer of bit count using two's complement."""
        if count <= 0:
            raise ValueError(f"Bit count must be positive for signed read: {count}")
        val = self.read_bits(count)
        sign_bit = 1 << (count - 1)
        if val & sign_bit:
            val -= (1 << count)
        return val

    def peek_bits(self, count: int) -> int:
        """Inspects count bits without advancing the stream position."""
        saved_byte = self.byte_pos
        saved_bit = self.bit_offset
        try:
            return self.read_bits(count)
        finally:
            self.byte_pos = saved_byte
            self.bit_offset = saved_bit

    def skip_bits(self, count: int) -> None:
        """Skips count bits forward in the stream."""
        if count < 0:
            raise ValueError(f"Cannot skip negative bits: {count}")
        if count > self.bits_remaining:
            raise EOFError(f"Cannot skip {count} bits, only {self.bits_remaining} remain.")

        total = self.bit_offset + count
        self.byte_pos += total // 8
        self.bit_offset = total % 8

    def align_byte(self) -> None:
        """Discards unread bits in the current byte to align to the next byte boundary."""
        if self.bit_offset > 0:
            self.bit_offset = 0
            self.byte_pos += 1

    def read_bytes(self, num_bytes: int) -> bytes:
        """Reads aligned bytes from the stream after aligning to byte boundary."""
        self.align_byte()
        if self.byte_pos + num_bytes > len(self.buffer):
            raise EOFError(f"Requested {num_bytes} bytes, got {len(self.buffer) - self.byte_pos}")
        data = self.buffer[self.byte_pos : self.byte_pos + num_bytes]
        self.byte_pos += num_bytes
        return data


class BitWriter:
    """
    Arbitrary bitstream writer supporting MSB-first and LSB-first bit ordering.
    Accumulates bits across byte boundaries and serializes to byte sequences.
    """

    def __init__(self, bit_order: str = "msb"):
        self.bit_order = bit_order.lower()
        if self.bit_order not in ("msb", "lsb"):
            raise ValueError(f"Unsupported bit order '{bit_order}'. Expected 'msb' or 'lsb'.")

        self.bytes = bytearray()
        self.current_byte = 0
        self.bit_offset = 0

    @property
    def bits_written(self) -> int:
        return len(self.bytes) * 8 + self.bit_offset

    @property
    def bytes_written(self) -> int:
        return len(self.bytes) + (1 if self.bit_offset > 0 else 0)

    def write_bit(self, bit: int) -> None:
        """Writes a single bit (0 or 1)."""
        bit = 1 if bit else 0

        if self.bit_order == "msb":
            self.current_byte |= (bit << (7 - self.bit_offset))
        else:
            self.current_byte |= (bit << self.bit_offset)

        self.bit_offset += 1
        if self.bit_offset == 8:
            self.bytes.append(self.current_byte)
            self.current_byte = 0
            self.bit_offset = 0

    def write_bits(self, value: int, count: int) -> None:
        """
        Writes count bits of value to the stream.
        Masks value to count bits.
        """
        if count < 0:
            raise ValueError(f"Bit count cannot be negative: {count}")
        if count == 0:
            return

        if self.bit_order == "msb":
            for i in range(count - 1, -1, -1):
                self.write_bit((value >> i) & 1)
        else:
            for i in range(count):
                self.write_bit((value >> i) & 1)

    def write_signed_bits(self, value: int, count: int) -> None:
        """Writes signed integer using two's complement masking."""
        if count <= 0:
            raise ValueError(f"Bit count must be positive for signed write: {count}")
        mask = (1 << count) - 1
        self.write_bits(value & mask, count)

    def align_byte(self, fill_bit: int = 0) -> None:
        """Pads the current byte to boundary with fill_bit (0 or 1)."""
        fill = 1 if fill_bit else 0
        while self.bit_offset > 0:
            self.write_bit(fill)

    def write_bytes(self, data: bytes) -> None:
        """Aligns to byte boundary and writes raw bytes."""
        self.align_byte()
        self.bytes.extend(data)

    def to_bytes(self, pad_to_byte: bool = True, fill_bit: int = 0) -> bytes:
        """Returns the serialized bytes, optionally padding incomplete final byte."""
        if pad_to_byte and self.bit_offset > 0:
            self.align_byte(fill_bit=fill_bit)
        return bytes(self.bytes)
