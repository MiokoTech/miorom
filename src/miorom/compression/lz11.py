from miorom.errors import CompressionError
from miorom.core.schema import BinaryStruct, U32


class LZ11:
    """
    Nintendo standard LZ77 Type 0x11 compression and decompression.
    Introduced with the Nintendo DS, widely used in NDS, Wii, and 3DS.
    Features variable-length encoding allowing match lengths up to 65,808 bytes.
    """

    MAGIC = 0x11


    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """Decompress LZ11 compressed data."""
        if len(data) < 4:
            raise CompressionError("Data too short for LZ11 header")

        magic = data[0]
        if magic != cls.MAGIC:
            raise CompressionError(f"Invalid LZ11 magic byte: expected 0x11, got {hex(magic)}")

        uncompressed_size = data[1] | (data[2] << 8) | (data[3] << 16)
        in_pos = 4

        if uncompressed_size == 0:
            if len(data) == 4:
                return b""
            if len(data) < 8:
                raise CompressionError("Data too short for extended LZ11 header")
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
                    # Compressed block (2, 3, or 4 bytes)
                    b1 = data[in_pos]
                    in_pos += 1
                    indicator = b1 >> 4

                    if indicator == 0:
                        # 3 bytes: Length 0x11 - 0x110
                        if in_pos + 1 >= data_len:
                            break
                        b2 = data[in_pos]
                        b3 = data[in_pos + 1]
                        in_pos += 2
                        length = (((b1 & 0x0F) << 4) | (b2 >> 4)) + 0x11
                        disp = (((b2 & 0x0F) << 8) | b3) + 1
                    elif indicator == 1:
                        # 4 bytes: Length 0x111 - 0x10110
                        if in_pos + 2 >= data_len:
                            break
                        b2 = data[in_pos]
                        b3 = data[in_pos + 1]
                        b4 = data[in_pos + 2]
                        in_pos += 3
                        length = (((b1 & 0x0F) << 12) | (b2 << 4) | (b3 >> 4)) + 0x111
                        disp = (((b3 & 0x0F) << 8) | b4) + 1
                    else:
                        # 2 bytes: Length 3 - 16
                        if in_pos >= data_len:
                            break
                        b2 = data[in_pos]
                        in_pos += 1
                        length = indicator + 1
                        disp = (((b1 & 0x0F) << 8) | b2) + 1

                    if disp > len(out):
                        raise CompressionError(f"LZ11 invalid displacement {disp} at pos {len(out)}")

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

        return bytes(out)

    @classmethod
    def compress(cls, data: bytes) -> bytes:
        """Compress data using Nintendo LZ11 format."""
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

                best_len = 0
                best_disp = 0
                max_len = min(65808, data_len - in_pos)

                if in_pos >= 3 and max_len >= 3:
                    window_start = max(0, in_pos - 4096)
                    target3 = data[in_pos:in_pos+3]
                    search_pos = in_pos - 1

                    while search_pos >= window_start:
                        pos = data.rfind(target3, window_start, search_pos + 3)
                        if pos == -1:
                            break

                        match_len = 3
                        while (match_len < max_len and
                               data[pos + match_len] == data[in_pos + match_len]):
                            match_len += 1

                        if match_len > best_len:
                            best_len = match_len
                            best_disp = in_pos - pos
                            if best_len >= max_len:
                                break

                        search_pos = pos - 1

                if best_len >= 3:
                    flags |= (1 << bit)
                    disp_val = best_disp - 1

                    if best_len <= 16:
                        # 2-byte encoding
                        b1 = ((best_len - 1) << 4) | ((disp_val >> 8) & 0x0F)
                        b2 = disp_val & 0xFF
                        out.append(b1)
                        out.append(b2)
                    elif best_len <= 0x110:
                        # 3-byte encoding: indicator = 0
                        adjusted = best_len - 0x11
                        b1 = (adjusted >> 4) & 0x0F
                        b2 = ((adjusted & 0x0F) << 4) | ((disp_val >> 8) & 0x0F)
                        b3 = disp_val & 0xFF
                        out.append(b1)
                        out.append(b2)
                        out.append(b3)
                    else:
                        # 4-byte encoding: indicator = 1
                        adjusted = best_len - 0x111
                        b1 = 0x10 | ((adjusted >> 12) & 0x0F)
                        b2 = (adjusted >> 4) & 0xFF
                        b3 = ((adjusted & 0x0F) << 4) | ((disp_val >> 8) & 0x0F)
                        b4 = disp_val & 0xFF
                        out.append(b1)
                        out.append(b2)
                        out.append(b3)
                        out.append(b4)

                    in_pos += best_len
                else:
                    out.append(data[in_pos])
                    in_pos += 1

            out[flag_pos] = flags

        while len(out) % 4 != 0:
            out.append(0)

        return bytes(out)
