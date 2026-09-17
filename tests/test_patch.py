import os
import tempfile
import pytest
from miorom.patch.ips import IpsPatcher
from miorom.patch.bps import BpsPatcher
from miorom.patch.xdelta import XdeltaPatcher
from miorom.patch import create_patch, apply_patch


def test_ips_patch():
    original = b"Hello, World! This is the original ROM data."
    modified = b"Hello, World! This is the MODIFIED ROM data with new text."

    patch = IpsPatcher.create(original, modified)
    assert patch.startswith(b"PATCH")
    assert patch.endswith(b"EOF")

    reconstructed = IpsPatcher.apply(original, patch)
    assert reconstructed == modified


def test_ips_patch_eof_offset_collision():
    """Verify that changes at offset 0x454F46 ('EOF') are correctly patched and not skipped."""
    original = bytearray(0x454F50)
    modified = bytearray(0x454F50)
    modified[0x454F46] = 0x99
    modified[0x454F47] = 0xAA

    patch = IpsPatcher.create(bytes(original), bytes(modified))
    assert patch.startswith(b"PATCH")
    assert patch.endswith(b"EOF")

    reconstructed = IpsPatcher.apply(bytes(original), patch)
    assert reconstructed[0x454F46] == 0x99
    assert reconstructed[0x454F47] == 0xAA
    assert reconstructed == bytes(modified)


def test_ips_stream_overlapping_and_truncation():
    """Verify that apply_stream handles overlapping records and truncation identically to apply."""
    import io
    import struct

    # 1. Overlapping records test
    patch = bytearray(b"PATCH")
    patch.extend(struct.pack(">I", 10)[1:])
    patch.extend(struct.pack(">H", 6))
    patch.extend(b"ABCDEF")
    patch.extend(struct.pack(">I", 12)[1:])
    patch.extend(struct.pack(">H", 2))
    patch.extend(b"99")
    patch.extend(b"EOF")

    orig = b"0123456789" * 4
    in_mem = IpsPatcher.apply(orig, bytes(patch))
    assert in_mem[10:16] == b"AB99EF"

    out_stream = io.BytesIO()
    IpsPatcher.apply_stream(io.BytesIO(orig), bytes(patch), out_stream)
    assert out_stream.getvalue() == in_mem

    # 2. Truncation test
    trunc_patch = bytearray(b"PATCH")
    trunc_patch.extend(struct.pack(">I", 0)[1:])
    trunc_patch.extend(struct.pack(">H", 4))
    trunc_patch.extend(b"TEST")
    trunc_patch.extend(b"EOF")
    trunc_patch.extend(struct.pack(">I", 15)[1:])  # Truncate to 15 bytes

    trunc_in_mem = IpsPatcher.apply(orig, bytes(trunc_patch))
    assert len(trunc_in_mem) == 15

    trunc_out_stream = io.BytesIO()
    IpsPatcher.apply_stream(io.BytesIO(orig), bytes(trunc_patch), trunc_out_stream)
    assert trunc_out_stream.getvalue() == trunc_in_mem



def test_bps_patch():
    original = b"Some source data that will be patched with BPS. " * 50
    modified = b"Some TARGET data that will be patched with BPS! " * 50

    patch = BpsPatcher.create(original, modified)
    assert patch.startswith(b"BPS1")

    reconstructed = BpsPatcher.apply(original, patch)
    assert reconstructed == modified


def test_unified_patch_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_file = os.path.join(tmpdir, "orig.bin")
        mod_file = os.path.join(tmpdir, "mod.bin")
        patch_file = os.path.join(tmpdir, "patch.bps")
        restored_file = os.path.join(tmpdir, "restored.bin")

        orig_data = b"MioROM testing unified patcher system! 12345"
        mod_data = b"MioROM testing unified patcher system! 67890"

        with open(orig_file, "wb") as f:
            f.write(orig_data)
        with open(mod_file, "wb") as f:
            f.write(mod_data)

        # Test BPS
        create_patch(orig_file, mod_file, patch_file)
        apply_patch(orig_file, patch_file, restored_file)

        with open(restored_file, "rb") as f:
            assert f.read() == mod_data

        # Test Xdelta if installed
        if XdeltaPatcher.is_available():
            xdelta_patch = os.path.join(tmpdir, "patch.xdelta")
            xdelta_restored = os.path.join(tmpdir, "xdelta_restored.bin")

            create_patch(orig_file, mod_file, xdelta_patch)
            apply_patch(orig_file, xdelta_patch, xdelta_restored)

            with open(xdelta_restored, "rb") as f:
                assert f.read() == mod_data
