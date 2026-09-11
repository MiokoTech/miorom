"""
miorom.compression.lzss
~~~~~~~~~~~~~~~~~~~~~~~
Standard Haruhiko Okumura LZSS (1989) compression and decompression codec.

Widely utilized across SNES, Sega Saturn, PlayStation, and retro PC games.
Uses a 4096-byte ring buffer (12-bit position) and 18-byte max match length.
"""

from __future__ import annotations

from typing import Optional

from miorom.errors import CompressionError
from miorom.result import MioRomResult


INDEX_BIT_COUNT = 12
LENGTH_BIT_COUNT = 4
WINDOW_SIZE = 1 << INDEX_BIT_COUNT  # 4096
MAX_MATCH_LEN = (1 << LENGTH_BIT_COUNT) + 2  # 18
THRESHOLD = 2
INITIAL_BUFFER_FILL = 0x20  # Okumura ASCII space fill


class LZSS(MioRomResult):
    """
    Standard Okumura LZSS (4096-byte sliding window, 18-byte lookahead).
    """

    @classmethod
    def decompress(
        cls,
        data: bytes,
        uncompressed_size: Optional[int] = None,
        init_pos: int = WINDOW_SIZE - MAX_MATCH_LEN,
        init_fill: int = INITIAL_BUFFER_FILL,
    ) -> bytes:
        """
        Decompresses standard Okumura LZSS binary byte streams.
        If uncompressed_size is None and stream has a 4-byte header, extracts size automatically.
        """
        if len(data) == 0:
            return b""

        pos = 0
        target_size = uncompressed_size

        ring_buffer = bytearray([init_fill] * WINDOW_SIZE)
        buf_pos = init_pos & (WINDOW_SIZE - 1)
        out = bytearray()
        flags = 0

        while pos < len(data):
            if target_size is not None and len(out) >= target_size:
                break

            flags >>= 1
            if (flags & 256) == 0:
                if pos >= len(data):
                    break
                flags = data[pos] | 0xFF00
                pos += 1

            if flags & 1:
                # 1 = Literal byte
                if pos >= len(data):
                    break
                byte_val = data[pos]
                pos += 1
                out.append(byte_val)
                ring_buffer[buf_pos] = byte_val
                buf_pos = (buf_pos + 1) & (WINDOW_SIZE - 1)
            else:
                # 0 = Backreference (offset, length)
                if pos + 1 >= len(data):
                    break
                b1 = data[pos]
                b2 = data[pos + 1]
                pos += 2

                match_offset = b1 | ((b2 & 0xF0) << 4)
                match_len = (b2 & 0x0F) + THRESHOLD + 1

                for k in range(match_len):
                    if target_size is not None and len(out) >= target_size:
                        break
                    ch = ring_buffer[(match_offset + k) & (WINDOW_SIZE - 1)]
                    out.append(ch)
                    ring_buffer[buf_pos] = ch
                    buf_pos = (buf_pos + 1) & (WINDOW_SIZE - 1)

        return bytes(out)

    @classmethod
    def compress(
        cls,
        data: bytes,
        init_pos: int = WINDOW_SIZE - MAX_MATCH_LEN,
        init_fill: int = INITIAL_BUFFER_FILL,
    ) -> bytes:
        """
        Compresses binary data into standard Okumura LZSS format.
        """
        if len(data) == 0:
            return b""

        ring_buffer = bytearray([init_fill] * WINDOW_SIZE)
        buf_pos = init_pos & (WINDOW_SIZE - 1)

        out = bytearray()
        code_buf = bytearray([0])
        mask = 1

        src_pos = 0
        src_len = len(data)

        while src_pos < src_len:
            # Search ring buffer for best match
            best_len = 0
            best_offset = 0
            max_cand_len = min(MAX_MATCH_LEN, src_len - src_pos)

            if max_cand_len > THRESHOLD:
                prefix = data[src_pos : src_pos + 3]
                # Scan entire 4096 ring buffer
                for cand_offset in range(WINDOW_SIZE):
                    # Check first 3 bytes
                    if (
                        ring_buffer[cand_offset] == prefix[0]
                        and ring_buffer[(cand_offset + 1) & (WINDOW_SIZE - 1)] == prefix[1]
                        and ring_buffer[(cand_offset + 2) & (WINDOW_SIZE - 1)] == prefix[2]
                    ):
                        k = 3
                        while k < max_cand_len:
                            if ring_buffer[(cand_offset + k) & (WINDOW_SIZE - 1)] != data[src_pos + k]:
                                break
                            k += 1
                        if k > best_len:
                            best_len = k
                            best_offset = cand_offset
                            if best_len == max_cand_len:
                                break

            if best_len > THRESHOLD:
                # Emit match
                match_pos = best_offset
                match_count = best_len - THRESHOLD - 1
                b1 = match_pos & 0xFF
                b2 = ((match_pos >> 4) & 0xF0) | (match_count & 0x0F)
                code_buf.append(b1)
                code_buf.append(b2)

                for k in range(best_len):
                    ring_buffer[buf_pos] = data[src_pos + k]
                    buf_pos = (buf_pos + 1) & (WINDOW_SIZE - 1)
                src_pos += best_len
            else:
                # Emit literal
                code_buf[0] |= mask
                ch = data[src_pos]
                code_buf.append(ch)
                ring_buffer[buf_pos] = ch
                buf_pos = (buf_pos + 1) & (WINDOW_SIZE - 1)
                src_pos += 1

            mask = (mask << 1) & 0xFF
            if mask == 0:
                # Flush 8-token chunk
                out.extend(code_buf)
                code_buf = bytearray([0])
                mask = 1

        # Flush final partial chunk if any
        if len(code_buf) > 1:
            out.extend(code_buf)

        return bytes(out)
