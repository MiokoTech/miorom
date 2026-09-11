"""
miorom.compression.mio0
~~~~~~~~~~~~~~~~~~~~~~~
Nintendo 64 MIO0 compression codec.
Commonly used in Nintendo 64 games (Super Mario 64, Mario Kart 64,
Star Fox 64, Pokémon Stadium, early Zelda 64 / Ocarina of Time builds).

MIO0 is an LZ77-variant compression format that multiplexes three separate data sections:
1. 16-byte Big-Endian Header ('MIO0', decompressed length, compressed offset, uncompressed offset).
2. Layout bitstream (starting at offset 0x10):
   - Bit 1: 1 uncompressed literal byte from uncompressed offset.
   - Bit 0: 2-byte token from compressed offset (lookback distance & length).
3. Compressed stream (16-bit big-endian LZ tokens):
   - Upper 4 bits + 3: match length (3 to 18 bytes).
   - Lower 12 bits + 1: backreference distance (1 to 4096 bytes).
4. Uncompressed stream: raw literal bytes.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

from miorom.core.schema import BinaryStruct, RawBytes, U32
from miorom.errors import CompressionError


class MIO0HeaderStruct(BinaryStruct):
    """
    16-byte MIO0 Big-Endian Header.
    """
    _endian = ">"
    magic = RawBytes(4)
    uncompressed_size = U32()
    compressed_offset = U32()
    uncompressed_offset = U32()


def _find_longest_match(
    data: bytes, pos: int, max_len: int = 18, max_dist: int = 4096
) -> Tuple[int, int]:
    """
    Finds the longest lookback match for data at `pos`.
    Supports overlapping/cyclic matches (e.g. RLE).
    Returns (distance, length). If no match >= 3 is found, returns (0, 0).
    """
    src_len = len(data)
    avail = src_len - pos
    if avail < 3:
        return 0, 0

    max_check = min(max_len, avail)
    best_len = 0
    best_dist = 0

    # Fast-path 1: Single byte RLE (distance = 1)
    if pos >= 1 and data[pos] == data[pos - 1]:
        b = data[pos - 1]
        rle_len = 0
        while rle_len < max_check and data[pos + rle_len] == b:
            rle_len += 1
        if rle_len >= 3:
            best_len = rle_len
            best_dist = 1
            if best_len == max_check:
                return best_dist, best_len

    # Fast-path 2: 2-byte periodic pattern (distance = 2)
    if pos >= 2 and data[pos : pos + 2] == data[pos - 2 : pos]:
        pat0, pat1 = data[pos - 2], data[pos - 1]
        p_len = 0
        while p_len < max_check:
            expected = pat0 if (p_len % 2 == 0) else pat1
            if data[pos + p_len] != expected:
                break
            p_len += 1
        if p_len > best_len:
            best_len = p_len
            best_dist = 2
            if best_len == max_check:
                return best_dist, best_len

    # General search using 3-byte prefix and rfind
    prefix = data[pos : pos + 3]
    win_start = max(0, pos - max_dist)
    search_end = pos
    searches = 0

    while searches < 32:
        found = data.rfind(prefix, win_start, search_end)
        if found == -1:
            break
        searches += 1
        dist = pos - found
        
        # Extend match (allowing cyclic overlap where match_len > dist)
        match_len = 3
        while match_len < max_check and data[pos + match_len] == data[found + (match_len % dist)]:
            match_len += 1

        if match_len > best_len:
            best_len = match_len
            best_dist = dist
            if best_len == max_check:
                break

        search_end = found

    return best_dist, best_len


class MIO0Codec:
    """
    Nintendo 64 MIO0 decompressor and compressor.
    """

    MAGIC = b"MIO0"

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """
        Decompresses MIO0 binary data into raw bytes.
        """
        if len(data) < 16:
            raise CompressionError("Data too short for MIO0 header (minimum 16 bytes required).")
        if data[:4] != cls.MAGIC:
            raise CompressionError(f"Invalid MIO0 magic header: {data[:4]!r}")

        header = MIO0HeaderStruct.from_bytes(data[:16])
        uncompressed_size = header.uncompressed_size
        comp_offset = header.compressed_offset
        uncomp_offset = header.uncompressed_offset

        if uncompressed_size == 0:
            return b""

        if comp_offset > len(data) or uncomp_offset > len(data):
            raise CompressionError("Corrupted MIO0 header offsets point past end of data.")

        output = bytearray()
        bit_idx = 0
        comp_idx = comp_offset
        uncomp_idx = uncomp_offset

        while len(output) < uncompressed_size:
            byte_pos = 16 + (bit_idx >> 3)
            if byte_pos >= comp_offset or byte_pos >= len(data):
                raise CompressionError("MIO0 bitstream overrun before reaching decompressed size.")

            is_literal = bool((data[byte_pos] >> (7 - (bit_idx & 7))) & 1)
            bit_idx += 1

            if is_literal:
                if uncomp_idx >= len(data):
                    raise CompressionError(
                        f"MIO0 uncompressed stream truncated at offset {uncomp_idx}."
                    )
                output.append(data[uncomp_idx])
                uncomp_idx += 1
            else:
                if comp_idx + 2 > len(data):
                    raise CompressionError(
                        f"MIO0 compressed stream truncated at offset {comp_idx}."
                    )
                val = (data[comp_idx] << 8) | data[comp_idx + 1]
                comp_idx += 2

                length = ((val >> 12) & 0x0F) + 3
                dist = (val & 0x0FFF) + 1

                copy_src = len(output) - dist
                if copy_src < 0:
                    raise CompressionError(
                        f"MIO0 backreference out of bounds: dist={dist}, current output size={len(output)}."
                    )

                for _ in range(length):
                    if len(output) >= uncompressed_size:
                        break
                    output.append(output[copy_src])
                    copy_src += 1

        if len(output) < uncompressed_size:
            raise CompressionError(
                f"MIO0 decompression truncated: expected {uncompressed_size} bytes, got {len(output)} bytes."
            )

        return bytes(output)

    @classmethod
    def compress(cls, data: bytes) -> bytes:
        """
        Compresses raw binary data using Nintendo 64 MIO0 format.
        """
        if not data:
            return cls.MAGIC + struct.pack(">III", 0, 16, 16)

        src_len = len(data)
        bit_flags: List[int] = []
        comp_buf = bytearray()
        uncomp_buf = bytearray()

        pos = 0
        while pos < src_len:
            max_check = min(18, src_len - pos)
            best_dist, best_len = _find_longest_match(data, pos, max_len=max_check)

            # 1-step lookahead optimization
            if best_len >= 3 and pos + 1 < src_len:
                next_check = min(18, src_len - (pos + 1))
                next_dist, next_len = _find_longest_match(data, pos + 1, max_len=next_check)
                if next_len > best_len + 1:
                    # Emit current byte as literal and take the superior next match
                    bit_flags.append(1)
                    uncomp_buf.append(data[pos])
                    pos += 1
                    best_dist, best_len = next_dist, next_len

            if best_len >= 3:
                bit_flags.append(0)
                token = (((best_len - 3) & 0x0F) << 12) | ((best_dist - 1) & 0x0FFF)
                comp_buf.extend(struct.pack(">H", token))
                pos += best_len
            else:
                bit_flags.append(1)
                uncomp_buf.append(data[pos])
                pos += 1

        # Pack bit flags into bytes (MSB first)
        bit_buf = bytearray()
        cur_byte = 0
        cur_count = 0
        for b in bit_flags:
            cur_byte = (cur_byte << 1) | (b & 1)
            cur_count += 1
            if cur_count == 8:
                bit_buf.append(cur_byte)
                cur_byte = 0
                cur_count = 0
        if cur_count > 0:
            cur_byte <<= (8 - cur_count)
            bit_buf.append(cur_byte)

        # Offsets and 4-byte boundary alignment
        header_len = 16
        comp_offset = (header_len + len(bit_buf) + 3) & ~3
        pad_len = comp_offset - (header_len + len(bit_buf))
        uncomp_offset = comp_offset + len(comp_buf)

        header = cls.MAGIC + struct.pack(">III", src_len, comp_offset, uncomp_offset)
        return header + bytes(bit_buf) + (b"\x00" * pad_len) + bytes(comp_buf) + bytes(uncomp_buf)


# Alias
MIO0 = MIO0Codec
