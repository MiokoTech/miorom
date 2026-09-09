import struct
import zlib
from io import BytesIO
from typing import Dict, List
from miorom.errors import PatchError
from miorom.patch.hunks import PatchHunk, merge_patches


def _encode_vlq(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val == 0:
            out.append(b | 0x80)
            break
        out.append(b)
        val -= 1
    return bytes(out)


def _decode_vlq(stream: BytesIO) -> int:
    val = 0
    shift = 0
    while True:
        raw = stream.read(1)
        if not raw:
            raise EOFError("Unexpected EOF reading BPS VLQ")
        b = raw[0]
        val += (b & 0x7F) << shift
        if b & 0x80:
            break
        shift += 7
        val += 1 << shift
    return val


class BpsPatcher:
    """
    Pure-Python BPS (Beat Patch System) Patcher and Creator.
    Modern patch format supporting arbitrary file sizes and CRC32 verification.
    """

    MAGIC = b"BPS1"

    @classmethod
    def apply(cls, source: bytes, patch: bytes) -> bytes:
        """Apply a BPS patch to source binary data with CRC32 verification."""
        if not patch.startswith(cls.MAGIC):
            raise PatchError("Invalid BPS patch: missing 'BPS1' header")

        # Verify patch CRC32 (last 4 bytes)
        expected_patch_crc = struct.unpack("<I", patch[-4:])[0]
        actual_patch_crc = zlib.crc32(patch[:-4]) & 0xFFFFFFFF
        if actual_patch_crc != expected_patch_crc:
            raise PatchError("Corrupted BPS patch: patch CRC32 mismatch")

        expected_source_crc = struct.unpack("<I", patch[-12:-8])[0]
        expected_target_crc = struct.unpack("<I", patch[-8:-4])[0]

        actual_source_crc = zlib.crc32(source) & 0xFFFFFFFF
        if actual_source_crc != expected_source_crc:
            raise PatchError(
                f"Source checksum mismatch! Expected: {hex(expected_source_crc)}, got: {hex(actual_source_crc)}"
            )

        stream = BytesIO(patch[4:-12])
        source_size = _decode_vlq(stream)
        target_size = _decode_vlq(stream)
        meta_size = _decode_vlq(stream)
        _ = stream.read(meta_size)  # skip metadata

        target = bytearray(target_size)
        output_offset = 0
        source_rel_offset = 0
        target_rel_offset = 0

        while output_offset < target_size:
            data = _decode_vlq(stream)
            action = data & 3
            length = (data >> 2) + 1

            if action == 0:
                # SourceRead
                target[output_offset:output_offset+length] = source[output_offset:output_offset+length]
                output_offset += length
            elif action == 1:
                # TargetRead
                chunk = stream.read(length)
                target[output_offset:output_offset+length] = chunk
                output_offset += length
            elif action == 2:
                # SourceCopy
                offset_data = _decode_vlq(stream)
                offset_sign = -1 if (offset_data & 1) else 1
                source_rel_offset += offset_sign * (offset_data >> 1)
                for _ in range(length):
                    target[output_offset] = source[source_rel_offset]
                    output_offset += 1
                    source_rel_offset += 1
            elif action == 3:
                # TargetCopy
                offset_data = _decode_vlq(stream)
                offset_sign = -1 if (offset_data & 1) else 1
                target_rel_offset += offset_sign * (offset_data >> 1)
                for _ in range(length):
                    target[output_offset] = target[target_rel_offset]
                    output_offset += 1
                    target_rel_offset += 1

        actual_target_crc = zlib.crc32(target) & 0xFFFFFFFF
        if actual_target_crc != expected_target_crc:
            raise PatchError("Target checksum mismatch after BPS patching")

        return bytes(target)

    @classmethod
    def parse(cls, patch: bytes, source: bytes) -> List[PatchHunk]:
        """Decode a BPS patch to concrete writes using its own source image."""
        output = bytearray(cls.apply(source, patch))
        source_bytes = source
        source_len = len(source_bytes)
        hunks: List[PatchHunk] = []
        for index, (source_byte, output_byte) in enumerate(zip(source_bytes, output)):
            if source_byte != output_byte:
                hunks.append(PatchHunk(index, bytes([output_byte])))
        if len(output) > source_len:
            start = source_len
            for index, byte in enumerate(output[source_len:]):
                if byte:
                    hunks.append(PatchHunk(start + index, bytes([byte])))
        return merge_patches(hunks)

    @classmethod
    def create(cls, source: bytes, target: bytes, metadata: str = "") -> bytes:
        """Create a standard linear BPS patch from source to target."""
        out = bytearray(cls.MAGIC)
        out.extend(_encode_vlq(len(source)))
        out.extend(_encode_vlq(len(target)))
        meta_bytes = metadata.encode("utf-8")
        out.extend(_encode_vlq(len(meta_bytes)))
        out.extend(meta_bytes)

        source_len = len(source)
        target_len = len(target)
        output_offset = 0

        while output_offset < target_len:
            # Check for matches with source at same offset (SourceRead)
            same_len = 0
            while (output_offset + same_len < target_len and
                   output_offset + same_len < source_len and
                   source[output_offset + same_len] == target[output_offset + same_len]):
                same_len += 1

            if same_len >= 4 or (same_len > 0 and output_offset + same_len == target_len):
                # Action 0: SourceRead
                data = ((same_len - 1) << 2) | 0
                out.extend(_encode_vlq(data))
                output_offset += same_len
                continue

            # Gather differing bytes (TargetRead)
            diff_bytes = bytearray()
            while output_offset < target_len:
                # Lookahead to see if next bytes match source
                if (output_offset < source_len and
                    source[output_offset] == target[output_offset]):
                    matching = 0
                    while (matching < 4 and
                           output_offset + matching < target_len and
                           output_offset + matching < source_len and
                           source[output_offset + matching] == target[output_offset + matching]):
                        matching += 1
                    if matching == 4:
                        break
                diff_bytes.append(target[output_offset])
                output_offset += 1

            if diff_bytes:
                # Action 1: TargetRead
                data = ((len(diff_bytes) - 1) << 2) | 1
                out.extend(_encode_vlq(data))
                out.extend(diff_bytes)

        # Checksums
        source_crc = zlib.crc32(source) & 0xFFFFFFFF
        target_crc = zlib.crc32(target) & 0xFFFFFFFF
        out.extend(struct.pack("<II", source_crc, target_crc))
        patch_crc = zlib.crc32(out) & 0xFFFFFFFF
        out.extend(struct.pack("<I", patch_crc))

        return bytes(out)

    @classmethod
    def apply_file(cls, src_path: str, patch_path: str, out_path: str):
        with open(src_path, "rb") as f:
            src = f.read()
        with open(patch_path, "rb") as f:
            patch = f.read()
        res = cls.apply(src, patch)
        with open(out_path, "wb") as f:
            f.write(res)

    @classmethod
    def create_file(cls, src_path: str, target_path: str, patch_path: str, metadata: str = ""):
        with open(src_path, "rb") as f:
            src = f.read()
        with open(target_path, "rb") as f:
            target = f.read()
        patch = cls.create(src, target, metadata=metadata)
        with open(patch_path, "wb") as f:
            f.write(patch)
