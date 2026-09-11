"""
miorom.compression.aplib
~~~~~~~~~~~~~~~~~~~~~~~~
Pure-Python aPLib decompressor and compressor.
aPLib is a popular LZ-based compression library by Jørgen Ibsen widely used in
retro game translations (SNES, GBA, PS1) for its high compression ratio and tiny assembly decompressors.
"""

from __future__ import annotations

import struct
from binascii import crc32
from io import BytesIO
from typing import List, Optional

from miorom.core.schema import BinaryStruct, RawBytes, U32
from miorom.errors import CompressionError


class AP32HeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)
    header_size = U32()
    packed_size = U32()
    packed_crc = U32()
    orig_size = U32()
    orig_crc = U32()


class _BitWriter:
    def __init__(self):
        self.stream = bytearray()
        self.tag = 0
        self.bitcount = 0
        self.tag_pos = 0

    def init_tag(self):
        self.tag_pos = len(self.stream)
        self.stream.append(0)
        self.tag = 0
        self.bitcount = 0

    def put_bit(self, bit: int):
        if self.bitcount == 0:
            self.tag_pos = len(self.stream)
            self.stream.append(0)
            self.tag = 0
            self.bitcount = 8

        self.bitcount -= 1
        if bit:
            self.tag |= (1 << self.bitcount)
        self.stream[self.tag_pos] = self.tag

    def put_byte(self, b: int):
        self.stream.append(b & 0xFF)

    def put_gamma(self, val: int):
        # Determine bit length of val excluding leading 1
        bits = []
        temp = val
        while temp > 1:
            bits.append(temp & 1)
            temp >>= 1
        bits.reverse()

        for idx, bit in enumerate(bits):
            self.put_bit(bit)
            is_last = (idx == len(bits) - 1)
            self.put_bit(0 if is_last else 1)

    def get_bytes(self) -> bytes:
        return bytes(self.stream)


class APLib:
    """
    Pure Python aPLib decompressor and compressor.
    """

    MAGIC = b"AP32"

    def __init__(self, source: bytes, strict: bool = True):
        self.source = BytesIO(source)
        self.destination = bytearray()
        self.tag = 0
        self.bitcount = 0
        self.strict = bool(strict)

    def getbit(self) -> int:
        self.bitcount -= 1
        if self.bitcount < 0:
            byte = self.source.read(1)
            if not byte:
                return 0
            self.tag = byte[0]
            self.bitcount = 7

        bit = (self.tag >> 7) & 1
        self.tag = (self.tag << 1) & 0xFF
        return bit

    def getgamma(self) -> int:
        result = 1
        while True:
            result = (result << 1) + self.getbit()
            if not self.getbit():
                break
        return result

    def depack(self) -> bytes:
        r0 = -1
        lwm = 0
        done = False

        try:
            first = self.source.read(1)
            if not first:
                return bytes(self.destination)
            self.destination.extend(first)

            while not done:
                if self.getbit():
                    if self.getbit():
                        if self.getbit():
                            # Single-byte match (111)
                            offs = 0
                            for _ in range(4):
                                offs = (offs << 1) + self.getbit()

                            if offs:
                                self.destination.append(self.destination[-offs])
                            else:
                                self.destination.append(0)

                            lwm = 0
                        else:
                            # Short match (110)
                            b = self.source.read(1)
                            if not b:
                                break
                            offs = b[0]
                            length = 2 + (offs & 1)
                            offs >>= 1

                            if offs:
                                for _ in range(length):
                                    self.destination.append(self.destination[-offs])
                            else:
                                done = True

                            r0 = offs
                            lwm = 1
                    else:
                        # Block match (10)
                        offs = self.getgamma()

                        if lwm == 0 and offs == 2:
                            offs = r0
                            length = self.getgamma()
                            for _ in range(length):
                                self.destination.append(self.destination[-offs])
                        else:
                            if lwm == 0:
                                offs -= 3
                            else:
                                offs -= 2

                            offs <<= 8
                            b = self.source.read(1)
                            if not b:
                                break
                            offs += b[0]
                            length = self.getgamma()

                            if offs >= 32000:
                                length += 1
                            if offs >= 1280:
                                length += 1
                            if offs < 128:
                                length += 2

                            for _ in range(length):
                                self.destination.append(self.destination[-offs])

                            r0 = offs

                        lwm = 1
                else:
                    # Literal byte (0)
                    b = self.source.read(1)
                    if not b:
                        break
                    self.destination.extend(b)
                    lwm = 0

        except (TypeError, IndexError, struct.error) as exc:
            if self.strict:
                raise CompressionError(f"aPLib decompression error: {exc}")

        return bytes(self.destination)

    @classmethod
    def decompress(cls, data: bytes, strict: bool = False) -> bytes:
        """
        Decompresses aPLib compressed data (supports raw streams and AP32 container headers).
        """
        if not data:
            return b""

        packed_size = None
        orig_size = None
        orig_crc = None

        if data.startswith(cls.MAGIC) and len(data) >= 24:
            hdr = AP32HeaderStruct.from_bytes(data)
            header_size = hdr.header_size
            packed_size = hdr.packed_size
            orig_size = hdr.orig_size
            orig_crc = hdr.orig_crc
            data = data[header_size : header_size + packed_size]

        if strict and packed_size is not None and packed_size != len(data):
            raise CompressionError("aPLib packed size mismatch")

        result = cls(data, strict=strict).depack()

        if strict:
            if orig_size is not None and orig_size != len(result):
                raise CompressionError("aPLib unpacked size mismatch")
            if orig_crc is not None and orig_crc != (crc32(result) & 0xFFFFFFFF):
                raise CompressionError("aPLib unpacked CRC mismatch")

        return result

    @classmethod
    def compress(cls, data: bytes, with_header: bool = False) -> bytes:
        """
        Compresses data using aPLib format.
        """
        if not data:
            return b""

        writer = _BitWriter()
        # First byte verbatim
        writer.put_byte(data[0])

        pos = 1
        src_len = len(data)
        lwm = 0
        r0 = -1

        while pos < src_len:
            best_dist = 0
            best_len = 0

            # Check backreferences in sliding window (up to 32KB)
            win_start = max(0, pos - 32000)
            max_check = min(256, src_len - pos)

            if max_check >= 2:
                for cand_len in range(2, max_check + 1):
                    pat = data[pos : pos + cand_len]
                    found = data.rfind(pat, win_start, pos)
                    if found != -1:
                        best_dist = pos - found
                        best_len = cand_len
                    else:
                        break

            # Short match (length 2 or 3, dist < 128)
            if 2 <= best_len <= 3 and best_dist < 128:
                writer.put_bit(1)
                writer.put_bit(1)
                writer.put_bit(0)
                writer.put_byte((best_dist << 1) | (best_len - 2))
                pos += best_len
                r0 = best_dist
                lwm = 1
            # Block match (length >= 3)
            elif best_len >= 3:
                # Calculate length adjustment
                adj = 0
                if best_dist >= 32000:
                    adj += 1
                if best_dist >= 1280:
                    adj += 1
                if best_dist < 128:
                    adj += 2

                enc_len = best_len - adj
                if enc_len >= 2:
                    writer.put_bit(1)
                    writer.put_bit(0)
                    offs_hi = best_dist >> 8
                    gamma_offs = offs_hi + (2 if lwm else 3)
                    writer.put_gamma(gamma_offs)
                    writer.put_byte(best_dist & 0xFF)
                    writer.put_gamma(enc_len)
                    pos += best_len
                    r0 = best_dist
                    lwm = 1
                else:
                    # Emit literal
                    writer.put_bit(0)
                    writer.put_byte(data[pos])
                    pos += 1
                    lwm = 0
            else:
                # Literal byte
                writer.put_bit(0)
                writer.put_byte(data[pos])
                pos += 1
                lwm = 0

        # Emit EOF marker: 110 + byte 0x00
        writer.put_bit(1)
        writer.put_bit(1)
        writer.put_bit(0)
        writer.put_byte(0x00)

        raw_compressed = writer.get_bytes()

        if with_header:
            header = AP32HeaderStruct(
                magic=cls.MAGIC,
                header_size=24,
                packed_size=len(raw_compressed),
                packed_crc=crc32(raw_compressed) & 0xFFFFFFFF,
                orig_size=src_len,
                orig_crc=crc32(data) & 0xFFFFFFFF,
            )
            return header.to_bytes() + raw_compressed

        return raw_compressed
