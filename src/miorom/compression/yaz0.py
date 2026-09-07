import struct
from typing import Optional


class Yaz0:
    """
    Nintendo Yaz0 compression codec.
    Widely used across Nintendo 64, GameCube, Wii, and Switch games (e.g. Zelda, Mario).
    Header: 'Yaz0' (4 bytes), uncompressed size (4 bytes BE), 8 bytes reserved/padding.
    """

    MAGIC = b"Yaz0"

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        if len(data) < 16:
            raise ValueError("Data too short for Yaz0 header (minimum 16 bytes).")
        if data[:4] != cls.MAGIC:
            raise ValueError(f"Invalid Yaz0 magic: {data[:4]!r}")

        uncompressed_size = struct.unpack(">I", data[4:8])[0]
        output = bytearray()
        src_pos = 16
        src_len = len(data)

        valid_bits = 0
        code_byte = 0

        while len(output) < uncompressed_size and src_pos < src_len:
            if valid_bits == 0:
                code_byte = data[src_pos]
                src_pos += 1
                valid_bits = 8

            is_raw = (code_byte & 0x80) != 0
            code_byte = (code_byte << 1) & 0xFF
            valid_bits -= 1

            if is_raw:
                if src_pos >= src_len:
                    break
                output.append(data[src_pos])
                src_pos += 1
            else:
                if src_pos + 1 >= src_len:
                    break
                b1 = data[src_pos]
                b2 = data[src_pos + 1]
                src_pos += 2

                dist = ((b1 & 0x0F) << 8) | b2
                length_nibble = b1 >> 4

                if length_nibble == 0:
                    if src_pos >= src_len:
                        break
                    b3 = data[src_pos]
                    src_pos += 1
                    copy_len = b3 + 0x12
                else:
                    copy_len = length_nibble + 2

                copy_pos = len(output) - (dist + 1)
                if copy_pos < 0:
                    raise ValueError(f"Invalid Yaz0 back-reference distance: {dist + 1}")

                for _ in range(copy_len):
                    if len(output) >= uncompressed_size:
                        break
                    output.append(output[copy_pos])
                    copy_pos += 1

        return bytes(output)

    @classmethod
    def compress(cls, data: bytes, search_depth: int = 1024) -> bytes:
        """
        Compresses data into Yaz0 format.
        """
        data_len = len(data)
        out_header = bytearray(cls.MAGIC)
        out_header += struct.pack(">I", data_len)
        out_header += b"\x00" * 8  # 8 bytes reserved

        out_body = bytearray()
        src_pos = 0

        # Maximum lookback distance: 4096 (0x1000)
        # Maximum copy length: 0x111 (273 bytes)
        MAX_DIST = 4096
        MAX_LEN = 273

        while src_pos < data_len:
            code_bits = 0
            chunk = bytearray()

            for bit_i in range(8):
                if src_pos >= data_len:
                    break

                # Search best match
                max_back = min(src_pos, MAX_DIST)
                start_window = max(0, src_pos - search_depth)
                best_len = 0
                best_dist = 0

                # Simple greedy search
                cur_max_len = min(data_len - src_pos, MAX_LEN)
                if cur_max_len >= 3:
                    sub = data[src_pos : src_pos + 3]
                    # Find candidate positions
                    window_bytes = data[start_window:src_pos]
                    cand_idx = window_bytes.find(sub)
                    while cand_idx != -1:
                        match_pos = start_window + cand_idx
                        l = 3
                        while (
                            l < cur_max_len
                            and data[match_pos + l] == data[src_pos + l]
                        ):
                            l += 1
                        if l > best_len:
                            best_len = l
                            best_dist = src_pos - match_pos
                            if best_len == cur_max_len:
                                break
                        cand_idx = window_bytes.find(sub, cand_idx + 1)

                if best_len >= 3:
                    # Compressed backref
                    # Flag bit = 0
                    dist_code = best_dist - 1
                    if best_len < 18:
                        b1 = ((best_len - 2) << 4) | ((dist_code >> 8) & 0x0F)
                        b2 = dist_code & 0xFF
                        chunk.extend([b1, b2])
                    else:
                        b1 = (dist_code >> 8) & 0x0F
                        b2 = dist_code & 0xFF
                        b3 = (best_len - 0x12) & 0xFF
                        chunk.extend([b1, b2, b3])
                    src_pos += best_len
                else:
                    # Literal
                    code_bits |= 1 << (7 - bit_i)
                    chunk.append(data[src_pos])
                    src_pos += 1

            out_body.append(code_bits)
            out_body.extend(chunk)

        return bytes(out_header + out_body)
