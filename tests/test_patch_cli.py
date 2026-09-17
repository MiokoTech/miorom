import os
import tempfile

from miorom.patch import apply_patch, create_patch, inspect_patch


def test_create_and_apply_all_formats():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_file = os.path.join(tmpdir, "orig.bin")
        mod_file = os.path.join(tmpdir, "mod.bin")

        orig_data = b"MioROM Original ROM Data Block 1234567890" * 20
        mod_data = b"MioROM Modified ROM Data Block 1234567890" * 20

        with open(orig_file, "wb") as f:
            f.write(orig_data)
        with open(mod_file, "wb") as f:
            f.write(mod_data)

        for fmt in ["bps", "ips", "ups", "ppf"]:
            patch_file = os.path.join(tmpdir, f"patch.{fmt}")
            applied_file = os.path.join(tmpdir, f"applied_{fmt}.bin")

            # 1. Create patch
            create_patch(orig_file, mod_file, patch_file, fmt=fmt)
            assert os.path.exists(patch_file)
            assert os.path.getsize(patch_file) > 0

            # 2. Inspect patch
            info = inspect_patch(patch_file)
            assert info["format"] == fmt.upper()
            assert info["file_size"] > 0
            if "is_patch_valid" in info:
                assert info["is_patch_valid"] is True

            # 3. Apply patch (with auto-detecting format from file contents)
            apply_patch(orig_file, patch_file, applied_file)
            assert os.path.exists(applied_file)
            with open(applied_file, "rb") as f:
                res_data = f.read()
            assert res_data == mod_data, f"Data mismatch for format {fmt}"


def test_inspect_patch_diagnostics():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_file = os.path.join(tmpdir, "orig.bin")
        mod_file = os.path.join(tmpdir, "mod.bin")

        with open(orig_file, "wb") as f:
            f.write(b"A" * 100)
        with open(mod_file, "wb") as f:
            f.write(b"B" * 100)

        # Test BPS inspection
        bps_file = os.path.join(tmpdir, "test.bps")
        create_patch(orig_file, mod_file, bps_file, fmt="bps")
        info = inspect_patch(bps_file)
        assert info["format"] == "BPS"
        assert info["source_size"] == 100
        assert info["target_size"] == 100
        assert info["is_patch_valid"] is True

        # Test UPS inspection
        ups_file = os.path.join(tmpdir, "test.ups")
        create_patch(orig_file, mod_file, ups_file, fmt="ups")
        info = inspect_patch(ups_file)
        assert info["format"] == "UPS"
        assert info["source_size"] == 100
        assert info["target_size"] == 100
        assert info["is_patch_valid"] is True

        # Test PPF inspection
        ppf_file = os.path.join(tmpdir, "test.ppf")
        create_patch(orig_file, mod_file, ppf_file, fmt="ppf")
        info = inspect_patch(ppf_file)
        assert info["format"] == "PPF"
        assert info["version"] == 3
        assert info["record_count"] >= 1
