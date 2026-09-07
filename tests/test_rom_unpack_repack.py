import os
import struct
import tempfile
import pytest

from miorom import (
    RomManager,
    unpack_rom,
    repack_rom,
    NDSRom,
    GameCubeDisc,
    U8Archive,
    NARCArchive,
    ISO9660,
    GBARom,
)
from miorom.rom.handlers.nds import calculate_nds_crc16, build_nds_fnt, parse_nds_fnt
from miorom.platforms.gc.disc import GCHeader


def test_nds_fnt_build_and_parse_deep():
    files = [
        "data/script/event01.bin",
        "data/script/event02.bin",
        "data/text/message.msg",
        "sound/bgm01.sseq",
        "sound/se01.sdat",
        "root_file.txt",
    ]
    fnt_bytes, ordered_files = build_nds_fnt(files)
    assert len(fnt_bytes) > 0
    assert len(ordered_files) == len(files)

    parsed_map = parse_nds_fnt(fnt_bytes)
    assert len(parsed_map) == len(files)
    assert set(parsed_map.values()) == set(files)


def test_nds_unpack_and_repack_roundtrip():
    # Build a synthetic NDS ROM
    raw = bytearray(0x5000)
    raw[0:12] = b"TESTGAME\x00\x00\x00\x00"
    raw[12:16] = b"ATSE"
    raw[16:18] = b"01"
    raw[18] = 0x00  # unit code

    # ARM9 & ARM7 info
    arm9_content = b"\x12\x34\x56\x78" * 32
    arm7_content = b"\xAA\xBB\xCC\xDD" * 16

    struct.pack_into("<I", raw, 0x20, 0x200)   # arm9_offset
    struct.pack_into("<I", raw, 0x24, 0x02000000)  # arm9_entry
    struct.pack_into("<I", raw, 0x28, 0x02000000)  # arm9_ram
    struct.pack_into("<I", raw, 0x2C, len(arm9_content))  # arm9_size
    raw[0x200 : 0x200 + len(arm9_content)] = arm9_content

    struct.pack_into("<I", raw, 0x30, 0x300)   # arm7_offset
    struct.pack_into("<I", raw, 0x34, 0x02380000)
    struct.pack_into("<I", raw, 0x38, 0x02380000)
    struct.pack_into("<I", raw, 0x3C, len(arm7_content))
    raw[0x300 : 0x300 + len(arm7_content)] = arm7_content

    # FNT & FAT
    test_files = {
        "dialogue/intro.txt": b"Hello Rune Factory!",
        "system/config.bin": b"CONFIG_DATA_BYTES_12345",
    }
    fnt_bytes, ordered_files = build_nds_fnt(list(test_files.keys()))
    fnt_off = 0x400
    struct.pack_into("<II", raw, 0x40, fnt_off, len(fnt_bytes))
    raw[fnt_off : fnt_off + len(fnt_bytes)] = fnt_bytes

    fat_off = 0x600
    fat_size = len(ordered_files) * 8
    struct.pack_into("<II", raw, 0x48, fat_off, fat_size)

    file_cur = 0x1000
    for i, (_, rel_p) in enumerate(ordered_files):
        p_bytes = test_files[rel_p]
        start = file_cur
        end = start + len(p_bytes)
        struct.pack_into("<II", raw, fat_off + (i * 8), start, end)
        raw[start:end] = p_bytes
        file_cur += len(p_bytes) + 32

    # Calculate CRC16
    crc = calculate_nds_crc16(bytes(raw[:0x15E]))
    struct.pack_into("<H", raw, 0x15E, crc)

    with tempfile.TemporaryDirectory() as tmpdir:
        nds_file = os.path.join(tmpdir, "game.nds")
        with open(nds_file, "wb") as f:
            f.write(raw)

        unpacked_dir = os.path.join(tmpdir, "unpacked_nds")
        meta = unpack_rom(nds_file, unpacked_dir)
        assert meta["format"] == "nds"
        assert meta["title"] == "TESTGAME"
        assert meta["file_count"] == 2

        # Check unpacked files
        txt_path = os.path.join(unpacked_dir, "root", "dialogue", "intro.txt")
        assert os.path.isfile(txt_path)
        with open(txt_path, "rb") as f:
            assert f.read() == b"Hello Rune Factory!"

        # Modify a file
        with open(txt_path, "wb") as f:
            f.write(b"Translated Dialogue String!")

        # Repack
        repacked_file = os.path.join(tmpdir, "repacked.nds")
        repacked_bytes = repack_rom(unpacked_dir, repacked_file)
        assert len(repacked_bytes) > 0
        assert os.path.isfile(repacked_file)

        # Inspect repacked ROM with NDSRom
        rom_re = NDSRom.from_file(repacked_file)
        assert rom_re.title == "TESTGAME"
        assert rom_re.get_arm9_binary() == arm9_content
        assert rom_re.get_arm7_binary() == arm7_content

        files_re = rom_re.list_files()
        assert len(files_re) == 2
        assert rom_re.get_file(0) == b"Translated Dialogue String!" or rom_re.get_file(1) == b"Translated Dialogue String!"


def test_gamecube_unpack_and_repack_roundtrip():
    # Build a synthetic GameCube disc
    header = GCHeader(
        game_id="GM8E",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=True,
        stream_buf_size=0,
        magic=GameCubeDisc.GC_MAGIC,
        game_title="Super Mario Sunshine",
        dol_offset=0,
        fst_offset=0x450000,
        fst_size=0,
        fst_max_size=0x100000,
        user_pos=0x500000,
        user_length=0,
    )
    raw = bytearray(0x450000)
    raw[:0x440] = header.pack()

    disc = GameCubeDisc(bytes(raw))
    disc.add_file("stage/world1.bin", b"WORLD_1_DATA")
    disc.add_file("audio/bgm.adp", b"MUSIC_AUDIO_TRACK_DATA")
    disc_bytes = disc.to_bytes()

    with tempfile.TemporaryDirectory() as tmpdir:
        iso_file = os.path.join(tmpdir, "game.iso")
        with open(iso_file, "wb") as f:
            f.write(disc_bytes)

        unpacked_dir = os.path.join(tmpdir, "unpacked_gc")
        meta = unpack_rom(iso_file, unpacked_dir)
        assert meta["format"] == "gamecube"
        assert meta["game_id"] == "GM8E"
        assert meta["file_count"] == 2

        # Check extracted file
        w1_path = os.path.join(unpacked_dir, "root", "stage", "world1.bin")
        assert os.path.isfile(w1_path)
        with open(w1_path, "rb") as f:
            assert f.read() == b"WORLD_1_DATA"

        # Modify file
        with open(w1_path, "wb") as f:
            f.write(b"WORLD_1_MODIFIED_TEXTURES")

        # Repack
        repacked_iso = os.path.join(tmpdir, "repacked.iso")
        repacked_bytes = repack_rom(unpacked_dir, repacked_iso)
        assert len(repacked_bytes) > 0

        # Inspect repacked disc
        disc_re = GameCubeDisc(repacked_bytes)
        assert disc_re.header.game_id == "GM8E"
        assert disc_re.read_file("stage/world1.bin") == b"WORLD_1_MODIFIED_TEXTURES"
        assert disc_re.read_file("audio/bgm.adp") == b"MUSIC_AUDIO_TRACK_DATA"


def test_u8_unpack_and_repack_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = os.path.join(tmpdir, "src_u8")
        os.makedirs(os.path.join(src_dir, "models"), exist_ok=True)
        with open(os.path.join(src_dir, "models", "hero.brres"), "wb") as f:
            f.write(b"HERO_3D_MODEL_DATA")
        with open(os.path.join(src_dir, "info.txt"), "wb") as f:
            f.write(b"Archive Info")

        arc_file = os.path.join(tmpdir, "test.arc")
        U8Archive.pack(src_dir, arc_file)

        unpacked_dir = os.path.join(tmpdir, "unpacked_u8")
        meta = unpack_rom(arc_file, unpacked_dir)
        assert meta["format"] == "u8"
        assert meta["file_count"] == 2

        # Check extracted file
        hero_file = os.path.join(unpacked_dir, "root", "models", "hero.brres")
        assert os.path.isfile(hero_file)
        with open(hero_file, "rb") as f:
            assert f.read() == b"HERO_3D_MODEL_DATA"

        # Modify file
        with open(hero_file, "wb") as f:
            f.write(b"MODDED_HERO_MODEL")

        # Repack
        repacked_arc = os.path.join(tmpdir, "repacked.arc")
        repacked_data = repack_rom(unpacked_dir, repacked_arc)
        assert U8Archive.is_u8(repacked_data)

        # Unpack again to verify
        verify_dir = os.path.join(tmpdir, "verify_u8")
        U8Archive.extract_all(repacked_arc, verify_dir)
        with open(os.path.join(verify_dir, "models", "hero.brres"), "rb") as f:
            assert f.read() == b"MODDED_HERO_MODEL"


def test_narc_unpack_and_repack_roundtrip():
    payloads = [b"TEXT_0", b"TEXT_1_MORE_DATA", b"TEXTURE_RAW_BYTES"]
    narc_bytes = NARCArchive.pack_files(payloads)

    with tempfile.TemporaryDirectory() as tmpdir:
        narc_file = os.path.join(tmpdir, "archive.narc")
        with open(narc_file, "wb") as f:
            f.write(narc_bytes)

        unpacked_dir = os.path.join(tmpdir, "unpacked_narc")
        meta = unpack_rom(narc_file, unpacked_dir)
        assert meta["format"] == "narc"
        assert meta["file_count"] == 3

        # Modify first file
        file0_path = os.path.join(unpacked_dir, "root", "file_0000.bin")
        with open(file0_path, "wb") as f:
            f.write(b"MODIFIED_TEXT_0")

        # Repack
        repacked_narc = os.path.join(tmpdir, "repacked.narc")
        repack_rom(unpacked_dir, repacked_narc)

        with open(repacked_narc, "rb") as f:
            re_entries = NARCArchive.unpack_entries(f.read())
        assert len(re_entries) == 3
        assert re_entries[0].data == b"MODIFIED_TEXT_0"
        assert re_entries[1].data == payloads[1]


def test_cartridge_unpack_and_repack_roundtrip():
    # Synthetic GBA ROM
    raw_gba = bytearray(0x200)
    raw_gba[4:4 + len(GBARom.NINTENDO_LOGO)] = GBARom.NINTENDO_LOGO
    raw_gba[0xA0:0xAC] = b"POKEMON_EM\x00\x00"
    raw_gba[0xAC:0xB0] = b"BPEE"
    raw_gba[0xB0:0xB2] = b"01"
    rom = GBARom(bytes(raw_gba))
    rom.fix_checksum()
    original_checksum = rom.header_checksum

    with tempfile.TemporaryDirectory() as tmpdir:
        gba_file = os.path.join(tmpdir, "game.gba")
        with open(gba_file, "wb") as f:
            f.write(rom.data)

        unpacked_dir = os.path.join(tmpdir, "unpacked_gba")
        meta = unpack_rom(gba_file, unpacked_dir)
        assert meta["format"] == "cartridge"
        assert meta["subplatform"] == "gba"
        assert meta["title"] == "POKEMON_EM"

        # Change title in rom.bin
        rom_bin = os.path.join(unpacked_dir, "rom.bin")
        with open(rom_bin, "rb") as f:
            d = bytearray(f.read())
        d[0xA0:0xAC] = b"POKEMON_MOD\x00"
        with open(rom_bin, "wb") as f:
            f.write(d)

        # Repack
        repacked_gba = os.path.join(tmpdir, "repacked.gba")
        repacked_bytes = repack_rom(unpacked_dir, repacked_gba)

        rom_re = GBARom(repacked_bytes)
        assert rom_re.title == "POKEMON_MOD"
        assert rom_re.validate_checksum() is True


def test_iso9660_unpack_and_repack_roundtrip():
    sector_size = 2048
    iso_data = bytearray(sector_size * 20)

    # Setup PVD at sector 16
    pvd_offset = 16 * sector_size
    iso_data[pvd_offset : pvd_offset + 6] = b"\x01CD001"
    iso_data[pvd_offset + 6] = 1
    iso_data[pvd_offset + 40 : pvd_offset + 50] = b"TEST_DISC "
    struct.pack_into("<I", iso_data, pvd_offset + 80, 20)
    struct.pack_into(">I", iso_data, pvd_offset + 84, 20)
    struct.pack_into("<H", iso_data, pvd_offset + 128, 2048)
    struct.pack_into(">H", iso_data, pvd_offset + 130, 2048)

    # Root dir record in PVD (offset 156)
    root_rec = pvd_offset + 156
    iso_data[root_rec] = 34
    struct.pack_into("<I", iso_data, root_rec + 2, 17)
    struct.pack_into("<I", iso_data, root_rec + 10, 2048)

    # Setup Root Directory Sector at sector 17
    root_dir_offset = 17 * sector_size
    file_lba = 18
    file_content = b"Original ISO File Content"
    file_name = b"DATA.BIN;1"

    rec_len = 33 + len(file_name)
    if rec_len % 2 != 0:
        rec_len += 1

    entry_offset = root_dir_offset
    iso_data[entry_offset] = rec_len
    struct.pack_into("<I", iso_data, entry_offset + 2, file_lba)
    struct.pack_into(">I", iso_data, entry_offset + 6, file_lba)
    struct.pack_into("<I", iso_data, entry_offset + 10, len(file_content))
    struct.pack_into(">I", iso_data, entry_offset + 14, len(file_content))
    iso_data[entry_offset + 25] = 0
    iso_data[entry_offset + 32] = len(file_name)
    iso_data[entry_offset + 33 : entry_offset + 33 + len(file_name)] = file_name

    iso_data[18 * sector_size : 18 * sector_size + len(file_content)] = file_content

    with tempfile.TemporaryDirectory() as tmpdir:
        iso_file = os.path.join(tmpdir, "disc.iso")
        with open(iso_file, "wb") as f:
            f.write(iso_data)

        unpacked_dir = os.path.join(tmpdir, "unpacked_iso")
        meta = unpack_rom(iso_file, unpacked_dir)
        assert meta["format"] == "iso9660"
        assert meta["file_count"] == 1

        fpath = os.path.join(unpacked_dir, "root", "DATA.BIN")
        assert os.path.isfile(fpath)
        with open(fpath, "rb") as f:
            assert f.read() == file_content

        # Modify file
        with open(fpath, "wb") as f:
            f.write(b"Modified Content in ISO9660")

        # Repack
        repacked_iso = os.path.join(tmpdir, "repacked.iso")
        repack_rom(unpacked_dir, repacked_iso)

        # Verify
        iso_re = ISO9660.from_file(repacked_iso)
        assert iso_re.read_file("DATA.BIN") == b"Modified Content in ISO9660"


def test_cli_unpack_and_repack(monkeypatch, capsys):
    from miorom.cli.main import main

    payloads = [b"CLI_FILE_A", b"CLI_FILE_B"]
    narc_bytes = NARCArchive.pack_files(payloads)

    with tempfile.TemporaryDirectory() as tmpdir:
        narc_path = os.path.join(tmpdir, "cli_test.narc")
        with open(narc_path, "wb") as f:
            f.write(narc_bytes)

        out_dir = os.path.join(tmpdir, "cli_unpacked")
        # Test CLI unpack
        monkeypatch.setattr("sys.argv", ["miorom", "unpack", narc_path, out_dir])
        main()
        captured = capsys.readouterr()
        assert "[✓] Successfully unpacked" in captured.out
        assert os.path.isdir(out_dir)

        # Test CLI repack
        repack_path = os.path.join(tmpdir, "cli_repacked.narc")
        monkeypatch.setattr("sys.argv", ["miorom", "repack", out_dir, repack_path])
        main()
        captured = capsys.readouterr()
        assert "[✓] Successfully repacked ROM" in captured.out
        assert os.path.isfile(repack_path)
