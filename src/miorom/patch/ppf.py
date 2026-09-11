"""
miorom.patch.ppf
~~~~~~~~~~~~~~~~
PlayStation Patch Format (PPF v1.0, v2.0, v3.0) creator, applier, and inspector.

PPF is the standard binary patching container used across PlayStation 1,
PlayStation 2, and PlayStation Portable optical disc images.
"""

from __future__ import annotations

import io
import struct
from typing import BinaryIO, Dict, List, Optional, Tuple, Union

from miorom.errors import PatchError
from miorom.result import MioRomResult


PPF1_MAGIC = b"PPF10"
PPF2_MAGIC = b"PPF20"
PPF3_MAGIC = b"PPF30"


class PPFPatcher(MioRomResult):
    """
    PlayStation Patch Format (PPF v1, v2, v3) encoder, decoder, and streaming patcher.
    """

    @classmethod
    def parse(cls, patch: bytes) -> Dict[str, Union[str, int, bool]]:
        """Parses and inspects PPF patch header metadata and chunk statistics."""
        if len(patch) < 56:
            raise PatchError("Data too small for PPF header (minimum 56 bytes).")

        magic = patch[:5]
        if magic not in (PPF1_MAGIC, PPF2_MAGIC, PPF3_MAGIC):
            raise PatchError(f"Invalid PPF magic: {magic!r}")

        version = 1 if magic == PPF1_MAGIC else (2 if magic == PPF2_MAGIC else 3)
        description = patch[6:56].decode("latin-1", errors="replace").rstrip("\x00")

        has_undo = False
        has_block_check = False
        image_type = 0

        if version == 3:
            if len(patch) < 60:
                raise PatchError("Incomplete PPF3 header.")
            image_type = patch[56]
            has_block_check = patch[57] != 0
            has_undo = patch[58] != 0

        # Scan hunks to compute total records and changed bytes
        stream = io.BytesIO(patch)
        if version == 1:
            stream.seek(56)
        elif version == 2:
            stream.seek(56 + 4 + 4 + 1024)
        else:
            base_header_len = 60
            if has_block_check:
                base_header_len += 1024
            stream.seek(base_header_len)

        record_count = 0
        total_modified_bytes = 0

        while True:
            if version == 3:
                pos_data = stream.read(8)
                if not pos_data:
                    break
                if len(pos_data) < 8:
                    break
                len_data = stream.read(1)
                if not len_data:
                    break
                chunk_len = len_data[0]
                if has_undo:
                    stream.seek(chunk_len, io.SEEK_CUR)
                stream.seek(chunk_len, io.SEEK_CUR)
            else:
                pos_data = stream.read(4)
                if not pos_data:
                    break
                if len(pos_data) < 4:
                    break
                len_data = stream.read(1)
                if not len_data:
                    break
                chunk_len = len_data[0]
                stream.seek(chunk_len, io.SEEK_CUR)

            record_count += 1
            total_modified_bytes += chunk_len

        return {
            "version": version,
            "magic": magic.decode("ascii"),
            "description": description,
            "has_undo": has_undo,
            "has_block_check": has_block_check,
            "image_type": image_type,
            "record_count": record_count,
            "total_modified_bytes": total_modified_bytes,
        }

    @classmethod
    def apply(
        cls,
        source: bytes,
        patch: bytes,
        validate_block: bool = True,
    ) -> bytes:
        """Applies a PPF patch to in-memory binary data."""
        src_stream = io.BytesIO(source)
        patch_stream = io.BytesIO(patch)

        cls.apply_stream(src_stream, patch_stream, validate_block=validate_block)
        return src_stream.getvalue()

    @classmethod
    def apply_stream(
        cls,
        target_stream: BinaryIO,
        patch_stream: BinaryIO,
        output_stream: Optional[BinaryIO] = None,
        validate_block: bool = True,
    ):
        """
        Streams a PPF patch onto a file stream with low memory overhead.
        If output_stream is None, patches target_stream directly in-place.
        """
        patch_stream.seek(0)
        hdr = patch_stream.read(5)
        if len(hdr) < 5:
            raise PatchError("Patch stream too small for PPF header.")

        if hdr == PPF3_MAGIC:
            meta = patch_stream.read(55)
            if len(meta) < 55:
                raise PatchError("Truncated PPF3 header.")
            image_type = meta[51]
            has_block_check = meta[52] != 0
            has_undo = meta[53] != 0

            if has_block_check:
                expected_validation = patch_stream.read(1024)
                if len(expected_validation) < 1024:
                    raise PatchError("Truncated PPF3 validation block in patch.")
                if validate_block:
                    check_offset = 0x8000 if image_type == 1 else 0x9320
                    target_stream.seek(check_offset)
                    actual_validation = target_stream.read(1024)
                    if actual_validation != expected_validation:
                        raise PatchError("Target image validation block does not match PPF3 patch.")

            while True:
                pos_data = patch_stream.read(8)
                if not pos_data:
                    break
                if len(pos_data) < 8:
                    raise PatchError("Truncated offset in PPF3 record.")
                offset = struct.unpack("<Q", pos_data)[0]

                len_byte = patch_stream.read(1)
                if not len_byte:
                    raise PatchError("Truncated length byte in PPF3 record.")
                chunk_len = len_byte[0]

                if has_undo:
                    # Skip undo data bytes
                    undo_bytes = patch_stream.read(chunk_len)
                    if len(undo_bytes) < chunk_len:
                        raise PatchError("Truncated undo data in PPF3 record.")

                patch_data = patch_stream.read(chunk_len)
                if len(patch_data) < chunk_len:
                    raise PatchError("Truncated payload in PPF3 record.")

                dest = output_stream if output_stream is not None else target_stream
                dest.seek(offset)
                dest.write(patch_data)

        elif hdr == PPF2_MAGIC:
            meta = patch_stream.read(51)
            if len(meta) < 51:
                raise PatchError("Truncated PPF2 header.")
            img_size_bytes = patch_stream.read(4)
            blk_size_bytes = patch_stream.read(4)
            val_block = patch_stream.read(1024)
            if len(val_block) < 1024:
                raise PatchError("Truncated PPF2 validation block.")

            if validate_block:
                target_stream.seek(0x9320)
                actual_val = target_stream.read(1024)
                if len(actual_val) == 1024 and actual_val != val_block:
                    raise PatchError("Target image validation block does not match PPF2 patch.")

            while True:
                pos_data = patch_stream.read(4)
                if not pos_data:
                    break
                if len(pos_data) < 4:
                    break
                offset = struct.unpack("<I", pos_data)[0]

                len_byte = patch_stream.read(1)
                if not len_byte:
                    break
                chunk_len = len_byte[0]

                patch_data = patch_stream.read(chunk_len)
                if len(patch_data) < chunk_len:
                    raise PatchError("Truncated payload in PPF2 record.")

                dest = output_stream if output_stream is not None else target_stream
                dest.seek(offset)
                dest.write(patch_data)

        elif hdr == PPF1_MAGIC:
            patch_stream.seek(56)
            while True:
                pos_data = patch_stream.read(4)
                if not pos_data:
                    break
                if len(pos_data) < 4:
                    break
                offset = struct.unpack("<I", pos_data)[0]

                len_byte = patch_stream.read(1)
                if not len_byte:
                    break
                chunk_len = len_byte[0]

                patch_data = patch_stream.read(chunk_len)
                if len(patch_data) < chunk_len:
                    raise PatchError("Truncated payload in PPF1 record.")

                dest = output_stream if output_stream is not None else target_stream
                dest.seek(offset)
                dest.write(patch_data)

        else:
            raise PatchError(f"Unsupported PPF magic: {hdr!r}")

    @classmethod
    def create(
        cls,
        source: bytes,
        modified: bytes,
        description: str = "MioROM PPF3 Patch",
        version: int = 3,
        include_undo: bool = True,
        block_check: bool = False,
    ) -> bytes:
        """
        Creates a PPF patch from source and modified binary bytes.
        Defaults to PPF 3.0 standard.
        """
        max_len = max(len(source), len(modified))
        diff_chunks: List[Tuple[int, bytes, bytes]] = []

        # Find diff chunks (<= 255 bytes per record)
        idx = 0
        while idx < max_len:
            src_b = source[idx] if idx < len(source) else 0
            mod_b = modified[idx] if idx < len(modified) else 0

            if src_b != mod_b:
                start = idx
                orig_chunk = bytearray()
                mod_chunk = bytearray()

                while idx < max_len and len(mod_chunk) < 255:
                    s = source[idx] if idx < len(source) else 0
                    m = modified[idx] if idx < len(modified) else 0
                    if s == m and (idx + 1 < max_len):
                        # Peek ahead to avoid splitting small single-byte matches
                        next_s = source[idx + 1] if idx + 1 < len(source) else 0
                        next_m = modified[idx + 1] if idx + 1 < len(modified) else 0
                        if next_s != next_m:
                            orig_chunk.append(s)
                            mod_chunk.append(m)
                            idx += 1
                            continue
                        break
                    orig_chunk.append(s)
                    mod_chunk.append(m)
                    idx += 1

                diff_chunks.append((start, bytes(orig_chunk), bytes(mod_chunk)))
            else:
                idx += 1

        desc_bytes = description.encode("latin-1", errors="replace")[:50]
        desc_padded = desc_bytes.ljust(50, b"\x00")

        out = bytearray()

        if version == 3:
            out.extend(PPF3_MAGIC)
            out.append(0x00)  # Encoding / method
            out.extend(desc_padded)
            out.append(0x00)  # Image type (BIN)
            out.append(1 if block_check else 0)
            out.append(1 if include_undo else 0)
            out.append(0x00)  # Reserved dummy

            if block_check:
                if len(source) >= 0x9320 + 1024:
                    out.extend(source[0x9320 : 0x9320 + 1024])
                else:
                    out.extend(b"\x00" * 1024)

            for offset, orig_data, mod_data in diff_chunks:
                out.extend(struct.pack("<Q", offset))
                out.append(len(mod_data))
                if include_undo:
                    out.extend(orig_data)
                out.extend(mod_data)

        elif version == 2:
            out.extend(PPF2_MAGIC)
            out.append(0x00)
            out.extend(desc_padded)
            out.extend(struct.pack("<I", len(source)))
            out.extend(struct.pack("<I", 1024))
            if block_check and len(source) >= 0x9320 + 1024:
                out.extend(source[0x9320 : 0x9320 + 1024])
            else:
                out.extend(b"\x00" * 1024)

            for offset, _, mod_data in diff_chunks:
                out.extend(struct.pack("<I", offset & 0xFFFFFFFF))
                out.append(len(mod_data))
                out.extend(mod_data)

        else:
            # PPF 1.0
            out.extend(PPF1_MAGIC)
            out.append(0x00)
            out.extend(desc_padded)

            for offset, _, mod_data in diff_chunks:
                out.extend(struct.pack("<I", offset & 0xFFFFFFFF))
                out.append(len(mod_data))
                out.extend(mod_data)

        return bytes(out)

    @classmethod
    def apply_file(
        cls,
        source_path: str,
        patch_path: str,
        output_path: str,
        validate_block: bool = True,
    ):
        """Applies a PPF patch from files on disk."""
        with open(source_path, "rb") as sf, open(patch_path, "rb") as pf, open(output_path, "w+b") as of:
            # Copy source to output
            while chunk := sf.read(65536):
                of.write(chunk)
            of.flush()
            # Apply patch on output file
            cls.apply_stream(of, pf, validate_block=validate_block)

    @classmethod
    def create_file(
        cls,
        source_path: str,
        target_path: str,
        patch_path: str,
        description: str = "MioROM PPF3 Patch",
        version: int = 3,
        include_undo: bool = True,
        block_check: bool = False,
    ):
        """Creates a PPF patch from source and target files on disk."""
        with open(source_path, "rb") as sf, open(target_path, "rb") as tf:
            src_bytes = sf.read()
            tgt_bytes = tf.read()
        patch_data = cls.create(
            src_bytes,
            tgt_bytes,
            description=description,
            version=version,
            include_undo=include_undo,
            block_check=block_check,
        )
        with open(patch_path, "wb") as pf:
            pf.write(patch_data)

