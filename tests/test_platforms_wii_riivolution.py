"""
tests/test_platforms_wii_riivolution.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Nintendo Wii Riivolution XML Mod Engine.
Tests cover:
- Riivolution XML parsing, serialization, and roundtrip fidelity
- Option and choice active patch resolution
- Game ID matching (exact, prefix, and multi-region)
- Automated folder diffing, delta isolation, and mod packaging
- Virtual in-memory WiiDisc patching with file redirects and folder redirects
- CLI integration via miorom patch export-riivolution
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from miorom.core import schema
from miorom.platforms.wii import (
    FileRedirect,
    FolderRedirect,
    RiivolutionFile,
    RiivolutionPatch,
    WiiDisc,
    WiiDiscHeader,
    WiiPartition,
    apply_riivolution_to_disc,
    create_riivolution_package,
)
from miorom.platforms.wii.disc import (
    CLUSTER_SIZE,
    PARTITION_TYPE_DATA,
    WII_COMMON_KEY_RETAIL,
    WII_DISC_MAGIC,
)
from miorom.platforms.wii.u8 import (
    WADTicket,
    WADTmd,
    aes128_cbc_encrypt,
)

SAMPLE_RIIVOLUTION_XML = """<?xml version="1.0" encoding="utf-8"?>
<wiidisc version="1">
  <id game="RMCE" />
  <id game="RMCJ" />
  <region type="E" />
  <options>
    <section name="Translations">
      <option name="Indonesian Language" id="opt_indo" default="1">
        <choice name="Disabled" />
        <choice name="Enabled">
          <patch id="patch_indo_main" />
        </choice>
      </option>
    </section>
  </options>
  <patch id="patch_indo_main">
    <file disc="/Race/Course/LuigiCircuit.szs" external="/MarioKart_Indo/Race/Course/LuigiCircuit.szs" create="true" />
    <file disc="/Text/message.bmg" external="/MarioKart_Indo/Text/message.bmg" offset="0x10" />
    <folder disc="/Scene/UI" external="/MarioKart_Indo/Scene/UI" recursive="true" />
    <memory offset="0x80001800" value="386000014e800020" original="386000004e800020" />
  </patch>
</wiidisc>
"""


def test_riivolution_xml_model_and_roundtrip():
    """Verify parsing and serialization of full Riivolution XML specification."""
    riiv = RiivolutionFile.from_xml(SAMPLE_RIIVOLUTION_XML)

    assert riiv.version == 1
    assert riiv.game_ids == ["RMCE", "RMCJ"]
    assert riiv.regions == ["E"]
    assert len(riiv.sections) == 1

    section = riiv.sections[0]
    assert section.name == "Translations"
    assert len(section.options) == 1

    option = section.options[0]
    assert option.name == "Indonesian Language"
    assert option.id == "opt_indo"
    assert option.default_choice == 1
    assert len(option.choices) == 2
    assert option.choices[0].name == "Disabled"
    assert option.choices[0].patch_ids == []
    assert option.choices[1].name == "Enabled"
    assert option.choices[1].patch_ids == ["patch_indo_main"]

    patch = riiv.get_patch("patch_indo_main")
    assert patch is not None
    assert len(patch.files) == 2
    assert patch.files[0].disc_path == "/Race/Course/LuigiCircuit.szs"
    assert patch.files[0].external_path == "/MarioKart_Indo/Race/Course/LuigiCircuit.szs"
    assert patch.files[0].create is True
    assert patch.files[1].offset == 0x10

    assert len(patch.folders) == 1
    assert patch.folders[0].disc_path == "/Scene/UI"
    assert patch.folders[0].external_path == "/MarioKart_Indo/Scene/UI"
    assert patch.folders[0].recursive is True

    assert len(patch.memory) == 1
    assert patch.memory[0].offset == 0x80001800
    assert patch.memory[0].value == bytes.fromhex("386000014e800020")
    assert patch.memory[0].original == bytes.fromhex("386000004e800020")

    # Verify serialization roundtrip
    serialized = riiv.to_xml(pretty=True)
    assert "<wiidisc" in serialized
    assert 'game="RMCE"' in serialized
    assert 'name="Translations"' in serialized
    assert 'id="patch_indo_main"' in serialized

    reparsed = RiivolutionFile.from_xml(serialized)
    assert reparsed.game_ids == riiv.game_ids
    assert len(reparsed.sections) == 1
    assert len(reparsed.patches) == 1


def test_riivolution_active_patches_and_game_id_matching():
    """Verify option resolution and game ID prefix matching."""
    riiv = RiivolutionFile.from_xml(SAMPLE_RIIVOLUTION_XML)

    # By default, default_choice=1 ('Enabled') should be selected
    default_active = riiv.get_active_patches()
    assert len(default_active) == 1
    assert default_active[0].id == "patch_indo_main"

    # Explicitly select choice 0 ('Disabled')
    disabled_active = riiv.get_active_patches({"opt_indo": 0})
    assert len(disabled_active) == 0

    # Test Game ID matching
    assert riiv.matches_game_id("RMCE01") is True
    assert riiv.matches_game_id("RMCJ01") is True
    assert riiv.matches_game_id("RMCP01") is False  # PAL not in game_ids
    assert riiv.matches_game_id("SMNE01") is False


def test_automated_diffing_and_package_generation():
    """Verify recursive directory diffing, delta asset extraction, and SD card layout generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_dir = Path(tmpdir) / "original"
        mod_dir = Path(tmpdir) / "modified"
        dist_dir = Path(tmpdir) / "sdcard_output"

        orig_dir.mkdir()
        mod_dir.mkdir()

        # 1. Unchanged file (identical content)
        (orig_dir / "root" / "Common.szs").parent.mkdir(parents=True, exist_ok=True)
        (mod_dir / "root" / "Common.szs").parent.mkdir(parents=True, exist_ok=True)
        identical_data = b"IDENTICAL_GAME_ASSET_PAYLOAD_DATA" * 50
        (orig_dir / "root" / "Common.szs").write_bytes(identical_data)
        (mod_dir / "root" / "Common.szs").write_bytes(identical_data)

        # 2. Modified file (different content)
        (orig_dir / "root" / "Race" / "Course.szs").parent.mkdir(parents=True, exist_ok=True)
        (mod_dir / "root" / "Race" / "Course.szs").parent.mkdir(parents=True, exist_ok=True)
        (orig_dir / "root" / "Race" / "Course.szs").write_bytes(b"ORIGINAL_COURSE_DATA")
        (mod_dir / "root" / "Race" / "Course.szs").write_bytes(b"MODIFIED_TRANSLATED_COURSE_DATA_NEW")

        # 3. Newly added file (only in mod_dir)
        (mod_dir / "root" / "Text" / "indo.bmg").parent.mkdir(parents=True, exist_ok=True)
        (mod_dir / "root" / "Text" / "indo.bmg").write_bytes(b"NEW_INDONESIAN_TRANSLATION_BMG")

        # Run packaging engine
        summary = create_riivolution_package(
            original_root=orig_dir,
            modified_root=mod_dir,
            output_dir=dist_dir,
            mod_name="MarioKart_Indo",
            game_ids="RMCE01",
            section_name="Localization",
            option_name="Indonesian Translation",
        )

        assert summary.mod_name == "MarioKart_Indo"
        assert summary.modified_files_count == 1
        assert summary.added_files_count == 1
        assert summary.xml_path.exists()
        assert summary.payload_dir.exists()

        # Verify that unchanged Common.szs was NOT copied
        assert not (summary.payload_dir / "Common.szs").exists()

        # Verify modified and added files were copied
        assert (summary.payload_dir / "Race" / "Course.szs").read_bytes() == b"MODIFIED_TRANSLATED_COURSE_DATA_NEW"
        assert (summary.payload_dir / "Text" / "indo.bmg").read_bytes() == b"NEW_INDONESIAN_TRANSLATION_BMG"

        # Verify generated XML structure
        generated_xml = RiivolutionFile.from_xml(summary.xml_path)
        assert generated_xml.game_ids == ["RMCE01"]
        patch = generated_xml.patches["patch_mariokart_indo"]
        assert len(patch.files) == 2

        disc_paths = {f.disc_path for f in patch.files}
        assert "/Race/Course.szs" in disc_paths
        assert "/Text/indo.bmg" in disc_paths


def _make_minimal_dol() -> bytes:
    """Constructs a minimal valid GameCube/Wii DOL binary with text and data sections."""
    header = bytearray(0x100)
    # text0 at offset 0x100, RAM 0x80003100, size 0x80
    schema.pack_into(">I", header, 0, 0x100)
    schema.pack_into(">I", header, 0x48, 0x80003100)
    schema.pack_into(">I", header, 0x90, 0x80)
    # data0 at offset 0x180, RAM 0x80010000, size 0x40
    schema.pack_into(">I", header, 0x1C, 0x180)
    schema.pack_into(">I", header, 0x64, 0x80010000)
    schema.pack_into(">I", header, 0xAC, 0x40)
    # BSS & entry point
    schema.pack_into(">III", header, 0xD8, 0x80020000, 0x1000, 0x80003100)

    text = b"\x60\x00\x00\x00" * 32  # 32 NOPs
    data = b"\x00" * 0x40
    return bytes(header + text + data)


def _create_synthetic_wii_disc(main_dol: Optional[bytes] = None) -> WiiDisc:
    """Helper to construct a playable synthetic WiiDisc in memory."""
    header = WiiDiscHeader(
        game_id="RMCE",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=False,
        stream_buf_size=0,
        magic=WII_DISC_MAGIC,
        gc_magic=0xC2339F3D,
        game_title="Mario Kart Wii Test",
    )

    title_id = b"\x00\x01\x00\x00RMCE"
    title_key = bytes.fromhex("0102030405060708090a0b0c0d0e0f10")

    tik_raw = bytearray(0x2A4)
    tik_raw[0x1CB : 0x1D3] = title_id
    iv = title_id + (b"\x00" * 8)
    enc_title_key = aes128_cbc_encrypt(title_key, WII_COMMON_KEY_RETAIL, iv)
    tik_raw[0x1F0 : 0x200] = enc_title_key
    ticket = WADTicket.from_bytes(bytes(tik_raw))

    tmd_raw = bytearray(0x1E4 + 36)
    schema.pack_into(">H", tmd_raw, 0x1DE, 1)
    tmd = WADTmd.from_bytes(bytes(tmd_raw))

    part = WiiPartition(
        partition_offset=0x50000,
        partition_type=PARTITION_TYPE_DATA,
        ticket=ticket,
        tmd=tmd,
        title_key=title_key,
        data_offset=0x58000,
        data_size=CLUSTER_SIZE * 2,
        h3_offset=0x51000,
        boot_bin=b"BOOT" + b"\x00" * (0x440 - 4),
        bi2_bin=b"BI2" + b"\x00" * (0x2000 - 3),
        apploader_bin=b"APPLOADER",
        main_dol=main_dol if main_dol is not None else b"MAIN_DOL_BINARY_DATA",
    )
    part["files/Text/message.bmg"] = b"ORIGINAL_ENGLISH_MESSAGE_DATA"
    part["files/Race/Course.szs"] = b"ORIGINAL_COURSE_SZS_DATA"

    return WiiDisc(header=header, partitions=[part])


def test_apply_riivolution_to_disc():
    """Verify in-memory virtual disc patching using Riivolution file redirects and folder redirects."""
    disc = _create_synthetic_wii_disc()

    with tempfile.TemporaryDirectory() as tmpdir:
        ext_root = Path(tmpdir)
        mod_assets = ext_root / "MarioKart_Indo"
        mod_assets.mkdir()

        # Create external replacement file
        (mod_assets / "Text").mkdir()
        (mod_assets / "Text" / "message.bmg").write_bytes(b"TERJEMAHAN_BAHASA_INDONESIA_BERHASIL")

        # Create external folder redirect directory
        (mod_assets / "CustomTracks").mkdir()
        (mod_assets / "CustomTracks" / "Track1.szs").write_bytes(b"CUSTOM_TRACK_1_PAYLOAD")

        patch = RiivolutionPatch(
            id="patch_test",
            files=[
                FileRedirect(
                    disc_path="/Text/message.bmg",
                    external_path="/MarioKart_Indo/Text/message.bmg",
                )
            ],
            folders=[
                FolderRedirect(
                    disc_path="/Race/Tracks",
                    external_path="/MarioKart_Indo/CustomTracks",
                )
            ],
        )
        riiv_file = RiivolutionFile(
            version=1,
            game_ids=["RMCE"],
            patches={"patch_test": patch},
        )

        patched_disc = apply_riivolution_to_disc(
            disc=disc,
            riivolution_file=riiv_file,
            external_root_dir=ext_root,
        )

        part = patched_disc.partitions[0]
        # Assert redirected file replaced content
        assert part["files/Text/message.bmg"] == b"TERJEMAHAN_BAHASA_INDONESIA_BERHASIL"
        # Assert redirected folder mapped new file
        assert part["files/Race/Tracks/Track1.szs"] == b"CUSTOM_TRACK_1_PAYLOAD"
        # Assert unmodified file remained intact
        assert part["files/Race/Course.szs"] == b"ORIGINAL_COURSE_SZS_DATA"


def test_riivolution_cli_export():
    """Verify miorom patch export-riivolution CLI integration."""
    # Test through Python main CLI entry point
    from miorom.cli.main import main

    with tempfile.TemporaryDirectory() as tmpdir:
        orig_dir = os.path.join(tmpdir, "orig")
        mod_dir = os.path.join(tmpdir, "mod")
        out_dir = os.path.join(tmpdir, "sdcard")

        os.makedirs(os.path.join(orig_dir, "root"), exist_ok=True)
        os.makedirs(os.path.join(mod_dir, "root"), exist_ok=True)

        with open(os.path.join(orig_dir, "root", "file.bin"), "wb") as f:
            f.write(b"ORIG")
        with open(os.path.join(mod_dir, "root", "file.bin"), "wb") as f:
            f.write(b"MODIFIED")

        # Invoke CLI: miorom patch export-riivolution --orig ... --mod ... --name MyMod --id RMCE01 -o ...
        # Note: cli/main.py uses sys.argv if not using click, or argparse directly
        import sys
        old_argv = sys.argv
        try:
            sys.argv = [
                "miorom",
                "patch",
                "export-riivolution",
                "--orig",
                orig_dir,
                "--mod",
                mod_dir,
                "--name",
                "TestMod",
                "--id",
                "RMCE01",
                "-o",
                out_dir,
            ]
            # Call main()
            main()
        finally:
            sys.argv = old_argv

        # Check output files exist
        assert os.path.isfile(os.path.join(out_dir, "riivolution", "TestMod.xml"))
        assert os.path.isfile(os.path.join(out_dir, "TestMod", "file.bin"))
        with open(os.path.join(out_dir, "TestMod", "file.bin"), "rb") as f:
            assert f.read() == b"MODIFIED"


def test_riivolution_cli_apply():
    """Verify miorom patch apply-riivolution CLI integration."""
    import sys

    from miorom.cli.main import main

    disc = _create_synthetic_wii_disc()

    with tempfile.TemporaryDirectory() as tmpdir:
        disc_path = os.path.join(tmpdir, "input.iso")
        with open(disc_path, "wb") as f:
            f.write(disc.to_bytes())

        # Create external asset
        mod_asset_dir = os.path.join(tmpdir, "MyMod", "Text")
        os.makedirs(mod_asset_dir, exist_ok=True)
        asset_file = os.path.join(mod_asset_dir, "message.bmg")
        with open(asset_file, "wb") as f:
            f.write(b"CLI_APPLIED_TRANSLATED_MESSAGE")

        # Create XML
        xml_path = os.path.join(tmpdir, "mod.xml")
        riiv_xml = """<?xml version="1.0" encoding="utf-8"?>
<wiidisc version="1">
  <id game="RMCE" />
  <patch id="p1">
    <file disc="/Text/message.bmg" external="/MyMod/Text/message.bmg" />
  </patch>
</wiidisc>
"""
        with open(xml_path, "w") as f:
            f.write(riiv_xml)

        out_patched = os.path.join(tmpdir, "patched.iso")

        old_argv = sys.argv
        try:
            sys.argv = [
                "miorom",
                "patch",
                "apply-riivolution",
                "--disc",
                disc_path,
                "--xml",
                xml_path,
                "--root",
                tmpdir,
                "-o",
                out_patched,
            ]
            main()
        finally:
            sys.argv = old_argv

        assert os.path.isfile(out_patched)
        loaded = WiiDisc.from_file(out_patched)
        assert loaded.partitions[0]["files/Text/message.bmg"] == b"CLI_APPLIED_TRANSLATED_MESSAGE"


def test_apply_riivolution_offset_and_resize_rules():
    """Verify offset partial replacement, dictionary get() access, and resize=False zero padding/truncation."""
    disc = _create_synthetic_wii_disc()
    part = disc.partitions[0]
    # Set initial test files
    part["files/Data/fixed.bin"] = b"1234567890ABCDEF"  # 16 bytes
    part["files/Data/short.bin"] = b"12345678901234567890123456789012"  # 32 bytes

    with tempfile.TemporaryDirectory() as tmpdir:
        ext_root = Path(tmpdir)
        mod_dir = ext_root / "Mod"
        mod_dir.mkdir()

        # 1. Partial offset replacement (offset=4, 4 bytes)
        (mod_dir / "patch_offset.bin").write_bytes(b"XXXX")

        # 2. resize=False with larger external file (20 bytes replacing 16-byte fixed.bin -> truncated to 16 bytes)
        (mod_dir / "oversized.bin").write_bytes(b"ABCDEFGHIJKLMNOPQRST")  # 20 bytes

        # 3. resize=False with smaller external file (10 bytes replacing 32-byte short.bin -> zero-padded to 32 bytes)
        (mod_dir / "undersized.bin").write_bytes(b"SHORT_DATA")  # 10 bytes

        # Test offset redirect on fixed.bin first
        patch_offset_only = RiivolutionPatch(
            id="p_off",
            files=[
                FileRedirect(
                    disc_path="/Data/fixed.bin",
                    external_path="/Mod/patch_offset.bin",
                    offset=4,
                )
            ],
        )
        riiv_off = RiivolutionFile(version=1, game_ids=["RMCE"], patches={"p_off": patch_offset_only})
        apply_riivolution_to_disc(disc, riiv_off, ext_root)
        # Bytes 0..4 = "1234", 4..8 = "XXXX", 8..16 = "90ABCDEF"
        assert part["files/Data/fixed.bin"] == b"1234XXXX90ABCDEF"
        # Test WiiPartition.get() works as expected
        assert part.get("files/Data/fixed.bin") == b"1234XXXX90ABCDEF"
        assert part.get("files/NonExistent.bin", b"DEFAULT") == b"DEFAULT"

        # Test oversized file with resize=False (should be truncated to 16 bytes)
        patch_resize_large = RiivolutionPatch(
            id="p_large",
            files=[
                FileRedirect(
                    disc_path="/Data/fixed.bin",
                    external_path="/Mod/oversized.bin",
                    resize=False,
                )
            ],
        )
        riiv_large = RiivolutionFile(version=1, game_ids=["RMCE"], patches={"p_large": patch_resize_large})
        apply_riivolution_to_disc(disc, riiv_large, ext_root)
        assert len(part["files/Data/fixed.bin"]) == 16
        assert part["files/Data/fixed.bin"] == b"ABCDEFGHIJKLMNOP"

        # Test undersized file with resize=False (should be zero-padded to 32 bytes)
        patch_resize_small = RiivolutionPatch(
            id="p_small",
            files=[
                FileRedirect(
                    disc_path="/Data/short.bin",
                    external_path="/Mod/undersized.bin",
                    resize=False,
                )
            ],
        )
        riiv_small = RiivolutionFile(version=1, game_ids=["RMCE"], patches={"p_small": patch_resize_small})
        apply_riivolution_to_disc(disc, riiv_small, ext_root)
        assert len(part["files/Data/short.bin"]) == 32
        assert part["files/Data/short.bin"] == b"SHORT_DATA" + (b"\x00" * 22)


def test_apply_riivolution_create_flag_and_folder_recursive_rules():
    """Verify create=False disc preservation and folder recursive=False isolation."""
    disc = _create_synthetic_wii_disc()
    part = disc.partitions[0]
    part["files/Existing/file.bin"] = b"EXISTING_DATA"

    with tempfile.TemporaryDirectory() as tmpdir:
        ext_root = Path(tmpdir)
        mod_dir = ext_root / "Mod"
        mod_dir.mkdir()

        (mod_dir / "new_standalone.bin").write_bytes(b"NEW_STANDALONE")
        (mod_dir / "allowed_new.bin").write_bytes(b"ALLOWED_NEW")

        # Folder structure with subdirectories
        folder_dir = mod_dir / "FolderTest"
        folder_dir.mkdir()
        (folder_dir / "top.bin").write_bytes(b"TOP_LEVEL")
        (folder_dir / "nested").mkdir()
        (folder_dir / "nested" / "sub.bin").write_bytes(b"SUB_LEVEL")

        patch = RiivolutionPatch(
            id="p_rules",
            files=[
                # create=False on non-existent file -> should NOT create
                FileRedirect(
                    disc_path="/New/should_not_exist.bin",
                    external_path="/Mod/new_standalone.bin",
                    create=False,
                ),
                # create=True on non-existent file -> SHOULD create
                FileRedirect(
                    disc_path="/New/allowed.bin",
                    external_path="/Mod/allowed_new.bin",
                    create=True,
                ),
            ],
            folders=[
                # recursive=False -> only top.bin mapped, nested/sub.bin ignored
                FolderRedirect(
                    disc_path="/Dir",
                    external_path="/Mod/FolderTest",
                    recursive=False,
                    create=True,
                )
            ],
        )

        riiv = RiivolutionFile(version=1, game_ids=["RMCE"], patches={"p_rules": patch})
        apply_riivolution_to_disc(disc, riiv, ext_root)

        # File with create=False must not exist
        assert "files/New/should_not_exist.bin" not in part
        # File with create=True must exist
        assert part["files/New/allowed.bin"] == b"ALLOWED_NEW"

        # Folder with recursive=False: top level file exists, nested file does NOT
        assert part["files/Dir/top.bin"] == b"TOP_LEVEL"
        assert "files/Dir/nested/sub.bin" not in part


def test_apply_riivolution_memory_patch_to_dol():
    """Verify DolFile memory patching, original byte verification, and out-of-bounds safety."""
    from miorom.platforms.gc.dol import DolFile

    dol_bytes = _make_minimal_dol()
    disc = _create_synthetic_wii_disc(main_dol=dol_bytes)
    part = disc.partitions[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        from miorom.platforms.wii.riivolution import MemoryPatch

        patch = RiivolutionPatch(
            id="p_mem",
            memory=[
                # 1. Matching original -> should be applied
                MemoryPatch(
                    offset=0x80003100,
                    value=bytes.fromhex("386000014E800020"),  # li r3, 1; blr
                    original=bytes.fromhex("6000000060000000"),  # nop; nop
                ),
                # 2. Mismatching original -> should NOT be applied
                MemoryPatch(
                    offset=0x80003108,
                    value=bytes.fromhex("DEADBEEF"),
                    original=bytes.fromhex("FFFFFFFF"),  # actual is 60000000
                ),
                # 3. Memory address out of DOL range -> handled gracefully without crash
                MemoryPatch(
                    offset=0x95000000,
                    value=bytes.fromhex("11223344"),
                ),
            ],
        )

        riiv = RiivolutionFile(version=1, game_ids=["RMCE"], patches={"p_mem": patch})
        apply_riivolution_to_disc(disc, riiv, tmpdir, apply_memory_to_dol=True)

        # Re-parse DOL from partition and verify modified instructions
        updated_dol = DolFile.from_bytes(part.main_dol)
        assert updated_dol.read_memory(0x80003100, 8) == bytes.fromhex("386000014E800020")
        # Offset 0x80003108 was skipped due to original mismatch
        assert updated_dol.read_memory(0x80003108, 4) == bytes.fromhex("60000000")


def test_riivolution_package_asymmetric_directory_layouts():
    """Verify package diffing when original directory uses 'root/' and modified is flat."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_dir = Path(tmpdir) / "original"
        mod_dir = Path(tmpdir) / "modified"
        out_dir = Path(tmpdir) / "pkg_out"
        orig_dir.mkdir()
        mod_dir.mkdir()

        # Original has 'root/Race/Course.szs'
        (orig_dir / "root" / "Race").mkdir(parents=True)
        (orig_dir / "root" / "Race" / "Course.szs").write_bytes(b"IDENTICAL_CONTENT")

        # Modified is flat 'Race/Course.szs' and adds 'Race/New.szs'
        (mod_dir / "Race").mkdir(parents=True)
        (mod_dir / "Race" / "Course.szs").write_bytes(b"IDENTICAL_CONTENT")
        (mod_dir / "Race" / "New.szs").write_bytes(b"NEW_CONTENT")

        summary = create_riivolution_package(
            original_root=orig_dir,
            modified_root=mod_dir,
            output_dir=out_dir,
            mod_name="FlatTest",
            game_ids="RMCE01",
        )

        # Identical Course.szs should be omitted from delta
        assert summary.modified_files_count == 0
        assert summary.added_files_count == 1
        assert not (summary.payload_dir / "Race" / "Course.szs").exists()
        assert (summary.payload_dir / "Race" / "New.szs").read_bytes() == b"NEW_CONTENT"
