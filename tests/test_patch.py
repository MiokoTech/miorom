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
