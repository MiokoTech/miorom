"""
miorom.compression.comper
~~~~~~~~~~~~~~~~~~~~~~~~~
Sega Genesis / Mega Drive Comper compression codec.
Designed by The Squee for high decompression speed on the Motorola 68000.
Commonly used in Sonic the Hedgehog 1 and Sonic 3 & Knuckles title/art data.

Format Specification:
- Word-oriented (16-bit Big-Endian words).
- Interleaved 16-bit Big-Endian descriptor words (MSB-first: bit 15 to bit 0).
- Bit 0: Literal 16-bit word copied directly to output (2 bytes).
- Bit 1: Dictionary match (2 bytes):
  * Byte 0: neg_dist (distance in words = (0x100 - neg_dist), so distance in bytes = (0x100 - neg_dist) * 2).
  * Byte 1: length_byte
    - If length_byte == 0: End-Of-Stream marker (Terminator).
    - If length_byte > 0: Copy (length_byte + 1) words from lookback buffer.
- Window size: up to 256 words (512 bytes).
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

from miorom.errors import CompressionError


class ComperCodec:
    """
    Sega Genesis Comper decompressor and compressor.
    """

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """
        Decompresses Comper-compressed binary data into raw bytes.
        """
        if not data:
            return b""

        pos = 0
        total_len = len(data)
        output = bytearray()

        desc_word = 0
        bits_left = 0

        while pos < total_len:
            if bits_left == 0:
                if pos + 2 > total_len:
                    break
                desc_word = struct.unpack_from(">H", data, pos)[0]
                pos += 2
                bits_left = 16

            is_match = bool((desc_word >> 15) & 1)
            desc_word = (desc_word << 1) & 0xFFFF
            bits_left -= 1

            if not is_match:
                # Bit 0: Literal 16-bit word
                if pos + 2 > total_len:
                    break
                output.extend(data[pos : pos + 2])
                pos += 2
            else:
                # Bit 1: Dictionary match or terminator
                if pos + 2 > total_len:
                    break
                neg_dist = data[pos]
                length_byte = data[pos + 1]
                pos += 2

                if length_byte == 0:
                    # End-of-stream terminator
                    break

                num_words = length_byte + 1
                dist_bytes = (0x100 - neg_dist) * 2

                copy_src = len(output) - dist_bytes
                if copy_src < 0:
                    raise CompressionError(
                        f"Comper backreference out of bounds: dist={dist_bytes}, output size={len(output)}."
                    )

                for _ in range(num_words):
                    output.append(output[copy_src])
                    output.append(output[copy_src + 1])
                    copy_src += 2

        return bytes(output)

    @classmethod
    def compress(cls, data: bytes) -> bytes:
        """
        Compresses raw binary data using the Comper algorithm.
        Pads odd-length input to 16-bit word boundary.
        """
        if not data:
            # Output empty terminator
            return struct.pack(">HBB", 0x8000, 0, 0)

        # Pad to even length if necessary
        padded_data = data if (len(data) % 2 == 0) else (data + b"\x00")
        src_len = len(padded_data)

        out = bytearray()
        desc_bits: List[int] = []
        payload_chunk = bytearray()

        pos = 0
        while pos < src_len:
            # Search for best match in words (up to 256 words / 512 bytes back)
            best_dist_words = 0
            best_len_words = 0

            max_check_words = min(256, (src_len - pos) // 2)
            win_start_words = max(0, (pos - 512) // 2)

            if max_check_words >= 2:
                cur_word = padded_data[pos : pos + 2]
                search_end = pos

                while True:
                    found = padded_data.rfind(cur_word, win_start_words * 2, search_end)
                    if found == -1:
                        break
                    # Must be word-aligned
                    if (found % 2) == 0:
                        dist_words = (pos - found) // 2
                        if 1 <= dist_words <= 256:
                            # Measure match length in words
                            m_words = 1
                            while (
                                m_words < max_check_words
                                and padded_data[pos + m_words * 2 : pos + (m_words + 1) * 2]
                                == padded_data[found + m_words * 2 : found + (m_words + 1) * 2]
                            ):
                                m_words += 1

                            if m_words > best_len_words:
                                best_len_words = m_words
                                best_dist_words = dist_words
                                if best_len_words == max_check_words:
                                    break
                    search_end = found

            if best_len_words >= 2:
                # Compressed match: bit 1
                desc_bits.append(1)
                neg_dist = (256 - best_dist_words) & 0xFF
                length_byte = best_len_words - 1
                payload_chunk.extend([neg_dist, length_byte])
                pos += best_len_words * 2
            else:
                # Literal word: bit 0
                desc_bits.append(0)
                payload_chunk.extend(padded_data[pos : pos + 2])
                pos += 2

            if len(desc_bits) == 16:
                desc_word = 0
                for i, bit in enumerate(desc_bits):
                    desc_word |= (bit << (15 - i))
                out.extend(struct.pack(">H", desc_word))
                out.extend(payload_chunk)
                desc_bits.clear()
                payload_chunk.clear()

        # Emit terminator: bit 1 with (0x00, 0x00)
        desc_bits.append(1)
        payload_chunk.extend([0, 0])

        # Flush remaining bits
        desc_word = 0
        for i, bit in enumerate(desc_bits):
            desc_word |= (bit << (15 - i))
        out.extend(struct.pack(">H", desc_word))
        out.extend(payload_chunk)

        return bytes(out)


# Alias
Comper = ComperCodec
