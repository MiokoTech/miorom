import struct
import pytest
from miorom.platforms.gc import GameCubeDisc, GCHeader, FSTEntry


def build_synthetic_gc_disc():
    """Build a minimal valid GameCube disc image in memory with an FST."""
    disc_data = bytearray(0x500000)

    # Header
    header = GCHeader(
        game_id="GALE",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=False,
        stream_buf_size=0,
        magic=0xC2339F3D,
        game_title="Super Smash Bros Melee",
        dol_offset=0x10000,
        fst_offset=0x450000,
        fst_size=0,
        fst_max_size=0x10000,
        user_pos=0x460000,
        user_length=0x1000,
    )
    disc_data[:0x440] = header.pack()

    # Mock DOL executable at dol_offset (0x10000)
    dol_hdr = bytearray(0x100)
    struct.pack_into(">I", dol_hdr, 0x00, 0x100)       # text_offset[0]
    struct.pack_into(">I", dol_hdr, 0x48, 0x80003100)  # text_addr[0]
    struct.pack_into(">I", dol_hdr, 0x90, 0x200)       # text_size[0]
    disc_data[0x10000:0x10100] = dol_hdr
    disc_data[0x10100:0x10300] = b"ORIGINAL_DOL_CODE" * 16

    # Build initial FST with 2 entries:
    # 0: Root directory (total entries: 3)
    # 1: dir "script" (parent: 0, next: 3)
    # 2: file "dialogue.bin" inside script (parent: 1, offset: 0x460000, size: 12)
    str_table = b"script\x00dialogue.bin\x00"
    entries_data = bytearray()

    # Entry 0: Root
    entries_data.extend(struct.pack(">III", 0x01000000, 0, 3))
    # Entry 1: Dir "script" (name_off = 0)
    entries_data.extend(struct.pack(">III", 0x01000000, 0, 3))
    # Entry 2: File "dialogue.bin" (name_off = 7, offset = 0x460000, size = 12)
    entries_data.extend(struct.pack(">III", 0x00000007, 0x460000, 12))

    full_fst = entries_data + str_table
    header.fst_size = len(full_fst)
    disc_data[0x428:0x42C] = struct.pack(">I", len(full_fst))
    disc_data[0x450000:0x450000 + len(full_fst)] = full_fst

    # File data
    disc_data[0x460000:0x460000 + 12] = b"HELLO_MELEE!"

    return bytes(disc_data)


def test_gc_header_parse_and_pack():
    disc_bytes = build_synthetic_gc_disc()
    header = GCHeader.parse(disc_bytes[:0x440])

    assert header.game_id == "GALE"
    assert header.maker_code == "01"
    assert header.game_title == "Super Smash Bros Melee"
    assert header.magic == 0xC2339F3D
    assert header.fst_offset == 0x450000

    packed = header.pack()
    assert packed[:4] == b"GALE"
    assert packed[4:6] == b"01"
    assert struct.unpack_from(">I", packed, 0x1C)[0] == 0xC2339F3D


def test_gc_disc_read_files():
    disc_bytes = build_synthetic_gc_disc()
    disc = GameCubeDisc(disc_bytes)

    assert len(disc.entries) == 3
    assert "script/dialogue.bin" in disc.files
    assert disc.read_file("script/dialogue.bin") == b"HELLO_MELEE!"


def test_gc_disc_replace_and_rebuild():
    disc_bytes = build_synthetic_gc_disc()
    disc = GameCubeDisc(disc_bytes)

    # Replace file with new content
    new_text = b"EXPANDED_TRANSLATED_DIALOGUE_TEXT_123456789"
    disc.replace_file("script/dialogue.bin", new_text)

    # Add a new file in a new directory
    disc.add_file("sound/bgm.adp", b"AUDIO_STREAM_DATA")

    rebuilt_bytes = disc.to_bytes(alignment=32)

    # Reload the rebuilt disc
    reloaded = GameCubeDisc(rebuilt_bytes)

    assert reloaded.read_file("script/dialogue.bin") == new_text
    assert reloaded.read_file("sound/bgm.adp") == b"AUDIO_STREAM_DATA"
    assert reloaded.header.fst_size > 0
    assert reloaded.header.user_length > 0


def test_gc_disc_save_and_load(tmp_path):
    disc_bytes = build_synthetic_gc_disc()
    disc = GameCubeDisc(disc_bytes)
    disc.replace_file("script/dialogue.bin", b"NEW_DATA")

    out_iso = tmp_path / "game.iso"
    disc.save(str(out_iso))

    loaded = GameCubeDisc.from_file(str(out_iso))
    assert loaded.read_file("script/dialogue.bin") == b"NEW_DATA"


def test_gc_rom_handler_main_dol_and_header_modification(tmp_path):
    import os
    from miorom.rom.handlers.gc import GameCubeRomHandler

    handler = GameCubeRomHandler()
    disc_bytes = build_synthetic_gc_disc()
    unpacked_dir = tmp_path / "gc_extracted"

    # Unpack GameCube disc
    meta = handler.unpack(disc_bytes, str(unpacked_dir))
    assert meta["game_id"] == "GALE"
    assert meta["file_count"] == 1

    # Verify extracted system files
    sys_dir = unpacked_dir / "sys"
    assert (sys_dir / "header.bin").is_file()
    assert (sys_dir / "disc_base.bin").is_file()
    assert (sys_dir / "main.dol").is_file()

    # Read extracted main.dol and verify it contains original code
    with open(sys_dir / "main.dol", "rb") as f:
        extracted_dol = f.read()
    assert b"ORIGINAL_DOL_CODE" in extracted_dol

    # 1. Modify sys/main.dol (code cave / ASM patch)
    patched_dol = bytearray(extracted_dol)
    patched_dol = patched_dol.replace(b"ORIGINAL_DOL_CODE", b"PATCHED_DOL_HACK")
    with open(sys_dir / "main.dol", "wb") as f:
        f.write(patched_dol)

    # 2. Modify sys/header.bin (game title / ID)
    with open(sys_dir / "header.bin", "rb") as f:
        hdr = GCHeader.parse(f.read())
    hdr.game_title = "Melee Modified Mod"
    hdr.game_id = "GALM"
    with open(sys_dir / "header.bin", "wb") as f:
        f.write(hdr.pack())

    # 3. Modify root file
    root_dir = unpacked_dir / "root"
    with open(root_dir / "script" / "dialogue.bin", "wb") as f:
        f.write(b"TRANSLATED_TEXT_IN_REPACK")

    # Repack into new ISO
    repacked_bytes = handler.repack(str(unpacked_dir))

    # Parse repacked ISO and verify all modifications were applied
    repacked_disc = GameCubeDisc(repacked_bytes)
    assert repacked_disc.header.game_id == "GALM"
    assert repacked_disc.header.game_title == "Melee Modified Mod"
    assert repacked_disc.read_file("script/dialogue.bin") == b"TRANSLATED_TEXT_IN_REPACK"

    # Verify DOL at dol_offset contains the injected patched code
    dol_offset = repacked_disc.header.dol_offset
    assert repacked_disc.raw_data[dol_offset : dol_offset + len(patched_dol)] == patched_dol
    assert b"PATCHED_DOL_HACK" in repacked_disc.raw_data
