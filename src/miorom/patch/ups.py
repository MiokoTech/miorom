"""
miorom.patch.ups
~~~~~~~~~~~~~~~~
Pure-Python UPS (Universal Patching System) Patcher and Creator.
Commonly used across Game Boy Advance (GBA) and Nintendo translation and hacking projects.
"""

from __future__ import annotations

import struct
import zlib
from io import BytesIO
from typing import Dict, Union

from miorom.core.vlq import encode_ups_varint, decode_ups_varint
from miorom.errors import PatchError, ParseError


def _encode_vlq(val: int) -> bytes:
    return encode_ups_varint(val)


def _decode_vlq(stream: BytesIO) -> int:
    data = stream.getvalue()
    pos = stream.tell()
    try:
        val, consumed = decode_ups_varint(data, pos)
        stream.seek(pos + consumed)
        return val
    except ParseError as err:
        raise EOFError(str(err))


class UpsPatcher:
    """
    Pure-Python UPS (Universal Patching System) format creator, patcher, and inspector.
    """

    MAGIC = b"UPS1"

    @classmethod
    def apply(cls, source: bytes, patch: bytes, ignore_checksums: bool = False) -> bytes:
        """Applies a UPS patch to source binary data with CRC32 verification."""
        if len(patch) < 16:
            raise PatchError("Invalid UPS patch: file too small (minimum 16 bytes).")
        if not patch.startswith(cls.MAGIC):
            raise PatchError("Invalid UPS patch: missing 'UPS1' header magic.")

        # Check patch file CRC32 (last 4 bytes)
        src_crc, dst_crc, patch_crc = struct.unpack("<III", patch[-12:])
        actual_patch_crc = zlib.crc32(patch[:-4]) & 0xFFFFFFFF
        if not ignore_checksums and actual_patch_crc != patch_crc:
            raise PatchError(
                f"Corrupt UPS patch: patch CRC32 mismatch (expected 0x{patch_crc:08X}, got 0x{actual_patch_crc:08X})"
            )

        stream = BytesIO(patch[4:-12])
        try:
            src_len = _decode_vlq(stream)
            dst_len = _decode_vlq(stream)
        except EOFError as err:
            raise PatchError(f"Malformed UPS header sizes: {err}")

        actual_src_crc = zlib.crc32(source) & 0xFFFFFFFF
        if not ignore_checksums and (len(source) != src_len or actual_src_crc != src_crc):
            raise PatchError(
                f"Source file mismatch! Expected size {src_len} (CRC 0x{src_crc:08X}), "
                f"got size {len(source)} (CRC 0x{actual_src_crc:08X})."
            )

        # Allocate target buffer
        target = bytearray(source)
        if len(target) < dst_len:
            target.extend(b"\x00" * (dst_len - len(target)))
        elif len(target) > dst_len:
            target = target[:dst_len]

        cur_offset = 0
        total_stream_bytes = len(patch) - 16
        while (stream.tell()) < total_stream_bytes:
            try:
                delta = _decode_vlq(stream)
            except EOFError:
                break
            cur_offset += delta
            while True:
                raw = stream.read(1)
                if not raw or raw[0] == 0:
                    break
                if cur_offset < len(target):
                    target[cur_offset] ^= raw[0]
                cur_offset += 1
            cur_offset += 1

        actual_dst_crc = zlib.crc32(target) & 0xFFFFFFFF
        if not ignore_checksums and actual_dst_crc != dst_crc:
            raise PatchError(
                f"Patched data checksum verification failed (expected 0x{dst_crc:08X}, got 0x{actual_dst_crc:08X})"
            )

        return bytes(target)

    @classmethod
    def create(cls, source: bytes, target: bytes) -> bytes:
        """Creates a UPS patch byte stream from source to target binary data."""
        out = bytearray(cls.MAGIC)
        out.extend(_encode_vlq(len(source)))
        out.extend(_encode_vlq(len(target)))

        max_len = max(len(source), len(target))
        cur = 0
        prev = 0

        while cur < max_len:
            s_b = source[cur] if cur < len(source) else 0
            t_b = target[cur] if cur < len(target) else 0
            if s_b == t_b:
                cur += 1
                continue

            diff = cur - prev
            out.extend(_encode_vlq(diff))
            while cur < max_len:
                s_b = source[cur] if cur < len(source) else 0
                t_b = target[cur] if cur < len(target) else 0
                xor_b = s_b ^ t_b
                if xor_b == 0:
                    break
                out.append(xor_b)
                cur += 1
            out.append(0x00)
            cur += 1
            prev = cur

        src_crc = zlib.crc32(source) & 0xFFFFFFFF
        dst_crc = zlib.crc32(target) & 0xFFFFFFFF
        out.extend(struct.pack("<II", src_crc, dst_crc))
        patch_crc = zlib.crc32(out) & 0xFFFFFFFF
        out.extend(struct.pack("<I", patch_crc))
        return bytes(out)

    @classmethod
    def apply_file(cls, source_path: str, patch_path: str, output_path: str, ignore_checksums: bool = False):
        """Applies a UPS patch file to a source file, writing to output_path."""
        with open(source_path, "rb") as f:
            source = f.read()
        with open(patch_path, "rb") as f:
            patch = f.read()

        result = cls.apply(source, patch, ignore_checksums=ignore_checksums)
        with open(output_path, "wb") as f:
            f.write(result)

    @classmethod
    def create_file(cls, source_path: str, target_path: str, patch_path: str):
        """Creates a UPS patch file comparing source_path to target_path."""
        with open(source_path, "rb") as f:
            source = f.read()
        with open(target_path, "rb") as f:
            target = f.read()

        patch = cls.create(source, target)
        with open(patch_path, "wb") as f:
            f.write(patch)

    @classmethod
    def inspect(cls, patch: bytes) -> Dict[str, Union[int, bool]]:
        """Inspects UPS patch metadata without applying it."""
        if len(patch) < 16 or not patch.startswith(cls.MAGIC):
            raise PatchError("Invalid UPS patch data.")

        src_crc, dst_crc, patch_crc = struct.unpack("<III", patch[-12:])
        actual_patch_crc = zlib.crc32(patch[:-4]) & 0xFFFFFFFF
        stream = BytesIO(patch[4:-12])
        src_len = _decode_vlq(stream)
        dst_len = _decode_vlq(stream)

        return {
            "source_size": src_len,
            "target_size": dst_len,
            "source_crc32": src_crc,
            "target_crc32": dst_crc,
            "patch_crc32": patch_crc,
            "is_patch_valid": actual_patch_crc == patch_crc,
        }
