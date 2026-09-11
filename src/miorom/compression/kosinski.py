"""
miorom.compression.kosinski
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Sega Mega Drive / Genesis Kosinski compression codec.
Widely used across Sega first-party games (e.g. Sonic the Hedgehog series,
Phantasy Star IV, Shinobi III, Streets of Rage).

Pure Python implementation using MioROM binary primitives.
"""

from __future__ import annotations

from typing import Optional
from miorom.errors import CompressionError


class KosinskiCodec:
    """
    Sega Kosinski LZSS compression and decompression codec.
    """

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """
        Decompresses Kosinski-compressed byte stream into uncompressed data.
        """
        if len(data) < 2:
            raise CompressionError("Data too short for Kosinski descriptor.")

        pos = 0
        data_len = len(data)

        def read_byte() -> int:
            nonlocal pos
            if pos >= data_len:
                raise CompressionError("Unexpected end of data while reading byte.")
            b = data[pos]
            pos += 1
            return b

        def get_descriptor() -> int:
            low = read_byte()
            high = read_byte()
            return (high << 8) | low

        descriptor = get_descriptor()
        desc_bits_left = 16

        def pop_descriptor() -> int:
            nonlocal descriptor, desc_bits_left
            bit = descriptor & 1
            descriptor >>= 1
            desc_bits_left -= 1
            if desc_bits_left == 0:
                if pos + 1 < data_len:
                    descriptor = get_descriptor()
                    desc_bits_left = 16
                else:
                    descriptor = 0
                    desc_bits_left = 0
            return bit

        output = bytearray()

        while True:
            if pop_descriptor():
                # Literal byte
                output.append(read_byte())
            else:
                if pop_descriptor():
                    # Full match or extended match or terminator
                    low = read_byte()
                    high = read_byte()
                    distance = ((high & 0xF8) << 5) | low
                    distance = (distance ^ 0x1FFF) + 1  # 2's complement 13-bit negative to positive
                    count = high & 7
                    if count != 0:
                        count += 2
                    else:
                        extra = read_byte()
                        count = extra + 1
                        if count == 1:
                            # Terminator reached
                            break
                        elif count == 2:
                            # 0xA000 boundary flag
                            continue
                else:
                    # Inline short match
                    count = 2
                    if pop_descriptor():
                        count += 2
                    if pop_descriptor():
                        count += 1
                    dist_byte = read_byte()
                    distance = (dist_byte ^ 0xFF) + 1

                copy_pos = len(output) - distance
                if copy_pos < 0:
                    raise CompressionError(
                        f"Invalid backreference distance: {distance} exceeds current output length {len(output)}."
                    )

                for _ in range(count):
                    output.append(output[copy_pos])
                    copy_pos += 1

        return bytes(output)

    @classmethod
    def compress(cls, data: bytes, search_depth: int = 2048) -> bytes:
        """
        Compresses uncompressed data into Sega Kosinski format.
        """
        out = bytearray()
        desc_pos = 0
        out.extend(b"\x00\x00")
        desc_bits: list[int] = []

        def push_bit(b: int) -> None:
            nonlocal desc_pos
            desc_bits.append(b & 1)
            if len(desc_bits) == 16:
                val = sum(bit << i for i, bit in enumerate(desc_bits))
                out[desc_pos] = val & 0xFF
                out[desc_pos + 1] = (val >> 8) & 0xFF
                desc_pos = len(out)
                out.extend(b"\x00\x00")
                desc_bits.clear()

        def push_bytes(bs: bytes) -> None:
            out.extend(bs)

        pos = 0
        data_len = len(data)

        while pos < data_len:
            best_len = 0
            best_dist = 0
            max_dist = min(pos, min(search_depth, 8192))
            start_w = max(0, pos - max_dist)
            window = data[start_w:pos]

            max_match = min(data_len - pos, 256)
            if max_match >= 2:
                sub2 = data[pos : pos + 2]
                idx = window.rfind(sub2)
                while idx != -1:
                    match_pos = start_w + idx
                    l = 2
                    while l < max_match and data[match_pos + l] == data[pos + l]:
                        l += 1
                    dist = pos - match_pos
                    if l > best_len or (l == best_len and dist < best_dist):
                        best_len = l
                        best_dist = dist
                    if best_len >= 256:
                        break
                    idx = window.rfind(sub2, 0, idx)

            # Match selection
            if best_len >= 2 and best_dist <= 256 and best_len <= 5:
                # Inline match
                push_bit(0)
                push_bit(0)
                push_bit(1 if best_len in (4, 5) else 0)
                push_bit(1 if best_len in (3, 5) else 0)
                push_bytes(bytes([(256 - best_dist) & 0xFF]))
                pos += best_len
            elif best_len in range(3, 10) and best_dist <= 8192:
                # Full match
                push_bit(0)
                push_bit(1)
                enc_dist = (8192 - best_dist) & 0x1FFF
                count = (best_len - 2) & 7
                low = enc_dist & 0xFF
                high = ((enc_dist >> 5) & 0xF8) | count
                push_bytes(bytes([low, high]))
                pos += best_len
            elif best_len >= 3 and best_dist <= 8192:
                # Extended match
                actual_len = min(best_len, 256)
                push_bit(0)
                push_bit(1)
                enc_dist = (8192 - best_dist) & 0x1FFF
                low = enc_dist & 0xFF
                high = ((enc_dist >> 5) & 0xF8) | 0
                extra = (actual_len - 1) & 0xFF
                push_bytes(bytes([low, high, extra]))
                pos += actual_len
            else:
                # Literal byte
                push_bit(1)
                push_bytes(bytes([data[pos]]))
                pos += 1

        # Emit Terminator
        push_bit(0)
        push_bit(1)
        push_bytes(b"\x00\xf0\x00")

        # Finalize descriptors
        if desc_bits:
            while len(desc_bits) < 16:
                desc_bits.append(0)
            val = sum(bit << i for i, bit in enumerate(desc_bits))
            out[desc_pos] = val & 0xFF
        # desc_pos holds empty descriptor on non-bit alignment
        return bytes(out)


Kosinski = KosinskiCodec
