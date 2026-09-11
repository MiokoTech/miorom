"""
miorom.compression.enigma
~~~~~~~~~~~~~~~~~~~~~~~~~
Sega Mega Drive / Genesis Enigma compression codec.
Run-length and incremental encoding for Sega Genesis VDP plane tilemaps
(e.g., Sonic the Hedgehog series, Golden Axe, Knuckles' Chaotix).

Pure Python implementation using MioROM binary primitives.
"""

from __future__ import annotations

from collections import Counter
from typing import List, Tuple
from miorom.core.schema import BinaryStruct, U8, U16
from miorom.errors import CompressionError


class EnigmaHeaderStruct(BinaryStruct):
    _endian = ">"
    inline_copy_bits = U8()
    render_flags_mask = U8()
    incremental_copy_word = U16()
    literal_copy_word = U16()


class EnigmaCodec:
    """
    Sega Enigma tilemap compression and decompression codec.
    """

    @classmethod
    def decompress(cls, data: bytes, starting_art_tile: int = 0) -> bytes:
        """
        Decompresses an Enigma-compressed byte stream into uncompressed 16-bit VDP plane words.
        """
        if len(data) < EnigmaHeaderStruct.sizeof():
            raise CompressionError(
                f"Data too short for Enigma header: {len(data)} bytes "
                f"(expected at least {EnigmaHeaderStruct.sizeof()})."
            )

        header = EnigmaHeaderStruct.from_bytes(data, offset=0)
        inline_copy_bits = header.inline_copy_bits
        render_flags_mask = header.render_flags_mask
        inc_copy_word = header.incremental_copy_word
        lit_copy_word = header.literal_copy_word

        # Bit positions in render_flags_mask from bit 4 down to 0
        flag_positions = [k for k in range(4, -1, -1) if (render_flags_mask & (1 << k))]

        bit_pos = EnigmaHeaderStruct.sizeof() * 8
        total_bits = len(data) * 8

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

        def read_inline_value() -> int:
            word = 0
            for k in flag_positions:
                if pop_bit():
                    word |= 1 << (11 + k)
            tile = pop_bits(inline_copy_bits)
            return word | tile

        out_words: List[int] = []

        while True:
            first_bit = pop_bit()
            if first_bit == 0:
                type_bit = pop_bit()
                count = pop_bits(4) + 1
                if type_bit == 0:
                    # Type 00: Incremental copy word
                    val = inc_copy_word
                    for _ in range(count):
                        out_words.append((val + starting_art_tile) & 0xFFFF)
                        val = (val + 1) & 0xFFFF
                else:
                    # Type 01: Literal copy word
                    for _ in range(count):
                        out_words.append((lit_copy_word + starting_art_tile) & 0xFFFF)
            else:
                t1 = pop_bit()
                t2 = pop_bit()
                type_code = (t1 << 1) | t2
                count_raw = pop_bits(4)
                if type_code == 0b11:
                    # Type 111: Terminator or Individual inline values
                    if count_raw == 0x0F:
                        # Terminator reached
                        break
                    count = count_raw + 1
                    for _ in range(count):
                        val = read_inline_value()
                        out_words.append((val + starting_art_tile) & 0xFFFF)
                else:
                    count = count_raw + 1
                    val = read_inline_value()
                    if type_code == 0b00:
                        # Type 100: Static inline
                        for _ in range(count):
                            out_words.append((val + starting_art_tile) & 0xFFFF)
                    elif type_code == 0b01:
                        # Type 101: Incremental inline
                        for _ in range(count):
                            out_words.append((val + starting_art_tile) & 0xFFFF)
                            val = (val + 1) & 0xFFFF
                    elif type_code == 0b10:
                        # Type 110: Decremental inline
                        for _ in range(count):
                            out_words.append((val + starting_art_tile) & 0xFFFF)
                            val = (val - 1) & 0xFFFF

        out = bytearray()
        for w in out_words:
            out.extend([(w >> 8) & 0xFF, w & 0xFF])
        return bytes(out)

    @classmethod
    def compress(cls, data: bytes, starting_art_tile: int = 0) -> bytes:
        """
        Compresses 16-bit Genesis VDP plane tilemap data into Enigma format.
        """
        if len(data) % 2 != 0:
            raise CompressionError("Enigma input data length must be a multiple of 2 bytes.")

        words = [
            (((data[i] << 8) | data[i + 1]) - starting_art_tile) & 0xFFFF
            for i in range(0, len(data), 2)
        ]

        if not words:
            # Minimal header + terminator
            hdr = EnigmaHeaderStruct(
                inline_copy_bits=8,
                render_flags_mask=0,
                incremental_copy_word=0,
                literal_copy_word=0,
            ).to_bytes()
            return hdr + bytes([0xFF])

        # Analyze flags and tile indices
        flags_mask = 0
        max_tile = 0
        for w in words:
            flags_mask |= (w >> 11) & 0x1F
            tile_idx = w & 0x07FF
            if tile_idx > max_tile:
                max_tile = tile_idx

        render_flags_mask = flags_mask
        inline_copy_bits = max(1, max_tile.bit_length())

        # Determine most common words for incremental and literal copy
        lit_counter = Counter(words)
        literal_copy_word = lit_counter.most_common(1)[0][0]

        # Scan for best starting incremental copy word
        inc_counter: Counter[int] = Counter()
        for i in range(len(words) - 1):
            if words[i + 1] == (words[i] + 1) & 0xFFFF:
                inc_counter[words[i]] += 1
        incremental_copy_word = (
            inc_counter.most_common(1)[0][0] if inc_counter else 0
        )

        flag_positions = [k for k in range(4, -1, -1) if (render_flags_mask & (1 << k))]

        bits: List[int] = []

        def push_bits(val: int, n: int) -> None:
            for bit_i in range(n - 1, -1, -1):
                bits.append((val >> bit_i) & 1)

        def push_inline_value(w: int) -> None:
            for k in flag_positions:
                bit_val = (w >> (11 + k)) & 1
                bits.append(bit_val)
            push_bits(w & ((1 << inline_copy_bits) - 1), inline_copy_bits)

        pos = 0
        num_words = len(words)

        while pos < num_words:
            # 1. Test Incremental Copy Word match
            inc_match = 0
            while (
                pos + inc_match < num_words
                and inc_match < 16
                and words[pos + inc_match] == (incremental_copy_word + inc_match) & 0xFFFF
            ):
                inc_match += 1

            # 2. Test Literal Copy Word match
            lit_match = 0
            while (
                pos + lit_match < num_words
                and lit_match < 16
                and words[pos + lit_match] == literal_copy_word
            ):
                lit_match += 1

            # 3. Test Inline Incremental run
            inline_inc = 1
            while (
                pos + inline_inc < num_words
                and inline_inc < 16
                and words[pos + inline_inc] == (words[pos] + inline_inc) & 0xFFFF
            ):
                inline_inc += 1

            # 4. Test Inline Decremental run
            inline_dec = 1
            while (
                pos + inline_dec < num_words
                and inline_dec < 16
                and words[pos + inline_dec] == (words[pos] - inline_dec) & 0xFFFF
            ):
                inline_dec += 1

            # 5. Test Inline Static run
            inline_stat = 1
            while (
                pos + inline_stat < num_words
                and inline_stat < 16
                and words[pos + inline_stat] == words[pos]
            ):
                inline_stat += 1

            # Select most efficient packet
            if inc_match >= 2 and inc_match >= lit_match and inc_match >= inline_inc:
                # Type 00: Incremental copy word (6 bits)
                push_bits(0b00, 2)
                push_bits(inc_match - 1, 4)
                pos += inc_match
            elif lit_match >= 2 and lit_match >= inline_stat:
                # Type 01: Literal copy word (6 bits)
                push_bits(0b01, 2)
                push_bits(lit_match - 1, 4)
                pos += lit_match
            elif inline_stat >= 2 and inline_stat >= inline_inc and inline_stat >= inline_dec:
                # Type 100: Inline Static (7 bits + inline value)
                push_bits(0b100, 3)
                push_bits(inline_stat - 1, 4)
                push_inline_value(words[pos])
                pos += inline_stat
            elif inline_inc >= 2 and inline_inc >= inline_dec:
                # Type 101: Inline Incremental (7 bits + inline value)
                push_bits(0b101, 3)
                push_bits(inline_inc - 1, 4)
                push_inline_value(words[pos])
                pos += inline_inc
            elif inline_dec >= 2:
                # Type 110: Inline Decremental (7 bits + inline value)
                push_bits(0b110, 3)
                push_bits(inline_dec - 1, 4)
                push_inline_value(words[pos])
                pos += inline_dec
            else:
                # Type 111: Individual inline value (7 bits + 1 inline value)
                push_bits(0b111, 3)
                push_bits(0, 4)  # count = 1
                push_inline_value(words[pos])
                pos += 1

        # Emit Terminator: Type 111, count 0x0F
        push_bits(0b111, 3)
        push_bits(0x0F, 4)

        # Build final binary output
        hdr = EnigmaHeaderStruct(
            inline_copy_bits=inline_copy_bits,
            render_flags_mask=render_flags_mask,
            incremental_copy_word=incremental_copy_word,
            literal_copy_word=literal_copy_word,
        ).to_bytes()

        out_body = bytearray()
        byte_buf = 0
        bits_in_buf = 0
        for b in bits:
            byte_buf = (byte_buf << 1) | b
            bits_in_buf += 1
            if bits_in_buf == 8:
                out_body.append(byte_buf)
                byte_buf = 0
                bits_in_buf = 0

        if bits_in_buf > 0:
            byte_buf <<= (8 - bits_in_buf)
            out_body.append(byte_buf)

        return hdr + bytes(out_body)


Enigma = EnigmaCodec
