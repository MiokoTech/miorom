from miorom.errors import CompressionError
from miorom.core.schema import BinaryStruct, U32
from typing import Union


class LZExtendedSizeStruct(BinaryStruct):
    _endian = "<"
    uncompressed_size = U32()


class LZ10:
    """
    Nintendo standard LZ77 Type 0x10 compression and decompression.
    Used widely across Game Boy Advance, Nintendo DS, DSi, Wii, and 3DS.
    """

    MAGIC = 0x10

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """Decompress LZ10 compressed data."""
        if len(data) < 4:
            raise CompressionError("Data too short for LZ10 header")

        magic = data[0]
        if magic != cls.MAGIC:
            raise CompressionError(f"Invalid LZ10 magic byte: expected 0x10, got {hex(magic)}")

        uncompressed_size = data[1] | (data[2] << 8) | (data[3] << 16)
        in_pos = 4

        if uncompressed_size == 0:
            if len(data) == 4:
                return b""
            if len(data) < 8:
                raise CompressionError("Data too short for extended LZ10 header")
            uncompressed_size = LZExtendedSizeStruct.from_bytes(data, offset=4).uncompressed_size
            in_pos = 8

        out = bytearray()
        data_len = len(data)

        while len(out) < uncompressed_size and in_pos < data_len:
            flags = data[in_pos]
            in_pos += 1

            for bit in range(7, -1, -1):
                if len(out) >= uncompressed_size or in_pos >= data_len:
                    break

                if (flags >> bit) & 1:
                    # Compressed block (2 bytes)
                    if in_pos + 1 >= data_len:
                        break
                    b1 = data[in_pos]
                    b2 = data[in_pos + 1]
                    in_pos += 2

                    length = (b1 >> 4) + 3
                    disp = (((b1 & 0x0F) << 8) | b2) + 1

                    if disp > len(out):
                        raise CompressionError(f"LZ10 invalid displacement {disp} at pos {len(out)}")

                    copy_pos = len(out) - disp
                    for _ in range(length):
                        out.append(out[copy_pos])
                        copy_pos += 1
                        if len(out) >= uncompressed_size:
                            break
                else:
                    # Literal byte
                    out.append(data[in_pos])
                    in_pos += 1

        if len(out) < uncompressed_size:
            raise CompressionError(
                f"LZ10 decompression truncated: expected {uncompressed_size} bytes, got {len(out)} bytes"
            )

        return bytes(out)

    @classmethod
    def compress(cls, data: bytes) -> bytes:
        """Compress data using Nintendo LZ10 format."""
        out = bytearray()
        uncompressed_size = len(data)

        # Header
        if uncompressed_size <= 0xFFFFFF:
            out.append(cls.MAGIC)
            out.append(uncompressed_size & 0xFF)
            out.append((uncompressed_size >> 8) & 0xFF)
            out.append((uncompressed_size >> 16) & 0xFF)
        else:
            out.append(cls.MAGIC)
            out.extend(b"\x00\x00\x00")
            out.extend(LZExtendedSizeStruct(uncompressed_size=uncompressed_size).to_bytes())

        in_pos = 0
        data_len = len(data)

        while in_pos < data_len:
            flag_pos = len(out)
            out.append(0) # placeholder for flags byte
            flags = 0

            for bit in range(7, -1, -1):
                if in_pos >= data_len:
                    break

                # Search for match in sliding window (max 4096 bytes back)
                best_len = 0
                best_disp = 0
                max_len = min(18, data_len - in_pos)

                if in_pos >= 3 and max_len >= 3:
                    window_start = max(0, in_pos - 4096)
                    # Optimization: only check match candidates that match the first 3 bytes
                    target3 = data[in_pos:in_pos+3]
                    search_pos = in_pos - 1

                    while search_pos >= window_start:
                        pos = data.rfind(target3, window_start, search_pos + 3)
                        if pos == -1:
                            break

                        # Measure match length
                        match_len = 3
                        while (match_len < max_len and
                               data[pos + match_len] == data[in_pos + match_len]):
                            match_len += 1

                        if match_len > best_len:
                            best_len = match_len
                            best_disp = in_pos - pos
                            if best_len == max_len:
                                break

                        search_pos = pos - 1

                if best_len >= 3:
                    # Compressed block
                    flags |= (1 << bit)
                    b1 = ((best_len - 3) << 4) | (((best_disp - 1) >> 8) & 0x0F)
                    b2 = (best_disp - 1) & 0xFF
                    out.append(b1)
                    out.append(b2)
                    in_pos += best_len
                else:
                    # Literal
                    out.append(data[in_pos])
                    in_pos += 1

            out[flag_pos] = flags

        # Pad output to 4 bytes alignment (Nintendo BIOS standard)
        while len(out) % 4 != 0:
            out.append(0)

        return bytes(out)
