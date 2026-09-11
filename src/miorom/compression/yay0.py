"""
miorom.compression.yay0
~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Yay0 compression codec.
Commonly used in Nintendo 64 and early GameCube titles (Super Mario 64,
The Legend of Zelda: Ocarina of Time, Majora's Mask, Star Fox 64, Diddy Kong Racing).

Yay0 is an LZSS variant that organizes data into three separate streams:
1. 32-bit big-endian bitmasks (at offset 0x10) indicating literal vs backreference.
2. 16-bit link table entries for backreference distance and length.
3. 8-bit byte chunk containing raw literals and extended copy lengths.
"""

from __future__ import annotations

import struct
from typing import List, Optional

from miorom.core.schema import BinaryStruct, RawBytes, U32
from miorom.errors import CompressionError


class Yay0HeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)
    uncompressed_size = U32()
    link_offset = U32()
    data_offset = U32()


class Yay0:
    """
    Nintendo Yay0 decompressor and compressor.
    """

    MAGIC = b"Yay0"

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """
        Decompresses Yay0 compressed binary data into raw bytes.
        """
        if len(data) < 16:
            raise CompressionError("Data too short for Yay0 header (minimum 16 bytes required).")
        if data[:4] != cls.MAGIC:
            raise CompressionError(f"Invalid Yay0 magic header: {data[:4]!r}")

        header = Yay0HeaderStruct.from_bytes(data)
        uncompressed_size = header.uncompressed_size
        link_pos = header.link_offset
        data_pos = header.data_offset

        if link_pos > len(data) or data_pos > len(data):
            raise CompressionError("Corrupted Yay0 header offsets point past end of data.")

        output = bytearray()
        mask_pos = 16
        valid_bits = 0
        mask_word = 0

        while len(output) < uncompressed_size:
            if valid_bits == 0:
                if mask_pos + 4 > link_pos or mask_pos + 4 > len(data):
                    break
                mask_word = struct.unpack(">I", data[mask_pos : mask_pos + 4])[0]
                mask_pos += 4
                valid_bits = 32

            is_literal = bool((mask_word >> 31) & 1)
            mask_word = (mask_word << 1) & 0xFFFFFFFF
            valid_bits -= 1

            if is_literal:
                if data_pos >= len(data):
                    break
                output.append(data[data_pos])
                data_pos += 1
            else:
                if link_pos + 2 > len(data):
                    break
                link = struct.unpack(">H", data[link_pos : link_pos + 2])[0]
                link_pos += 2

                dist = (link & 0x0FFF) + 1
                length = link >> 12

                if length == 0:
                    if data_pos >= len(data):
                        break
                    length = data[data_pos] + 18
                    data_pos += 1
                else:
                    length += 2

                copy_src = len(output) - dist
                if copy_src < 0:
                    raise CompressionError(
                        f"Yay0 backreference out of bounds: dist={dist}, current output size={len(output)}"
                    )

                for _ in range(length):
                    if len(output) >= uncompressed_size:
                        break
                    output.append(output[copy_src])
                    copy_src += 1

        if len(output) < uncompressed_size:
            raise CompressionError(
                f"Yay0 decompression truncated: expected {uncompressed_size} bytes, got {len(output)} bytes"
            )

        return bytes(output)

    @classmethod
    def compress(cls, data: bytes) -> bytes:
        """
        Compresses raw binary bytes using Yay0 algorithm.
        """
        if not data:
            # 16-byte header for empty data
            return cls.MAGIC + struct.pack(">III", 0, 16, 16)

        mask_bits: List[bool] = []
        link_entries: List[int] = []
        byte_chunk = bytearray()

        pos = 0
        src_len = len(data)

        while pos < src_len:
            best_dist = 0
            best_len = 0

            # Search back in history window (max 4096 bytes)
            win_start = max(0, pos - 4096)
            max_check = min(273, src_len - pos)

            if max_check >= 3:
                cand_len = 3
                while cand_len <= max_check:
                    pat = data[pos : pos + cand_len]
                    found = data.rfind(pat, win_start, pos)
                    if found != -1:
                        best_dist = pos - found
                        best_len = cand_len
                        cand_len += 1
                    else:
                        break

            if best_len >= 3:
                # Emit backreference
                mask_bits.append(False)
                dist_val = (best_dist - 1) & 0x0FFF
                if best_len >= 18:
                    # Extended length
                    link_word = dist_val  # high 4 bits = 0
                    link_entries.append(link_word)
                    byte_chunk.append(best_len - 18)
                else:
                    link_word = ((best_len - 2) << 12) | dist_val
                    link_entries.append(link_word)
                pos += best_len
            else:
                # Emit literal
                mask_bits.append(True)
                byte_chunk.append(data[pos])
                pos += 1

        # Pack mask bits into 32-bit words
        mask_words: List[int] = []
        cur_word = 0
        cur_bit_count = 0

        for bit in mask_bits:
            cur_word = (cur_word << 1) | (1 if bit else 0)
            cur_bit_count += 1
            if cur_bit_count == 32:
                mask_words.append(cur_word)
                cur_word = 0
                cur_bit_count = 0

        if cur_bit_count > 0:
            cur_word <<= (32 - cur_bit_count)
            mask_words.append(cur_word)

        # Build buffers and calculate offsets
        mask_bytes = bytearray()
        for w in mask_words:
            mask_bytes.extend(struct.pack(">I", w))

        link_bytes = bytearray()
        for lk in link_entries:
            link_bytes.extend(struct.pack(">H", lk))

        link_offset = 16 + len(mask_bytes)
        data_offset = link_offset + len(link_bytes)

        header = cls.MAGIC + struct.pack(">III", src_len, link_offset, data_offset)
        return header + bytes(mask_bytes) + bytes(link_bytes) + bytes(byte_chunk)
