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
