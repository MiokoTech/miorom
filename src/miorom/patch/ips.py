import struct
from typing import Union, BinaryIO
from io import BytesIO


class IpsPatcher:
    """
    Pure-Python IPS (International Patching System) Creator and Applier.
    Standard patch format for retro ROMs (up to 16MB).
    """

    MAGIC = b"PATCH"
    EOF = b"EOF"

    @classmethod
    def apply(cls, original: bytes, patch: bytes) -> bytes:
        """Apply an IPS patch to original binary data."""
        if not patch.startswith(cls.MAGIC):
            raise ValueError("Invalid IPS patch: missing 'PATCH' magic header")

        result = bytearray(original)
        pos = len(cls.MAGIC)
        patch_len = len(patch)

        while pos < patch_len:
            if patch[pos:pos+3] == cls.EOF:
                pos += 3
                # Check for optional 3-byte truncation offset (IPS32 extension)
                if pos + 3 <= patch_len:
                    trunc_size = (patch[pos] << 16) | (patch[pos+1] << 8) | patch[pos+2]
                    result = result[:trunc_size]
                break

            if pos + 5 > patch_len:
                raise ValueError("Truncated IPS record")

            offset = (patch[pos] << 16) | (patch[pos+1] << 8) | patch[pos+2]
            size = (patch[pos+3] << 8) | patch[pos+4]
            pos += 5

            if size > 0:
                # Normal record
                if pos + size > patch_len:
                    raise ValueError("Truncated IPS payload")
                data = patch[pos:pos+size]
                pos += size

                # Expand result if necessary
                if offset + size > len(result):
                    result.extend(b"\x00" * (offset + size - len(result)))

                result[offset:offset+size] = data
            else:
                # RLE record
                if pos + 3 > patch_len:
                    raise ValueError("Truncated IPS RLE record")
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
            raise ValueError(f"File size {max_len} exceeds IPS 16MB limit. Use BPS or Xdelta instead.")

        i = 0
        while i < max_len:
            orig_b = original[i] if i < orig_len else None
            mod_b = modified[i] if i < mod_len else None

            if orig_b != mod_b:
                # Found start of difference
                start = i
                # Check for special 'EOF' offset collision (0x454F46)
                if start == 0x454F46:
                    start -= 1
                    i -= 1

                # Gather diff run up to max record size (65535 bytes)
                diff_bytes = bytearray()
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
                        patch.extend(struct.pack(">I", start)[1:]) # 3-byte offset
                        patch.extend(b"\x00\x00")                 # Size 0
                        patch.extend(struct.pack(">H", size))      # RLE size
                        patch.append(diff_bytes[0])               # RLE byte
                    else:
                        # Normal record
                        patch.extend(struct.pack(">I", start)[1:]) # 3-byte offset
                        patch.extend(struct.pack(">H", size))      # Size
                        patch.extend(diff_bytes)                  # Data
            else:
                i += 1

        patch.extend(cls.EOF)
        # If modified is shorter than original, append truncation extension
        if mod_len < orig_len:
            patch.extend(struct.pack(">I", mod_len)[1:])

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
