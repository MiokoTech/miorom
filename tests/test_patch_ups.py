"""
Unit tests for UPS (Universal Patching System) patcher.
"""

import os
import tempfile
import pytest

from miorom.patch.ups import UpsPatcher
from miorom.patch import create_patch, apply_patch
from miorom.errors import PatchError


def test_ups_patch_roundtrip_basic():
    original = b"MioROM GBA Original ROM Data Sample. 1234567890"
    modified = b"MioROM GBA Modified ROM Data Sample. ABCDEFGHIJ"

    patch = UpsPatcher.create(original, modified)
    assert patch.startswith(b"UPS1")
    assert len(patch) > 16

    restored = UpsPatcher.apply(original, patch)
    assert restored == modified


def test_ups_patch_different_sizes():
    original = b"Short ROM"
    modified = b"Much longer modified ROM with appended expansion text and graphics."

    patch = UpsPatcher.create(original, modified)
    restored = UpsPatcher.apply(original, patch)
    assert restored == modified

    # Test shrink
    patch_shrink = UpsPatcher.create(modified, original)
    restored_short = UpsPatcher.apply(modified, patch_shrink)
    assert restored_short == original


def test_ups_patch_inspection():
    original = b"Test Source Data"
    modified = b"Test Target Data"
    patch = UpsPatcher.create(original, modified)

    meta = UpsPatcher.inspect(patch)
    assert meta["source_size"] == len(original)
    assert meta["target_size"] == len(modified)
    assert meta["is_patch_valid"] is True


def test_ups_patch_corrupt_detection():
    original = b"Source"
    modified = b"Target"
    patch = bytearray(UpsPatcher.create(original, modified))

    # Corrupt a byte in the body
    patch[8] ^= 0xFF

    with pytest.raises(PatchError):
        UpsPatcher.apply(original, bytes(patch))


def test_ups_file_create_and_apply_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = os.path.join(tmpdir, "game.gba")
        dst_file = os.path.join(tmpdir, "game_mod.gba")
        patch_file = os.path.join(tmpdir, "patch.ups")
        out_file = os.path.join(tmpdir, "game_restored.gba")

        src_data = b"Initial GBA game binary data with code and text."
        dst_data = b"Translated GBA game binary data with code and text."

        with open(src_file, "wb") as f:
            f.write(src_data)
        with open(dst_file, "wb") as f:
            f.write(dst_data)

        # Use unified create_patch with auto-detection from .ups
        create_patch(src_file, dst_file, patch_file)
        assert os.path.exists(patch_file)

        # Use unified apply_patch with auto-detection from .ups
        apply_patch(src_file, patch_file, out_file)
        with open(out_file, "rb") as f:
            restored_data = f.read()

        assert restored_data == dst_data
