import struct
import pytest
from miorom.scanner.text_stream import TextStreamScanner
from miorom.text.pointer_relinker import PointerRelinker, PointerRecord
from miorom.core.checksum import RetroChecksum
from miorom.patch.bps import BpsPatcher
from miorom.patch.ips import IpsPatcher
from miorom.patch.ups import UpsPatcher
from miorom.asm.hook_manager import CodeCaveManager, HookManager, ArmHookBuilder
from miorom.asm.reloc_calc import BranchRelocator
from miorom.asm.snippet import AsmSnippet
from miorom.asm.disasm import UniversalDisassembler
from miorom.graphics.planar import PlanarTileCodec
from miorom.graphics.tile_dedup import TileDeduplicator
from miorom.graphics.oam import HardwareOamCodec, SpriteDescriptor
from miorom.diff.bindiff import BinDiffEngine
from miorom.asm.ap_bypass import AntiPiracyBypasser


def test_golden_pipeline_text_translation_and_patching():
    rom_size = 0x8000
    rom = bytearray(b"\xFF" * rom_size)

    rom[0x7FC0:0x7FD5] = b"MIO_TEST_GAME        "
    rom[0x7FD5] = 0x20
    rom[0x7FD6] = 0x00
    rom[0x7FD7] = 0x09
    rom[0x7FD8] = 0x00
    rom[0x7FD9] = 0x01
    rom[0x7FDA] = 0x33
    rom[0x7FDB] = 0x00
    rom[0x7FDC:0x7FE0] = b"\x00\x00\xFF\xFF"

    strings = [
        "PLAYER SELECT".encode("ascii") + b"\x00",
        "START GAME".encode("ascii") + b"\x00",
        "OPTIONS MENU".encode("ascii") + b"\x00",
        "GAME OVER".encode("ascii") + b"\x00",
    ]

    string_offsets = [0x1000, 0x1020, 0x1040, 0x1060]
    for off, s in zip(string_offsets, strings):
        rom[off:off + len(s)] = s

    ptr_table_offset = 0x0800
    relinker = PointerRelinker(pointer_size=2, endian="little", base_address=0x8000)
    for i, target in enumerate(string_offsets):
        ptr_val = target + 0x8000
        struct.pack_into("<H", rom, ptr_table_offset + i * 2, ptr_val)

    scanner = TextStreamScanner(min_length=4, min_confidence=0.6)
    scanned_spans = scanner.scan(rom[0x1000:0x1080], encodings=["ascii"])
    assert len(scanned_spans) >= 3

    found_texts = [s.text.strip("\x00") for s in scanned_spans]
    assert "PLAYER SELECT" in found_texts
    assert "START GAME" in found_texts

    records = relinker.scan_pointer_table(
        rom,
        table_offset=ptr_table_offset,
        entry_count=4,
        pointer_type="absolute",
    )
    assert len(records) == 4
    assert records[0].target_offset == 0x1000

    new_strings = [
        "PILIH PEMAIN".encode("ascii") + b"\x00",
        "MULAI PETUALANGAN BARU SEKARANG".encode("ascii") + b"\x00",
        "PENGATURAN".encode("ascii") + b"\x00",
        "PERMAINAN SELESAI".encode("ascii") + b"\x00",
    ]

    modified_rom, report = relinker.relink(rom, records, new_strings, fill_byte=0xFF)
    assert report.entries_relinked > 0
    assert report.entries_relocated > 0

    p0_val = relinker.read_pointer(modified_rom, ptr_table_offset)
    p1_val = relinker.read_pointer(modified_rom, ptr_table_offset + 2)
    assert p0_val == 0x1000 + 0x8000
    assert p1_val != 0x1020 + 0x8000

    p1_target = p1_val - 0x8000
    assert modified_rom[p1_target:p1_target + len(new_strings[1])] == new_strings[1]

    sum_val, inv_val = RetroChecksum.snes_checksum(bytes(modified_rom))
    modified_rom[0x7FDC:0x7FE0] = struct.pack("<HH", inv_val, sum_val)

    re_sum, re_inv = RetroChecksum.snes_checksum(bytes(modified_rom))
    assert (re_sum + re_inv) & 0xFFFF == 0xFFFF

    bps_patch = BpsPatcher.create(bytes(rom), bytes(modified_rom))
    assert bps_patch.startswith(b"BPS1")
    restored_from_bps = BpsPatcher.apply(bytes(rom), bps_patch)
    assert restored_from_bps == bytes(modified_rom)

    ips_patch = IpsPatcher.create(bytes(rom), bytes(modified_rom))
    restored_from_ips = IpsPatcher.apply(bytes(rom), ips_patch)
    assert restored_from_ips == bytes(modified_rom)

    ups_patch = UpsPatcher.create(bytes(rom), bytes(modified_rom))
    restored_from_ups = UpsPatcher.apply(bytes(rom), ups_patch)
    assert restored_from_ups == bytes(modified_rom)


def test_golden_pipeline_code_cave_injection_and_relocation():
    rom = bytearray(b"\xEA" * 0x4000)

    cave_start = 0x2000
    cave_size = 0x200
    rom[cave_start:cave_start + cave_size] = b"\x00" * cave_size

    cave_mgr = CodeCaveManager(fill_byte=0x00)
    caves = cave_mgr.scan(rom, min_size=64)
    assert len(caves) >= 1
    selected_cave = caves[0]
    assert selected_cave.start == cave_start

    hook_site = 0x0500
    rom[hook_site:hook_site + 4] = b"\x00\x00\xA0\xE1"

    cave, offset_within = cave_mgr.allocate(24, label="custom_payload")
    allocated_addr = cave.start + offset_within
    assert allocated_addr == cave_start

    payload_arm = bytes([
        0x01, 0x00, 0x80, 0xE2,
        0x02, 0x10, 0x81, 0xE2,
    ])

    hook_mgr = HookManager()
    hook_rec = hook_mgr.install_arm_hook(
        buf=rom,
        hook_rom_offset=hook_site,
        hook_ram_addr=hook_site,
        cave_ram_addr=allocated_addr,
        cave_rom_offset=allocated_addr,
        cave_code=payload_arm,
        mode="b",
    )
    assert hook_rec.hook_offset == hook_site
    assert hook_rec.cave_offset == allocated_addr

    hook_inst = ArmHookBuilder.build_arm_b(hook_site, allocated_addr)
    assert rom[hook_site:hook_site + 4] == hook_inst

    cave_content = rom[allocated_addr:allocated_addr + 12]
    assert cave_content[:8] == payload_arm
    ret_b = ArmHookBuilder.build_arm_b(allocated_addr + 8, hook_site + 4)
    assert cave_content[8:12] == ret_b

    disasm_hook = UniversalDisassembler.disassemble(
        rom[hook_site:hook_site + 4],
        base_address=hook_site,
        arch="arm",
        endian="little",
    )
    assert len(disasm_hook) == 1
    assert disasm_hook[0].mnemonic.lower() == "b"
    assert disasm_hook[0].target_address == allocated_addr

    block_code = bytes([
        0xD0, 0x06,
        0xEA,
        0xEA,
        0xF0, 0x02,
        0xEA,
        0x60,
    ])
    orig_base = 0x0600
    new_base = 0x0900
    relocator = BranchRelocator()
    rebased_code, relocs = relocator.rebase_block(
        code=block_code,
        orig_base=orig_base,
        new_base=new_base,
        arch="6502",
    )
    assert len(relocs) == 2
    assert rebased_code == block_code


def test_golden_pipeline_graphics_planar_dedup_and_oam():
    tile_a_pixels = bytes([1 if (r + c) % 2 == 0 else 0 for r in range(8) for c in range(8)])
    tile_b_pixels = bytes([2 if r < 4 else 0 for r in range(8) for c in range(8)])
    tile_b_vflip = bytes([2 if r >= 4 else 0 for r in range(8) for c in range(8)])
    tile_c_pixels = bytes([3 if c < 4 else 0 for r in range(8) for c in range(8)])
    tile_c_hflip = bytes([3 if c >= 4 else 0 for r in range(8) for c in range(8)])

    raw_tiles = bytearray()
    raw_tiles += PlanarTileCodec.encode_tile(tile_a_pixels, format="4bpp_planar")
    raw_tiles += PlanarTileCodec.encode_tile(tile_b_pixels, format="4bpp_planar")
    raw_tiles += PlanarTileCodec.encode_tile(tile_b_vflip, format="4bpp_planar")
    raw_tiles += PlanarTileCodec.encode_tile(tile_c_pixels, format="4bpp_planar")
    raw_tiles += PlanarTileCodec.encode_tile(tile_c_hflip, format="4bpp_planar")
    raw_tiles += PlanarTileCodec.encode_tile(tile_a_pixels, format="4bpp_planar")

    all_tiles = [tile_a_pixels, tile_b_pixels, tile_b_vflip, tile_c_pixels, tile_c_hflip, tile_a_pixels]
    dedup_res = TileDeduplicator.deduplicate(all_tiles, allow_flip_h=True, allow_flip_v=True, preserve_blank_at_zero=False)

    assert dedup_res.original_count == 6
    assert dedup_res.unique_count == 3
    assert dedup_res.saved_count == 3

    assert dedup_res.entries[0].unique_index == 0
    assert dedup_res.entries[5].unique_index == 0

    assert dedup_res.entries[2].unique_index == dedup_res.entries[1].unique_index
    assert dedup_res.entries[2].flip_v is True

    assert dedup_res.entries[4].unique_index == dedup_res.entries[3].unique_index
    assert dedup_res.entries[4].flip_h is True

    opt_raw, raw_entries = TileDeduplicator.deduplicate_raw_bpp(bytes(raw_tiles), bpp=4, format="4bpp_planar")
    assert len(opt_raw) == 3 * 32
    assert len(raw_entries) == 6

    snes_words = [e.to_nametable_word_snes(palette=2, priority=3) for e in dedup_res.entries]
    assert len(snes_words) == 6
    assert (snes_words[2] & (1 << 15)) != 0
    assert (snes_words[4] & (1 << 14)) != 0

    sprites = [
        SpriteDescriptor(x=64, y=100, tile_id=dedup_res.entries[0].unique_index, palette=1, flip_h=False, flip_v=False, priority=2, size_flag=0),
        SpriteDescriptor(x=72, y=100, tile_id=dedup_res.entries[1].unique_index, palette=1, flip_h=False, flip_v=True, priority=2, size_flag=0),
        SpriteDescriptor(x=80, y=100, tile_id=dedup_res.entries[3].unique_index, palette=2, flip_h=True, flip_v=False, priority=2, size_flag=1),
    ]

    t1, t2 = HardwareOamCodec.encode_snes(sprites)
    assert len(t1) == 12
    assert len(t2) == 32

    decoded_sprites = HardwareOamCodec.decode_snes(t1, t2)
    assert len(decoded_sprites) == 3
    assert decoded_sprites[0].x == 64
    assert decoded_sprites[0].y == 100
    assert decoded_sprites[0].tile_id == dedup_res.entries[0].unique_index
    assert decoded_sprites[1].flip_v is True
    assert decoded_sprites[2].flip_h is True

    gba_bytes = HardwareOamCodec.encode_gba(sprites)
    assert len(gba_bytes) == 24
    decoded_gba = HardwareOamCodec.decode_gba(gba_bytes)
    assert len(decoded_gba) == 3
    assert decoded_gba[0].x == 64
    assert decoded_gba[0].y == 100
    assert decoded_gba[1].flip_v is True
    assert decoded_gba[2].flip_h is True


def test_golden_pipeline_cross_version_bindiff():
    ppc_routine_a = bytes([
        0x94, 0x21, 0xFF, 0xF0,
        0x7C, 0x08, 0x02, 0xA6,
        0x90, 0x01, 0x00, 0x14,
        0x38, 0x60, 0x00, 0x0A,
        0x80, 0x01, 0x00, 0x14,
        0x7C, 0x08, 0x03, 0xA6,
        0x38, 0x21, 0x00, 0x10,
        0x4E, 0x80, 0x00, 0x20,
    ])

    ppc_routine_b = bytes([
        0x94, 0x21, 0xFF, 0xF0,
        0x7C, 0x08, 0x02, 0xA6,
        0x90, 0x01, 0x00, 0x14,
        0x38, 0x60, 0x00, 0x14,
        0x80, 0x01, 0x00, 0x14,
        0x7C, 0x08, 0x03, 0xA6,
        0x38, 0x21, 0x00, 0x10,
        0x4E, 0x80, 0x00, 0x20,
    ])

    binary_v1 = bytearray(b"\x00" * 0x1000)
    binary_v2 = bytearray(b"\x00" * 0x1000)

    func1_v1 = 0x0100
    func1_v2 = 0x0200
    binary_v1[func1_v1:func1_v1 + len(ppc_routine_a)] = ppc_routine_a
    binary_v2[func1_v2:func1_v2 + len(ppc_routine_b)] = ppc_routine_b

    fp_a = BinDiffEngine.fingerprint_function(bytes(binary_v1), func1_v1, base_address=0x80000000, arch="ppc")
    fp_b = BinDiffEngine.fingerprint_function(bytes(binary_v2), func1_v2, base_address=0x80000000, arch="ppc")

    sim = BinDiffEngine.compare_fingerprints(fp_a, fp_b)
    assert sim >= 0.85

    report = BinDiffEngine.diff_binaries(
        data_a=bytes(binary_v1),
        base_a=0x80000000,
        funcs_a=[0x80000000 + func1_v1],
        data_b=bytes(binary_v2),
        base_b=0x80000000,
        funcs_b=[0x80000000 + func1_v2],
        arch="ppc",
        threshold=0.80,
    )
    assert report.total_funcs_a == 1
    assert len(report.matches) == 1
    match = report.matches[0]
    assert match.func_a_address == 0x80000000 + func1_v1
    assert match.func_b_address == 0x80000000 + func1_v2
    assert match.similarity >= 0.85


def test_golden_pipeline_anti_piracy_bypass_and_disassembly():
    ppc_code = bytearray([
        0x28, 0x03, 0x00, 0x00,
        0x40, 0x82, 0x00, 0x10,
        0x38, 0x60, 0x00, 0x01,
        0x4E, 0x80, 0x00, 0x20,
    ])

    matches = AntiPiracyBypasser.scan_ppc_integrity(bytes(ppc_code))
    assert len(matches) == 1
    assert matches[0].offset == 4
    assert matches[0].arch == "ppc"

    report = AntiPiracyBypasser.patch_all(ppc_code, matches)
    assert report.patched_count == 1
    assert ppc_code[4:8] == AntiPiracyBypasser.PPC_NOP

    disasm = UniversalDisassembler.disassemble(
        bytes(ppc_code),
        base_address=0x80003100,
        arch="ppc",
        endian="big",
    )
    assert len(disasm) == 4
    assert disasm[1].mnemonic.lower() == "nop"

