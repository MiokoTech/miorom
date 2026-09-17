"""
miorom.compression.blz
~~~~~~~~~~~~~~~~~~~~~~
Nintendo DS Bottom LZ (BLZ) / Backwards LZ77 Compression and Decompression Engine.

BLZ is an in-place backwards LZ77 compression scheme designed by Nintendo for the
Nintendo DS (and Game Boy Advance). It is the standard compression format used for
ARM9 executables (arm9.bin) and overlay binaries (y9.bin/y7.bin).

Unlike BIOS-level LZ10/LZ11, BLZ stores its metadata trailer at the end of the file
and decompresses backward from the end of the loaded RAM buffer, preventing the
unpacked data from overwriting compressed stream bytes before they are read.

Pure Python implementation adhering strictly to miorom.core.schema declarative models
and zero external runtime dependencies.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Union

from miorom.core.checksum import RetroChecksum
from miorom.core.schema import U32, BinaryStruct
from miorom.errors import CompressionError


class BLZTrailerStruct(BinaryStruct):
    """
    8-byte metadata trailer situated at the very end of a BLZ-compressed file.

    enc_and_hdr:
        Bits 0..23 (24 bits): Encoded payload length + trailer header size (enc_len + hdr_len).
        Bits 24..31 (8 bits): Trailer header size in bytes (hdr_len), typically 8..11 (0x08..0x0B).
    inc_len_hdr:
        Difference in uncompressed vs compressed payload length minus header size
        ((raw_len - dec_len - enc_len) - hdr_len), or 0 if uncompressed/raw.
    """
    _endian = "<"
    enc_and_hdr = U32()
    inc_len_hdr = U32()


class BLZ:
    """
    Nintendo DS Bottom LZ (BLZ / Backwards LZ77) compressor and decompressor.
    Compatible with CUE's blz utility and Nintendo DS SDK conventions.
    """

    BLZ_THRESHOLD = 2   # Minimum match length is 3 (THRESHOLD + 1)
    BLZ_F = 18          # Maximum match length ((1 << 4) + THRESHOLD = 18)
    BLZ_N = 4098        # Maximum displacement window ((1 << 12) + 2 = 4098)
    MIN_DISP = 3        # Minimum displacement distance

    @classmethod
    def is_compressed(cls, data: Union[bytes, bytearray]) -> bool:
        """
        Determines whether the provided binary data has a valid BLZ compression trailer.

        Args:
            data: Raw binary byte sequence.

        Returns:
            True if data contains a valid BLZ trailer and plausible dimensions, False otherwise.
        """
        if len(data) < 8:
            return False

        try:
            trailer = BLZTrailerStruct.from_bytes(data, offset=len(data) - 8)
            inc_len = trailer.inc_len_hdr
            if inc_len == 0:
                return False

            hdr_len = (trailer.enc_and_hdr >> 24) & 0xFF
            if hdr_len < 0x08 or hdr_len > 0x0B:
                return False

            enc_len = trailer.enc_and_hdr & 0x00FFFFFF
            if enc_len <= hdr_len or enc_len > len(data):
                return False

            dec_len = len(data) - enc_len
            raw_len = dec_len + enc_len + inc_len
            if raw_len > 0x00FFFFFF:  # 16 MB limit
                return False

            return True
        except Exception:
            return False

    @classmethod
    def decompress(cls, data: Union[bytes, bytearray]) -> bytes:
        """
        Decompresses a BLZ-compressed byte sequence.

        Args:
            data: BLZ-encoded binary stream with an 8..11 byte trailer at its end.

        Returns:
            Decompressed bytes.

        Raises:
            CompressionError: If the trailer is malformed or decompression fails.
        """
        if len(data) < 8:
            if data in (b"", b"\x00\x00\x00\x00"):
                return b""
            raise CompressionError("Data too short for BLZ trailer (minimum 8 bytes required).")

        trailer = BLZTrailerStruct.from_bytes(data, offset=len(data) - 8)
        inc_len = trailer.inc_len_hdr

        # If inc_len is 0, the stream is uncompressed raw bytes with 4 zero trailer bytes
        if inc_len == 0:
            if len(data) >= 4 and data.endswith(b"\x00\x00\x00\x00"):
                return bytes(data[:-4])
            return bytes(data)

        hdr_len = (trailer.enc_and_hdr >> 24) & 0xFF
        if hdr_len < 0x08 or hdr_len > 0x0B:
            raise CompressionError(
                f"Invalid BLZ header length: 0x{hdr_len:02X} (expected 0x08..0x0B)."
            )

        enc_len = trailer.enc_and_hdr & 0x00FFFFFF
        if enc_len > len(data):
            raise CompressionError(
                f"Invalid BLZ encoded length: {enc_len} exceeds total buffer length {len(data)}."
            )
        if enc_len <= hdr_len:
            raise CompressionError(
                f"Invalid BLZ encoded length: {enc_len} <= header length {hdr_len}."
            )

        dec_len = len(data) - enc_len
        pak_len = enc_len - hdr_len
        raw_len = dec_len + enc_len + inc_len

        if raw_len > 0x00FFFFFF:
            raise CompressionError(f"Corrupted BLZ decoded length: {raw_len} exceeds 16MB.")

        # 1. Uncompressed prefix (e.g. ARM9 secure area / prefix code)
        raw_buf = bytearray(raw_len)
        raw_buf[:dec_len] = data[:dec_len]

        # 2. Invert compressed payload for sequential forward traversal
        pak_buf = bytearray(data[dec_len : dec_len + pak_len])
        pak_buf.reverse()

        # 3. Backwards LZ77 decode loop
        pak_idx = 0
        raw_idx = dec_len
        pak_end = len(pak_buf)
        raw_end = raw_len

        flags = 0
        mask = 0

        while raw_idx < raw_end:
            mask >>= 1
            if mask == 0:
                if pak_idx >= pak_end:
                    break
                flags = pak_buf[pak_idx]
                pak_idx += 1
                mask = 0x80

            if (flags & mask) == 0:
                # Literal uncompressed byte
                if pak_idx >= pak_end:
                    break
                raw_buf[raw_idx] = pak_buf[pak_idx]
                pak_idx += 1
                raw_idx += 1
            else:
                # Compressed token: 2 bytes (length in high 4 bits, displacement in low 12 bits)
                if pak_idx + 1 >= pak_end:
                    break
                b1 = pak_buf[pak_idx]
                b2 = pak_buf[pak_idx + 1]
                pak_idx += 2

                pos_val = (b1 << 8) | b2
                match_len = (pos_val >> 12) + (cls.BLZ_THRESHOLD + 1)
                match_pos = (pos_val & 0x0FFF) + cls.MIN_DISP

                if raw_idx + match_len > raw_end:
                    match_len = raw_end - raw_idx

                for _ in range(match_len):
                    raw_buf[raw_idx] = raw_buf[raw_idx - match_pos]
                    raw_idx += 1

        # 4. Invert decoded portion to restore natural big/little endian order
        decoded_slice = raw_buf[dec_len:raw_len]
        decoded_slice.reverse()
        raw_buf[dec_len:raw_len] = decoded_slice

        return bytes(raw_buf[:raw_idx])

    @classmethod
    def compress(
        cls,
        data: Union[bytes, bytearray],
        is_arm9: bool = False,
        mode: str = "normal",
    ) -> bytes:
        """
        Compresses binary data using the Nintendo DS BLZ algorithm.

        Args:
            data: Raw uncompressed bytes to encode.
            is_arm9: If True, preserves the 16KB (0x4000) Secure Area uncompressed prefix,
                     checks/fixes the 2KB Secure Area CRC16 at offset 0x0E if Secure Area is valid.
            mode: 'normal' (fast window hash search) or 'best' (deeper search chain).

        Returns:
            BLZ compressed binary stream with trailing alignment bytes and BLZTrailerStruct.
        """
        raw_len = len(data)
        if raw_len == 0:
            return b"\x00\x00\x00\x00"

        raw_buf = bytearray(data)
        raw_new = raw_len

        # ARM9 Secure Area preservation & CRC validation
        if is_arm9 and raw_len >= 0x4000:
            # Check for Nintendo DS decrypted secure area signature (0xE7FFDEFF 0xE7FFDEFF 0xE7FFDEFF 0xDEFF)
            if (
                raw_buf[0:4] == b"\xff\xde\xff\xe7"
                and raw_buf[4:8] == b"\xff\xde\xff\xe7"
                and raw_buf[8:12] == b"\xff\xde\xff\xe7"
                and raw_buf[12:14] == b"\xff\xde"
                and raw_buf[0x7FE:0x800] == b"\x00\x00"
            ):
                # Recalculate 2KB Secure Area CRC16 (bytes 0x10..0x800)
                sec_crc = RetroChecksum.crc16_modbus(raw_buf[0x10:0x800])
                raw_buf[0x0E] = sec_crc & 0xFF
                raw_buf[0x0F] = (sec_crc >> 8) & 0xFF
                # Leave first 16KB uncompressed
                raw_new -= 0x4000

        # Invert buffer for backwards scanning
        raw_buf.reverse()

        max_chain = 128 if mode == "best" else 32
        table = defaultdict(list)

        pak_buffer = bytearray()
        flag_idx = -1
        mask = 0

        pak_tmp = 0
        raw_tmp = raw_len

        raw_idx = 0
        while raw_idx < raw_new:
            mask >>= 1
            if mask == 0:
                flag_idx = len(pak_buffer)
                pak_buffer.append(0)
                mask = 0x80

            len_best = cls.BLZ_THRESHOLD
            pos_best = 0

            # Find matching sequence via prefix hash
            if raw_idx + 3 <= raw_new:
                seq = bytes(raw_buf[raw_idx : raw_idx + 3])
                chain = table[seq]
                checked = 0
                for prev_idx in reversed(chain):
                    disp = raw_idx - prev_idx
                    if disp > cls.BLZ_N:
                        break
                    if disp < cls.MIN_DISP:
                        continue
                    checked += 1
                    if checked > max_chain:
                        break

                    m_len = 3
                    max_len = min(cls.BLZ_F, raw_new - raw_idx)
                    while (
                        m_len < max_len
                        and raw_buf[raw_idx + m_len] == raw_buf[prev_idx + m_len]
                    ):
                        m_len += 1

                    if m_len > len_best:
                        len_best = m_len
                        pos_best = disp
                        if len_best == cls.BLZ_F:
                            break

            # Register position in hash table
            if raw_idx + 3 <= raw_new:
                table[bytes(raw_buf[raw_idx : raw_idx + 3])].append(raw_idx)

            pak_buffer[flag_idx] = (pak_buffer[flag_idx] << 1) & 0xFF
            if len_best > cls.BLZ_THRESHOLD:
                pak_buffer[flag_idx] |= 1
                # Index skipped bytes into table
                for step in range(1, len_best):
                    s_idx = raw_idx + step
                    if s_idx + 3 <= raw_new:
                        table[bytes(raw_buf[s_idx : s_idx + 3])].append(s_idx)

                raw_idx += len_best
                pak_buffer.extend([
                    ((len_best - (cls.BLZ_THRESHOLD + 1)) << 4) | ((pos_best - cls.MIN_DISP) >> 8),
                    (pos_best - cls.MIN_DISP) & 0xFF,
                ])
            else:
                pak_buffer.append(raw_buf[raw_idx])
                raw_idx += 1

            # Track optimal cutoff point yielding smallest total file size
            curr_cost = len(pak_buffer) + (raw_len - raw_idx)
            if curr_cost < pak_tmp + raw_tmp:
                pak_tmp = len(pak_buffer)
                raw_tmp = raw_len - raw_idx

        # Align final flag byte to MSB if incomplete
        while mask and mask != 1:
            mask >>= 1
            pak_buffer[flag_idx] = (pak_buffer[flag_idx] << 1) & 0xFF

        raw_buf.reverse()
        pak_len = len(pak_buffer)
        pak_buffer.reverse()

        inc_len = raw_len - pak_tmp - raw_tmp

        # If compression is ineffective or does not reduce size, store uncompressed with 4 trailing zero bytes
        if (
            not pak_tmp
            or inc_len <= 11
            or (((pak_tmp + raw_tmp + 3) & -4) + 8 >= raw_len)
        ):
            out = bytearray(raw_buf)
            while len(out) & 3:
                out.append(0)
            out.extend(b"\x00\x00\x00\x00")
            return bytes(out)

        # Assemble compressed output:
        # [Uncompressed Prefix] + [Compressed Payload] + [0xFF Padding] + [BLZTrailerStruct]
        out = bytearray()
        out.extend(raw_buf[:raw_tmp])
        out.extend(pak_buffer[pak_len - pak_tmp : pak_len])

        enc_len = pak_tmp
        hdr_len = 8
        inc_len = raw_len - pak_tmp - raw_tmp

        # 4-byte align trailer with 0xFF padding bytes
        while len(out) & 3:
            out.append(0xFF)
            hdr_len += 1

        enc_and_hdr = (hdr_len << 24) | ((enc_len + hdr_len) & 0x00FFFFFF)
        inc_len_hdr = inc_len - hdr_len

        trailer = BLZTrailerStruct(enc_and_hdr=enc_and_hdr, inc_len_hdr=inc_len_hdr)
        out.extend(trailer.to_bytes())
        return bytes(out)
