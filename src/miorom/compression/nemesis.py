"""
miorom.compression.nemesis
~~~~~~~~~~~~~~~~~~~~~~~~~~
Sega Mega Drive / Genesis Nemesis compression codec.
Entropy and run-length based tile graphic compression widely used across Sega games.

Pure Python implementation using MioROM binary primitives.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Tuple
from miorom.errors import CompressionError


class NemesisCodec:
    """
    Sega Nemesis graphic tile compression and decompression codec.
    """

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """
        Decompresses Nemesis-compressed byte stream into uncompressed 4bpp tile bytes.
        """
        if len(data) < 2:
            raise CompressionError("Data too short for Nemesis header (minimum 2 bytes).")

        header_word = (data[0] << 8) | data[1]
        xor_mode = bool(header_word & 0x8000)
        total_tiles = header_word & 0x7FFF
        total_nybbles = total_tiles * 64

        pos = 2
        data_len = len(data)

        # 1. Parse Code Table
        code_table: Dict[Tuple[int, int], Tuple[int, int]] = {}
        current_nybble = 0

        while pos < data_len:
            b = data[pos]
            pos += 1
            if b == 0xFF:
                break
            if b & 0x80:
                current_nybble = b & 0x0F
            else:
                if pos >= data_len:
                    raise CompressionError("Unexpected end of data in Nemesis code table.")
                run_length = ((b >> 4) & 7) + 1
                code_bits = b & 0x0F
                code = data[pos]
                pos += 1
                code_table[(code, code_bits)] = (current_nybble, run_length)

        # 2. Bitstream Decoding
        bit_pos = pos * 8
        total_bits = data_len * 8

        def pop_bit() -> int:
            nonlocal bit_pos
            if bit_pos >= total_bits:
                return 0
            byte_idx = bit_pos >> 3
            bit_idx = 7 - (bit_pos & 7)
            bit_pos += 1
            return (data[byte_idx] >> bit_idx) & 1

        def pop_bits(n: int) -> int:
            val = 0
            for _ in range(n):
                val = (val << 1) | pop_bit()
            return val

        output = bytearray()
        nybbles_done = 0
        cur_32 = 0
        prev_32 = 0

        def output_nybble(n: int) -> None:
            nonlocal nybbles_done, cur_32, prev_32
            cur_32 = ((cur_32 << 4) | (n & 0x0F)) & 0xFFFFFFFF
            nybbles_done += 1
            if (nybbles_done & 7) == 0:
                final_32 = cur_32 ^ prev_32 if xor_mode else cur_32
                output.extend([
                    (final_32 >> 24) & 0xFF,
                    (final_32 >> 16) & 0xFF,
                    (final_32 >> 8) & 0xFF,
                    final_32 & 0xFF,
                ])
                prev_32 = final_32
                cur_32 = 0

        while nybbles_done < total_nybbles:
            code = 0
            code_bits = 0
            matched = False
            while code_bits < 8:
                code = (code << 1) | pop_bit()
                code_bits += 1
                if code_bits == 6 and code == 0x3F:
                    # Inline uncompressed run
                    run_length = pop_bits(3) + 1
                    nybble = pop_bits(4)
                    for _ in range(run_length):
                        output_nybble(nybble)
                    matched = True
                    break
                elif (code, code_bits) in code_table:
                    nybble, run_length = code_table[(code, code_bits)]
                    for _ in range(run_length):
                        output_nybble(nybble)
                    matched = True
                    break

            if not matched:
                raise CompressionError(
                    f"Invalid Nemesis code encountered: 0x{code:X} ({code_bits} bits) "
                    f"at nybble {nybbles_done}/{total_nybbles}."
                )

        return bytes(output)

    @classmethod
    def compress(cls, data: bytes, xor_mode: bool = False) -> bytes:
        """
        Compresses 4bpp Genesis tile graphics into Sega Nemesis format.
        """
        # Align to 32 bytes (1 tile = 8x8 pixels at 4bpp = 32 bytes)
        if len(data) % 32 != 0:
            pad = 32 - (len(data) % 32)
            data = data + b"\x00" * pad

        total_tiles = len(data) // 32
        if total_tiles > 0x7FFF:
            raise CompressionError(f"Data exceeds maximum Nemesis tile limit (0x7FFF tiles).")

        header_word = (0x8000 if xor_mode else 0) | (total_tiles & 0x7FFF)

        # 1. XOR Mode Preprocessing
        if xor_mode:
            transformed = bytearray()
            prev_32 = 0
            for i in range(0, len(data), 4):
                cur_32 = (data[i] << 24) | (data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3]
                xor_32 = cur_32 ^ prev_32
                transformed.extend([
                    (xor_32 >> 24) & 0xFF,
                    (xor_32 >> 16) & 0xFF,
                    (xor_32 >> 8) & 0xFF,
                    xor_32 & 0xFF,
                ])
                prev_32 = cur_32
            data_to_encode = bytes(transformed)
        else:
            data_to_encode = data

        # 2. Extract nybbles
        nybbles: List[int] = []
        for b in data_to_encode:
            nybbles.append((b >> 4) & 0x0F)
            nybbles.append(b & 0x0F)

        # 3. Group into runs (max length 8)
        runs: List[Tuple[int, int]] = []
        i = 0
        total_n = len(nybbles)
        while i < total_n:
            val = nybbles[i]
            l = 1
            while i + l < total_n and nybbles[i + l] == val and l < 8:
                l += 1
            runs.append((val, l))
            i += l

        # Assign prefix codes
        counts = Counter(runs)

        candidate_codes = [
            (0b00, 2),
            (0b01, 2),
            (0b10, 2),
            (0b110, 3),
            (0b1110, 4),
            (0b11110, 5),
            (0b1111100, 7),
            (0b1111101, 7),
        ]

        code_table: Dict[Tuple[int, int], Tuple[int, int]] = {}
        nybble_to_coded_runs: Dict[int, List[Tuple[int, int, int]]] = {}

        for (run_val, run_len), freq in counts.most_common(len(candidate_codes)):
            code, code_len = candidate_codes[len(code_table)]
            # Assign if savings outweigh the 16-bit code table header overhead
            if freq * (13 - code_len) > 16:
                code_table[(run_val, run_len)] = (code, code_len)
                nybble_to_coded_runs.setdefault(run_val, []).append((run_len, code, code_len))

        # 5. Build Output Stream
        out = bytearray()
        # Header (2 bytes BE)
        out.extend([(header_word >> 8) & 0xFF, header_word & 0xFF])

        # Code Table
        for nybble, run_list in sorted(nybble_to_coded_runs.items()):
            out.append(0x80 | nybble)
            for run_len, code, code_len in run_list:
                out.append(((run_len - 1) << 4) | (code_len & 0x0F))
                out.append(code)
        out.append(0xFF)

        # Bitstream
        bits: List[int] = []

        def push_bits(val: int, n: int) -> None:
            for bit_i in range(n - 1, -1, -1):
                bits.append((val >> bit_i) & 1)

        for val, l in runs:
            if (val, l) in code_table:
                code, code_len = code_table[(val, l)]
                push_bits(code, code_len)
            else:
                # Inline marker
                push_bits(0x3F, 6)
                push_bits(l - 1, 3)
                push_bits(val, 4)

        # Pack bits to bytes (MSB first)
        byte_buf = 0
        bits_in_buf = 0
        for b in bits:
            byte_buf = (byte_buf << 1) | b
            bits_in_buf += 1
            if bits_in_buf == 8:
                out.append(byte_buf)
                byte_buf = 0
                bits_in_buf = 0

        if bits_in_buf > 0:
            byte_buf <<= (8 - bits_in_buf)
            out.append(byte_buf)

        return bytes(out)


Nemesis = NemesisCodec
