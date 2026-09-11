"""
miorom.compression.refpack
~~~~~~~~~~~~~~~~~~~~~~~~~~
EA RefPack (QFS) compression and decompression codec.

Used extensively by Electronic Arts across PC, PlayStation, PlayStation 2,
Saturn, and GameCube games (Command & Conquer, Need for Speed, The Sims, SimCity).
"""

from __future__ import annotations

import io
from typing import List, Tuple

from miorom.errors import CompressionError
from miorom.result import MioRomResult


class RefPack(MioRomResult):
    """
    Electronic Arts RefPack (QFS) decompressor and compressor.
    """

    MAGIC = b"\x10\xfb"

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """Decompresses EA RefPack / QFS compressed binary data."""
        if len(data) < 5:
            raise CompressionError("Data too short for RefPack header (minimum 5 bytes).")

        # Check signature
        b0 = data[0]
        b1 = data[1]
        if (b0 & 0x3E) != 0x10 or b1 != 0xFB:
            raise CompressionError(f"Invalid RefPack header magic: {data[:2]!r}")

        has_large_size = bool(b0 & 0x01)
        pos = 2

        if has_large_size:
            if len(data) < 6:
                raise CompressionError("Truncated RefPack 4-byte size header.")
            uncompressed_size = (data[pos] << 24) | (data[pos + 1] << 16) | (data[pos + 2] << 8) | data[pos + 3]
            pos += 4
        else:
            uncompressed_size = (data[pos] << 16) | (data[pos + 1] << 8) | data[pos + 2]
            pos += 3

        out = bytearray()

        while pos < len(data):
            cmd = data[pos]
            pos += 1

            if cmd < 0x80:
                # 2-byte command
                if pos >= len(data):
                    raise CompressionError("Truncated 2-byte RefPack command.")
                b_next = data[pos]
                pos += 1

                lit_count = cmd & 0x03
                copy_count = ((cmd >> 2) & 0x07) + 3
                offset = ((cmd & 0x60) << 3) + b_next + 1

                if lit_count > 0:
                    if pos + lit_count > len(data):
                        raise CompressionError("Truncated literals in 2-byte RefPack command.")
                    out.extend(data[pos : pos + lit_count])
                    pos += lit_count

                if offset > len(out):
                    raise CompressionError(f"RefPack backreference offset {offset} exceeds output length {len(out)}.")

                src_idx = len(out) - offset
                for _ in range(copy_count):
                    out.append(out[src_idx])
                    src_idx += 1

            elif cmd < 0xC0:
                # 3-byte command
                if pos + 1 >= len(data):
                    raise CompressionError("Truncated 3-byte RefPack command.")
                b_next1 = data[pos]
                b_next2 = data[pos + 1]
                pos += 2

                copy_count = (cmd & 0x3F) + 4
                lit_count = b_next1 >> 6
                offset = ((b_next1 & 0x3F) << 8) + b_next2 + 1

                if lit_count > 0:
                    if pos + lit_count > len(data):
                        raise CompressionError("Truncated literals in 3-byte RefPack command.")
                    out.extend(data[pos : pos + lit_count])
                    pos += lit_count

                if offset > len(out):
                    raise CompressionError(f"RefPack backreference offset {offset} exceeds output length {len(out)}.")

                src_idx = len(out) - offset
                for _ in range(copy_count):
                    out.append(out[src_idx])
                    src_idx += 1

            elif cmd < 0xE0:
                # 4-byte command
                if pos + 2 >= len(data):
                    raise CompressionError("Truncated 4-byte RefPack command.")
                b_next1 = data[pos]
                b_next2 = data[pos + 1]
                b_next3 = data[pos + 2]
                pos += 3

                lit_count = cmd & 0x03
                copy_count = (((cmd >> 2) & 0x03) << 8) + b_next3 + 5
                offset = ((cmd & 0x10) << 12) + (b_next1 << 8) + b_next2 + 1

                if lit_count > 0:
                    if pos + lit_count > len(data):
                        raise CompressionError("Truncated literals in 4-byte RefPack command.")
                    out.extend(data[pos : pos + lit_count])
                    pos += lit_count

                if offset > len(out):
                    raise CompressionError(f"RefPack backreference offset {offset} exceeds output length {len(out)}.")

                src_idx = len(out) - offset
                for _ in range(copy_count):
                    out.append(out[src_idx])
                    src_idx += 1

            elif cmd < 0xFC:
                # Literal run command
                lit_count = ((cmd & 0x1F) + 1) * 4
                if pos + lit_count > len(data):
                    raise CompressionError("Truncated literal run command.")
                out.extend(data[pos : pos + lit_count])
                pos += lit_count

            else:
                # End of stream / final literal command
                lit_count = cmd & 0x03
                if lit_count > 0:
                    if pos + lit_count > len(data):
                        raise CompressionError("Truncated terminal literals.")
                    out.extend(data[pos : pos + lit_count])
                    pos += lit_count
                break

        return bytes(out)

    @classmethod
    def compress(cls, data: bytes) -> bytes:
        """Compresses binary data into EA RefPack / QFS format."""
        out = bytearray()
        size = len(data)

        # 3-byte size header
        out.append(0x10)
        out.append(0xFB)
        out.append((size >> 16) & 0xFF)
        out.append((size >> 8) & 0xFF)
        out.append(size & 0xFF)

        cursor = 0
        literal_buf = bytearray()

        def flush_literals():
            nonlocal literal_buf
            while len(literal_buf) >= 4:
                # Literal run block (multiples of 4, up to 112 bytes)
                take = min(112, len(literal_buf) - (len(literal_buf) % 4))
                cmd = 0xE0 | ((take // 4) - 1)
                out.append(cmd)
                out.extend(literal_buf[:take])
                literal_buf = literal_buf[take:]

        while cursor < size:
            # Look for best match within sliding window
            best_len = 0
            best_offset = 0

            max_offset = min(cursor, 131072)
            max_len = min(1028, size - cursor)

            # Fast window search (lookback up to 16384 for standard speed)
            window_start = max(0, cursor - 16384)
            current_prefix = data[cursor : cursor + 3]

            if len(current_prefix) >= 3:
                pos = cursor - 1
                while pos >= window_start:
                    if data[pos : pos + 3] == current_prefix:
                        match_l = 3
                        while (
                            match_l < max_len
                            and data[pos + match_l] == data[cursor + match_l]
                        ):
                            match_l += 1
                        if match_l > best_len:
                            best_len = match_l
                            best_offset = cursor - pos
                            if best_len >= 67:
                                break
                    pos -= 1

            if best_len >= 3:
                # Match found; flush literal chunks if needed
                if len(literal_buf) > 3:
                    flush_literals()
                lit_count = len(literal_buf)

                if lit_count <= 3 and best_offset <= 1024 and 3 <= best_len <= 10:
                    # 2-byte command
                    cmd = (
                        ((best_offset - 1) >> 3) & 0x60
                        | ((best_len - 3) << 2)
                        | lit_count
                    )
                    out.append(cmd)
                    out.append((best_offset - 1) & 0xFF)
                    if lit_count > 0:
                        out.extend(literal_buf)
                        literal_buf.clear()
                    cursor += best_len
                    continue

                if lit_count <= 3 and best_offset <= 16384 and best_len >= 4:
                    # 3-byte command
                    chunk_len = min(67, best_len)
                    cmd = 0x80 | (chunk_len - 4)
                    b1 = (lit_count << 6) | (((best_offset - 1) >> 8) & 0x3F)
                    b2 = (best_offset - 1) & 0xFF
                    out.append(cmd)
                    out.append(b1)
                    out.append(b2)
                    if lit_count > 0:
                        out.extend(literal_buf)
                        literal_buf.clear()
                    cursor += chunk_len
                    continue

            literal_buf.append(data[cursor])
            cursor += 1

        # Flush remaining literals and emit stop opcode
        flush_literals()
        stop_cmd = 0xFC | (len(literal_buf) & 0x03)
        out.append(stop_cmd)
        if literal_buf:
            out.extend(literal_buf)

        return bytes(out)
