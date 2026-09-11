from miorom.errors import CompressionError
from miorom.core.schema import BinaryStruct, U32


class RLE:
    """
    Nintendo standard Run-Length Encoding (Type 0x30) compression and decompression.
    Used in GBA, NDS, and Wii graphics and data banks.
    """

    MAGIC = 0x30
    END_OF_STREAM = 0xFF


    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """Decompress Nintendo RLE (Type 0x30) data."""
        if len(data) < 4:
            raise CompressionError("Data too short for RLE header")

        magic = data[0]
        if magic != cls.MAGIC:
            raise CompressionError(f"Invalid RLE magic byte: expected 0x30, got {hex(magic)}")

        uncompressed_size = data[1] | (data[2] << 8) | (data[3] << 16)
        in_pos = 4

        if uncompressed_size == 0:
            if len(data) == 4:
                return b""
            if len(data) < 8:
                raise CompressionError("Data too short for extended RLE header")
            uncompressed_size = RLEExtendedSizeStruct.from_bytes(data, offset=4).uncompressed_size
            in_pos = 8

        out = bytearray()
        data_len = len(data)

        while len(out) < uncompressed_size and in_pos < data_len:
            flag = data[in_pos]
            in_pos += 1

            is_compressed = bool(flag & 0x80)
            length = (flag & 0x7F)

            if is_compressed:
                length += 3
                if in_pos >= data_len:
                    break
                val = data[in_pos]
                in_pos += 1
                for _ in range(length):
                    out.append(val)
                    if len(out) >= uncompressed_size:
                        break
            else:
                length += 1
                for _ in range(length):
                    if in_pos >= data_len:
                        break
                    out.append(data[in_pos])
                    in_pos += 1
                    if len(out) >= uncompressed_size:
                        break

        if len(out) < uncompressed_size:
            raise CompressionError(
                f"RLE decompression truncated: expected {uncompressed_size} bytes, got {len(out)} bytes"
            )

        return bytes(out)

    @classmethod
    def compress(cls, data: bytes, include_end_marker: bool = False) -> bytes:
        """Compress data using Nintendo RLE (Type 0x30) format."""
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
            out.extend(RLEExtendedSizeStruct(uncompressed_size=uncompressed_size).to_bytes())

        in_pos = 0
        data_len = len(data)

        while in_pos < data_len:
            # Check for repeated bytes
            b = data[in_pos]
            run_len = 1
            while in_pos + run_len < data_len and data[in_pos + run_len] == b and run_len < (0x7F + 3):
                run_len += 1

            if run_len >= 3:
                # Compressed run
                flag = 0x80 | (run_len - 3)
                out.append(flag)
                out.append(b)
                in_pos += run_len
            else:
                # Literal run
                lit_run = bytearray()
                while in_pos < data_len and len(lit_run) < (0x7F + 1):
                    # Check if next 3 bytes are identical (start of compressed run)
                    if in_pos + 2 < data_len and data[in_pos] == data[in_pos+1] == data[in_pos+2]:
                        break
                    lit_run.append(data[in_pos])
                    in_pos += 1

                if lit_run:
                    flag = len(lit_run) - 1
                    out.append(flag)
                    out.extend(lit_run)

        while len(out) % 4 != 0:
            out.append(0)

        return bytes(out)
