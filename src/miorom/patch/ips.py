from typing import Any, BinaryIO, Dict, List, Tuple

from miorom.core import schema
from miorom.errors import PatchError
from miorom.patch.hunks import PatchHunk, merge_patches


class IpsPatcher:
    """
    Pure-Python IPS (International Patching System) Creator and Applier.
    Standard patch format for retro ROMs (up to 16MB).
    """

    MAGIC = b"PATCH"
    EOF = b"EOF"

    @classmethod
    def iter_records(cls, patch: bytes) -> List[Tuple[int, bytes]]:
        """Return decoded normal/RLE IPS records for patch-translation tools."""
        if not patch.startswith(cls.MAGIC):
            raise PatchError("Invalid IPS patch: missing 'PATCH' magic header")
        records: List[Tuple[int, bytes]] = []
        pos = len(cls.MAGIC)
        while pos + 3 <= len(patch):
            if patch[pos:pos+3] == cls.EOF:
                break
            if pos + 5 > len(patch):
                raise PatchError("Truncated IPS record")
            offset = (patch[pos] << 16) | (patch[pos+1] << 8) | patch[pos+2]
            size = (patch[pos+3] << 8) | patch[pos+4]
            pos += 5
            if size:
                if pos + size > len(patch):
                    raise PatchError("Truncated IPS payload")
                records.append((offset, patch[pos:pos+size]))
                pos += size
            else:
                if pos + 3 > len(patch):
                    raise PatchError("Truncated IPS RLE record")
                rle_size = (patch[pos] << 8) | patch[pos+1]
                rle_val = patch[pos+2]
                pos += 3
                records.append((offset, bytes([rle_val]) * rle_size))
        return records

    @classmethod
    def parse(cls, patch: bytes) -> List[PatchHunk]:
        return [PatchHunk(offset, data) for offset, data in cls.iter_records(patch)]

    @classmethod
    def apply(cls, original: bytes, patch: bytes) -> bytes:
        """Apply an IPS patch to original binary data."""
        if not patch.startswith(cls.MAGIC):
            raise PatchError("Invalid IPS patch: missing 'PATCH' magic header")

        result = bytearray(original)
        pos = len(cls.MAGIC)
        patch_len = len(patch)

        while pos < patch_len:
            if patch[pos:pos+3] == cls.EOF:
                pos += 3
                # Check for optional 3-byte truncation offset (IPS32 extension)
                if pos + 3 <= patch_len:
                    trunc_size = (patch[pos] << 16) | (patch[pos+1] << 8) | patch[pos+2]
                    if 0 < trunc_size < len(result):  # Only truncate if plausible
                        result = result[:trunc_size]
                break

            if pos + 5 > patch_len:
                raise PatchError("Truncated IPS record")

            offset = (patch[pos] << 16) | (patch[pos+1] << 8) | patch[pos+2]
            size = (patch[pos+3] << 8) | patch[pos+4]
            pos += 5

            if size > 0:
                # Normal record
                if pos + size > patch_len:
                    raise PatchError("Truncated IPS payload")
                data = patch[pos:pos+size]
                pos += size

                # Expand result if necessary
                if offset + size > len(result):
                    result.extend(b"\x00" * (offset + size - len(result)))

                result[offset:offset+size] = data
            else:
                # RLE record
                if pos + 3 > patch_len:
                    raise PatchError("Truncated IPS RLE record")
                rle_size = (patch[pos] << 8) | patch[pos+1]
                rle_val = patch[pos+2]
                pos += 3

                if offset + rle_size > len(result):
                    result.extend(b"\x00" * (offset + rle_size - len(result)))

                result[offset:offset+rle_size] = bytes([rle_val]) * rle_size

        return bytes(result)

    @classmethod
    def create(cls, original: bytes, modified: bytes) -> bytes:
        """Generate an IPS patch representing changes from original to modified."""
        patch = bytearray(cls.MAGIC)
        orig_len = len(original)
        mod_len = len(modified)
        max_len = max(orig_len, mod_len)

        if max_len > 0xFFFFFF:
            raise PatchError(f"File size {max_len} exceeds IPS 16MB limit. Use BPS or Xdelta instead.")

        i = 0
        while i < max_len:
            orig_b = original[i] if i < orig_len else None
            mod_b = modified[i] if i < mod_len else None

            if orig_b != mod_b:
                # Found start of difference
                start = i
                diff_bytes = bytearray()
                # Check for special 'EOF' offset collision (0x454F46)
                if start == 0x454F46:
                    start = 0x454F45
                    diff_bytes.append(modified[0x454F45] if 0x454F45 < mod_len else 0)

                # Gather diff run up to max record size (65535 bytes)
                while i < max_len and len(diff_bytes) < 0xFFFF:
                    o = original[i] if i < orig_len else None
                    m = modified[i] if i < mod_len else None
                    if o == m:
                        # Lookahead: if next 4 bytes are identical, end record
                        lookahead = True
                        for j in range(1, 4):
                            if i + j < max_len:
                                oj = original[i+j] if i+j < orig_len else None
                                mj = modified[i+j] if i+j < mod_len else None
                                if oj != mj:
                                    lookahead = False
                                    break
                        if lookahead:
                            break
                    diff_bytes.append(modified[i] if i < mod_len else 0)
                    i += 1

                size = len(diff_bytes)
                if size > 0:
                    # Check for RLE compression possibility
                    if size >= 8 and len(set(diff_bytes)) == 1:
                        # RLE record
                        patch.extend(schema.pack(">I", start)[1:]) # 3-byte offset
                        patch.extend(b"\x00\x00")                 # Size 0
                        patch.extend(schema.pack(">H", size))      # RLE size
                        patch.append(diff_bytes[0])               # RLE byte
                    else:
                        # Normal record
                        patch.extend(schema.pack(">I", start)[1:]) # 3-byte offset
                        patch.extend(schema.pack(">H", size))      # Size
                        patch.extend(diff_bytes)                  # Data
            else:
                i += 1

        patch.extend(cls.EOF)
        # Truncation extension for shorter files
        if mod_len < orig_len:
            patch.extend(schema.pack(">I", mod_len)[1:])

        return bytes(patch)

    @classmethod
    def apply_file(cls, orig_path: str, patch_path: str, out_path: str):
        with open(orig_path, "rb") as f:
            orig = f.read()
        with open(patch_path, "rb") as f:
            patch = f.read()
        res = cls.apply(orig, patch)
        with open(out_path, "wb") as f:
            f.write(res)

    @classmethod
    def create_file(cls, orig_path: str, mod_path: str, patch_path: str):
        with open(orig_path, "rb") as f:
            orig = f.read()
        with open(mod_path, "rb") as f:
            mod = f.read()
        patch = cls.create(orig, mod)
        with open(patch_path, "wb") as f:
            f.write(patch)

    @classmethod
    def apply_stream(
        cls,
        source_stream: BinaryIO,
        patch_bytes: bytes,
        output_stream: BinaryIO,
        chunk_size: int = 65536,
    ):
        """
        Apply IPS patch via constant-memory streaming buffers without loading full image into RAM.
        Ideal for large disc images (PS1, GameCube, Wii) on memory-constrained devices.
        """
        # Resolve all overlapping/adjacent hunks in chronological order
        hunks = merge_patches(cls.parse(patch_bytes))
        source_stream.seek(0)
        current_pos = 0

        # Inspect truncation size (IPS32 extension)
        inspect_data = cls.inspect(patch_bytes)
        truncate_size = inspect_data.get("truncate_size")

        for hunk in hunks:
            while current_pos < hunk.offset:
                to_read = min(chunk_size, hunk.offset - current_pos)
                chunk = source_stream.read(to_read)
                if not chunk:
                    output_stream.write(b"\x00" * (hunk.offset - current_pos))
                    current_pos = hunk.offset
                    break
                output_stream.write(chunk)
                current_pos += len(chunk)

            output_stream.write(hunk.data)
            source_stream.seek(current_pos + len(hunk.data))
            current_pos += len(hunk.data)

        # Stream remaining bytes from source
        while True:
            if truncate_size is not None and current_pos >= truncate_size:
                break
            to_read = chunk_size
            if truncate_size is not None:
                to_read = min(chunk_size, truncate_size - current_pos)
            chunk = source_stream.read(to_read)
            if not chunk:
                break
            output_stream.write(chunk)
            current_pos += len(chunk)

        if truncate_size is not None:
            output_stream.truncate(truncate_size)

    @classmethod
    def inspect(cls, patch: bytes) -> Dict[str, Any]:
        """Inspects IPS patch metadata without applying it."""
        records = cls.iter_records(patch)
        total_changed = sum(len(r[1]) for r in records)
        min_offset = min((r[0] for r in records), default=0)
        max_offset = max((r[0] + len(r[1]) for r in records), default=0)
        eof_pos = patch.rfind(cls.EOF)
        truncate_size = None
        if eof_pos != -1 and eof_pos + 6 <= len(patch):
            truncate_size = (patch[eof_pos + 3] << 16) | (patch[eof_pos + 4] << 8) | patch[eof_pos + 5]

        return {
            "record_count": len(records),
            "changed_bytes": total_changed,
            "min_offset": min_offset,
            "max_offset": max_offset,
            "truncate_size": truncate_size,
        }
