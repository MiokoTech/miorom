import os
import pytest
from miorom.patch.ppf import PPFPatcher, PPF1_MAGIC, PPF2_MAGIC, PPF3_MAGIC
from miorom.patch import create_patch, apply_patch
from miorom.errors import PatchError


def test_ppf3_create_and_apply_roundtrip():
    source = bytearray(b"ORIGINAL_PAYLOAD_FOR_PLAYSTATION_DISC" * 10)
    modified = bytearray(source)
    modified[10:14] = b"MODI"
    modified[50:55] = b"PATCH"

    patch = PPFPatcher.create(
        bytes(source),
        bytes(modified),
        description="Test PPF3 Patch",
        version=3,
        include_undo=True,
    )

    assert patch.startswith(PPF3_MAGIC)

    meta = PPFPatcher.parse(patch)
    assert meta["version"] == 3
    assert meta["description"] == "Test PPF3 Patch"
    assert meta["has_undo"] is True
    assert meta["record_count"] >= 2
    assert meta["total_modified_bytes"] == 9

    patched = PPFPatcher.apply(bytes(source), patch)
    assert patched == bytes(modified)


def test_ppf3_without_undo():
    source = b"A" * 100
    modified = b"A" * 20 + b"BBBBB" + b"A" * 75

    patch = PPFPatcher.create(
        source,
        modified,
        version=3,
        include_undo=False,
    )

    meta = PPFPatcher.parse(patch)
    assert meta["has_undo"] is False

    patched = PPFPatcher.apply(source, patch)
    assert patched == modified


def test_ppf3_block_validation():
    # Source image large enough to have block at 0x9320 (37664)
    source = bytearray(b"\x00" * 40000)
    source[0x9320 : 0x9320 + 10] = b"VALIDATION"
    modified = bytearray(source)
    modified[100:104] = b"DIFF"

    patch = PPFPatcher.create(
        bytes(source),
        bytes(modified),
        version=3,
        block_check=True,
    )

    meta = PPFPatcher.parse(patch)
    assert meta["has_block_check"] is True

    # Applying to matching source succeeds
    patched = PPFPatcher.apply(bytes(source), patch, validate_block=True)
    assert patched == bytes(modified)

    # Applying to corrupt source with mismatched validation block raises PatchError
    corrupt_source = bytearray(source)
    corrupt_source[0x9320 : 0x9320 + 10] = b"CORRUPTED!"
    with pytest.raises(PatchError):
        PPFPatcher.apply(bytes(corrupt_source), patch, validate_block=True)


def test_ppf1_and_ppf2_compatibility():
    source = b"HELLO_LEGACY_PLAYSTATION_DISC_IMAGE"
    modified = b"HELLO_MODDED_PLAYSTATION_DISC_IMAGE"

    # PPF 1.0
    patch1 = PPFPatcher.create(source, modified, version=1)
    assert patch1.startswith(PPF1_MAGIC)
    meta1 = PPFPatcher.parse(patch1)
    assert meta1["version"] == 1
    assert PPFPatcher.apply(source, patch1) == modified

    # PPF 2.0
    patch2 = PPFPatcher.create(source, modified, version=2)
    assert patch2.startswith(PPF2_MAGIC)
    meta2 = PPFPatcher.parse(patch2)
    assert meta2["version"] == 2
    assert PPFPatcher.apply(source, patch2) == modified


def test_ppf_file_helpers_and_universal_patch_api(tmp_path):
    src_file = str(tmp_path / "game.bin")
    mod_file = str(tmp_path / "game_mod.bin")
    patch_file = str(tmp_path / "patch.ppf")
    out_file = str(tmp_path / "output.bin")

    source_bytes = b"UNIVERSAL_PPF_TEST_DATA" * 50
    modified_bytes = b"UNIVERSAL_MOD_TEST_DATA" * 50

    with open(src_file, "wb") as f:
        f.write(source_bytes)
    with open(mod_file, "wb") as f:
        f.write(modified_bytes)

    # Test create_patch auto-detection
    create_patch(src_file, mod_file, patch_file)
    assert os.path.exists(patch_file)

    # Test apply_patch auto-detection
    apply_patch(src_file, patch_file, out_file)
    with open(out_file, "rb") as f:
        assert f.read() == modified_bytes


def test_ppf_error_handling():
    with pytest.raises(PatchError):
        PPFPatcher.parse(b"SHORT")

    with pytest.raises(PatchError):
        PPFPatcher.parse(b"NOTPPF_HEADER_DATA_PADDING_TO_FIFTY_SIX_BYTES_LONG_NOW!")

    with pytest.raises(PatchError):
        PPFPatcher.apply(b"DATA", b"SHORT")
