"""
miorom.core.vlq
~~~~~~~~~~~~~~~
Variable-Length Quantity (VLQ) & LEB128 Integer Codec Primitive.
Encodes and decodes multi-byte compressed integers used across game engines
(e.g., MIDI-style 7-bit continuation VLQ, unsigned/signed LEB128).
"""

from typing import Tuple

from miorom.errors import ParseError


class VariableLengthIntCodec:
    """
    Pure modular codec for variable-length integers (VLQ and LEB128).
    """

    @classmethod
    def encode_vlq(cls, value: int) -> bytes:
        """
        Encodes an integer into standard Big-Endian 7-bit continuation VLQ (MIDI format).
        Bit 7 is 1 for continuation bytes, and 0 for the last byte.
        """
        if value < 0:
            raise ParseError("Standard VLQ requires non-negative integers")
        if value == 0:
            return bytes([0])

        buf = bytearray()
        buf.append(value & 0x7F)
        value >>= 7

        while value > 0:
            buf.append((value & 0x7F) | 0x80)
            value >>= 7

        buf.reverse()
        return bytes(buf)

    @classmethod
    def decode_vlq(cls, data: bytes, offset: int = 0) -> Tuple[int, int]:
        """
        Decodes a Big-Endian 7-bit continuation VLQ from data at offset.
        Returns (value, bytes_consumed).
        """
        val = 0
        consumed = 0
        cur = offset

        while cur < len(data):
            b = data[cur]
            consumed += 1
            cur += 1
            val = (val << 7) | (b & 0x7F)
            if (b & 0x80) == 0:
                break

        return val, consumed

    @classmethod
    def encode_leb128(cls, value: int, signed: bool = False) -> bytes:
        """
        Encodes an integer into Little-Endian LEB128 (unsigned or two's-complement signed).
        """
        buf = bytearray()
        if not signed:
            if value < 0:
                raise ParseError("Unsigned LEB128 requires non-negative value")
            while True:
                byte = value & 0x7F
                value >>= 7
                if value != 0:
                    byte |= 0x80
                buf.append(byte)
                if value == 0:
                    break
        else:
            more = True
            while more:
                byte = value & 0x7F
                value >>= 7
                # Sign bit of current byte is bit 6 (0x40)
                if (value == 0 and (byte & 0x40) == 0) or (value == -1 and (byte & 0x40) != 0):
                    more = False
                else:
                    byte |= 0x80
                buf.append(byte)

        return bytes(buf)

    @classmethod
    def decode_leb128(cls, data: bytes, offset: int = 0, signed: bool = False) -> Tuple[int, int]:
        """
        Decodes Little-Endian LEB128 from data at offset.
        Returns (value, bytes_consumed).
        """
        result = 0
        shift = 0
        consumed = 0
        cur = offset

        while cur < len(data):
            byte = data[cur]
            cur += 1
            consumed += 1
            result |= (byte & 0x7F) << shift
            shift += 7
            if (byte & 0x80) == 0:
                if signed and (byte & 0x40) != 0:
                    result |= -(1 << shift)
                break

        return result, consumed

    @classmethod
    def encode_sqlite_varint(cls, value: int) -> bytes:
        """
        Encodes a 64-bit integer into SQLite 1-9 byte variable-length integer format.
        Bytes 1-8 store 7 bits with continuation flag 0x80; the 9th byte stores 8 bits.
        """
        if value < 0:
            raise ParseError("SQLite varint requires non-negative 64-bit integer")
        if value <= 0x7F:
            return bytes([value])

        buf = bytearray()
        if value >= (1 << 56):
            buf.append(value & 0xFF)
            value >>= 8
            for _ in range(8):
                buf.append((value & 0x7F) | 0x80)
                value >>= 7
        else:
            while value > 0:
                buf.append((value & 0x7F) | (0x80 if len(buf) > 0 else 0))
                value >>= 7
            for i in range(1, len(buf)):
                buf[i] |= 0x80

        buf.reverse()
        return bytes(buf)

    @classmethod
    def decode_sqlite_varint(cls, data: bytes, offset: int = 0) -> Tuple[int, int]:
        """
        Decodes SQLite 1-9 byte variable-length integer from data at offset.
        Returns (value, bytes_consumed).
        """
        val = 0
        cur = offset
        for i in range(8):
            if cur >= len(data):
                raise ParseError("Unexpected EOF while reading SQLite varint")
            b = data[cur]
            cur += 1
            val = (val << 7) | (b & 0x7F)
            if (b & 0x80) == 0:
                return val, cur - offset

        if cur >= len(data):
            raise ParseError("Unexpected EOF while reading 9th byte of SQLite varint")
        b = data[cur]
        cur += 1
        val = (val << 8) | b
        return val, cur - offset

    @staticmethod
    def zigzag_encode(n: int) -> int:
        """Maps signed integer to unsigned integer using ZigZag encoding."""
        return (n << 1) ^ (n >> 63) if n < 0 else (n << 1)

    @staticmethod
    def zigzag_decode(n: int) -> int:
        """Maps unsigned integer back to signed integer using ZigZag decoding."""
        return (n >> 1) ^ (-(n & 1))

    @classmethod
    def encode_ups_varint(cls, value: int) -> bytes:
        """
        Encodes an integer into UPS variable-length integer format.
        """
        if value < 0:
            raise ParseError("UPS varint requires non-negative integers")
        out = bytearray()
        val = value
        while True:
            b = val & 0x7F
            val >>= 7
            if val == 0:
                out.append(b | 0x80)
                break
            out.append(b)
            val -= 1
        return bytes(out)

    @classmethod
    def decode_ups_varint(cls, data: bytes, offset: int = 0) -> Tuple[int, int]:
        """
        Decodes UPS variable-length integer from data at offset.
        Returns (value, bytes_consumed).
        """
        val = 0
        shift = 0
        cur = offset
        while cur < len(data):
            b = data[cur]
            cur += 1
            val += (b & 0x7F) << shift
            if b & 0x80:
                return val, cur - offset
            shift += 7
            val += 1 << shift
        raise ParseError("Unexpected EOF reading UPS varint")


def encode_vlq(value: int) -> bytes:
    return VariableLengthIntCodec.encode_vlq(value)


def decode_vlq(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return VariableLengthIntCodec.decode_vlq(data, offset)


def encode_uleb128(value: int) -> bytes:
    return VariableLengthIntCodec.encode_leb128(value, signed=False)


def decode_uleb128(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return VariableLengthIntCodec.decode_leb128(data, offset, signed=False)


def encode_sleb128(value: int) -> bytes:
    return VariableLengthIntCodec.encode_leb128(value, signed=True)


def decode_sleb128(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return VariableLengthIntCodec.decode_leb128(data, offset, signed=True)


def encode_ups_varint(value: int) -> bytes:
    return VariableLengthIntCodec.encode_ups_varint(value)


def decode_ups_varint(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return VariableLengthIntCodec.decode_ups_varint(data, offset)
