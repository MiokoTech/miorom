"""
miorom.compression.saxman
~~~~~~~~~~~~~~~~~~~~~~~~~
Sega Genesis / Mega Drive Saxman compression codec.
Commonly used in Sonic the Hedgehog sound drivers and level data.

Format Specification:
- Optional 2-byte Little-Endian Header indicating compressed payload size.
- Interleaved 8-bit descriptor bytes (LSB-first: bit 0 to bit 7).
- Bit 1: Literal byte copied directly to output.
- Bit 0: LZSS backreference (2 bytes):
  * Byte 0: offset_low (8 bits)
  * Byte 1: (offset_high << 4) | (length - 3)
  * Match length: 3 to 18 bytes.
  * Window size: 4096 bytes (12-bit circular lookback with +0x12 adjustment).
  * Supports zero-filling for negative initial window offsets.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

from miorom.errors import CompressionError


class SaxmanCodec:
    """
    Sega Genesis Saxman decompressor and compressor.
    """

    @classmethod
    def decompress(cls, data: bytes, with_size: Optional[bool] = None) -> bytes:
        """
        Decompresses Saxman-compressed binary data.
        If with_size is None, auto-detects whether a 2-byte Little-Endian size header is present.
        """
        if not data:
            return b""

        pos = 0
        total_len = len(data)

        # Size header detection
        has_size_header = False
        if with_size is True:
            has_size_header = True
        elif with_size is None and total_len >= 2:
            declared_size = struct.unpack_from("<H", data, 0)[0]
            if declared_size == total_len - 2:
                has_size_header = True

        if has_size_header:
            if total_len < 2:
                raise CompressionError("Data too short for Saxman 2-byte size header.")
            declared_size = struct.unpack_from("<H", data, 0)[0]
            pos = 2
            end_pos = min(total_len, 2 + declared_size)
        else:
            end_pos = total_len

        output = bytearray()
        desc_byte = 0
        bits_left = 0

        while pos < end_pos:
            if bits_left == 0:
                desc_byte = data[pos]
                pos += 1
                bits_left = 8

            is_literal = bool(desc_byte & 1)
            desc_byte >>= 1
            bits_left -= 1

            if is_literal:
                if pos >= end_pos:
                    break
                output.append(data[pos])
                pos += 1
            else:
                if pos + 2 > end_pos:
                    break
                b0 = data[pos]
                b1 = data[pos + 1]
                pos += 2

                offset = b0 | ((b1 & 0xF0) << 4)
                count = (b1 & 0x0F) + 3

                # +0x12 adjustment and 12-bit mask
                offset = (offset + 0x12) & 0x0FFF
                offset |= (len(output) & 0xF000)
                if offset >= len(output):
                    offset -= 0x1000

                if offset < 0:
                    for _ in range(count):
                        if offset < 0:
                            output.append(0)
                        else:
                            output.append(output[offset])
                        offset += 1
                else:
                    for _ in range(count):
                        output.append(output[offset])
                        offset += 1

        return bytes(output)

    @classmethod
    def compress(cls, data: bytes, with_size: bool = True) -> bytes:
        """
        Compresses raw binary data using the Saxman algorithm.
        """
        if not data:
            return struct.pack("<H", 0) if with_size else b""

        src_len = len(data)
        out = bytearray()

        desc_bits: List[int] = []
        payload_chunk = bytearray()

        pos = 0
        while pos < src_len:
            # Search for best match in sliding window (up to 4096 bytes back)
            best_dist = 0
            best_len = 0
            best_offset = 0

            max_check = min(18, src_len - pos)
            win_start = max(0, pos - 4096)

            if max_check >= 3:
                prefix = data[pos : pos + 3]
                search_end = pos
                while True:
                    found = data.rfind(prefix, win_start, search_end)
                    if found == -1:
                        break
                    # Match length
                    m_len = 3
                    while m_len < max_check and data[pos + m_len] == data[found + m_len]:
                        m_len += 1
                    if m_len > best_len:
                        best_len = m_len
                        best_offset = found
                        if best_len == max_check:
                            break
                    search_end = found

            if best_len >= 3:
                # Compressed token
                desc_bits.append(0)
                adj_offset = (best_offset - 0x12) & 0x0FFF
                b0 = adj_offset & 0xFF
                b1 = ((adj_offset >> 4) & 0xF0) | ((best_len - 3) & 0x0F)
                payload_chunk.extend([b0, b1])
                pos += best_len
            else:
                # Literal byte
                desc_bits.append(1)
                payload_chunk.append(data[pos])
                pos += 1

            if len(desc_bits) == 8:
                # Flush descriptor byte and payload
                desc_byte = 0
                for i, bit in enumerate(desc_bits):
                    desc_byte |= (bit << i)
                out.append(desc_byte)
                out.extend(payload_chunk)
                desc_bits.clear()
                payload_chunk.clear()

        # Flush any remaining bits
        if desc_bits:
            desc_byte = 0
            for i, bit in enumerate(desc_bits):
                desc_byte |= (bit << i)
            out.append(desc_byte)
            out.extend(payload_chunk)

        if with_size:
            return struct.pack("<H", len(out)) + bytes(out)
        return bytes(out)


# Alias
Saxman = SaxmanCodec
