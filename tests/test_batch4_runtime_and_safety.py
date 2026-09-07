import struct
import pytest

from miorom import (
    MioRomHeap,
    HeapStats,
    MemBlock,
    AntiPiracyBypasser,
    APVectorType,
    APMatch,
    APBypassReport,
    RomLayoutExpander,
    RomExpansionReport,
    RomAddressSanitizer,
    SanitizerViolation,
    MemorySanitizerError,
    SanitizerReport,
    AccessType,
    ShadowTag,
    SaveStateDiffHunter,
    RAMSnapshot,
    DiffMatch,
    PointerTrail,
    DiffHunterReport,
)


# =====================================================================
# 1. Dynamic In-ROM Heap Allocator (MioRomHeap) Tests
# =====================================================================
def test_miorom_heap_alloc_free_coalesce():
    base_ram = 0x80500000
    heap_size = 0x10000  # 64 KB
    heap = MioRomHeap(base_ram=base_ram, total_size=heap_size)

    assert heap.check_integrity()
    stats0 = heap.stats()
    assert stats0.num_allocations == 0
    assert stats0.free_bytes > 0

    # Allocate 3 blocks
    p1 = heap.malloc(64)
    p2 = heap.malloc(128)
    p3 = heap.malloc(256)

    assert p1 == base_ram + 16
    assert p2 > p1
    assert p3 > p2
    assert heap.check_integrity()

    stats1 = heap.stats()
    assert stats1.num_allocations == 3

    # Free middle block
    assert heap.free(p2)
    assert heap.check_integrity()
    stats2 = heap.stats()
    assert stats2.num_allocations == 2

    # Free adjacent block p1 and verify coalescing
    assert heap.free(p1)
    assert heap.check_integrity()
    stats3 = heap.stats()
    assert stats3.num_allocations == 1

    # Free final block
    assert heap.free(p3)
    assert heap.check_integrity()
    assert heap.stats().num_allocations == 0

    # Check C payload generator
    c_code = heap.generate_c_payload()
    assert "miorom_malloc" in c_code
    assert "miorom_free" in c_code
    assert "MIO_HEAP_BASE" in c_code


# =====================================================================
# 2. Anti-Piracy & Integrity Bypass Engine Tests
# =====================================================================
def test_anti_piracy_bypasser_nds_and_ppc():
    # Construct synthetic ARM code containing NDS ROMCTRL pattern
    # ldr r0, =0x040001A4 (b"\xa4\x01\x00\x04")
    # Followed by conditional branch BNE (0x1A000005)
    code = bytearray(128)
    code[16:20] = b"\xa4\x01\x00\x04"
    # Conditional branch at offset 28
    bne_instr = 0x1A000005  # ARM BNE
    struct.pack_into("<I", code, 28, bne_instr)

    matches = AntiPiracyBypasser.scan_nds_ap(bytes(code))
    assert len(matches) >= 1
    assert matches[0].vector_type == APVectorType.CARTRIDGE_CHECK

    # Patch AP checks
    report = AntiPiracyBypasser.patch_all(code, matches)
    assert isinstance(report, APBypassReport)
    assert report.patched_count >= 1
    assert "Anti-Piracy & Integrity Bypass Report" in report.summary()
    # Verify patched with ARM NOP
    assert code[matches[0].offset : matches[0].offset + 4] == AntiPiracyBypasser.ARM_NOP

    # PowerPC integrity comparison test
    ppc_code = bytearray(64)
    # cmpwi r3, 0 (opcode 10, 0x2C030000) followed by bc/bne (opcode 16, 0x40820008)
    struct.pack_into(">II", ppc_code, 8, 0x2C030000, 0x40820008)
    ppc_matches = AntiPiracyBypasser.scan_ppc_integrity(bytes(ppc_code))
    assert len(ppc_matches) >= 1
    assert ppc_matches[0].vector_type == APVectorType.INTEGRITY_CMP


# =====================================================================
# 3. ROM Layout Expander & Far Memory Relocator Tests
# =====================================================================
def test_rom_layout_expander():
    # 1. GBA expansion (4MB -> 8MB)
    orig_gba = bytearray(4 * 1024 * 1024)
    orig_gba[0:4] = b"GBA!"
    expanded_gba, rep_gba = RomLayoutExpander.expand_gba(
        bytes(orig_gba), target_size=8 * 1024 * 1024, pad_byte=0xFF
    )
    assert len(expanded_gba) == 8 * 1024 * 1024
    assert expanded_gba[4 * 1024 * 1024] == 0xFF
    assert rep_gba.expanded_bytes == 4 * 1024 * 1024
    assert "ROM Layout Expansion Report" in rep_gba.summary()

    # 2. NDS expansion (512KB -> 1MB)
    nds_buf = bytearray(0x80000)
    nds_buf[0x14] = 0x07  # old capacity
    struct.pack_into("<I", nds_buf, 0x80, 0x80000)
    expanded_nds, rep_nds = RomLayoutExpander.expand_nds(bytes(nds_buf), target_size=0x100000)
    assert len(expanded_nds) == 0x100000
    new_cap = expanded_nds[0x14]
    assert new_cap > 0
    new_total_size = struct.unpack_from("<I", expanded_nds, 0x80)[0]
    assert new_total_size == 0x100000

    # 3. Far memory relocation
    rom = bytearray(0x1000)
    # Put text payload at 0x100
    rom[0x100:0x108] = b"FAR_DATA"
    # Pointer at 0x20 pointing to 0x100 (RAM base 0x80000000)
    struct.pack_into(">I", rom, 0x20, 0x80000100)

    # Relocate from 0x100 to 0x800
    updated = RomLayoutExpander.relocate_to_far_memory(
        rom_data=rom,
        source_offset=0x100,
        source_size=8,
        target_offset=0x800,
        pointer_locations=[0x20],
        ram_base=0x80000000,
        endian=">",
        pad_byte=0x00,
    )
    assert updated == 1
    assert rom[0x800:0x808] == b"FAR_DATA"
    assert rom[0x100:0x108] == b"\x00" * 8
    new_ptr = struct.unpack_from(">I", rom, 0x20)[0]
    assert new_ptr == 0x80000800


# =====================================================================
# 4. Fuzzing & Memory Safety Sanitizer (ROM-ASan) Tests
# =====================================================================
def test_rom_address_sanitizer():
    sanitizer = RomAddressSanitizer(default_tag=ShadowTag.UNMAPPED)

    # Protect a 32-byte dialogue buffer with 16-byte redzones
    buf_addr = 0x80100000
    sanitizer.protect_with_redzones(base_addr=buf_addr, payload_size=32, redzone_size=16, name="dialogue_buf")

    # Valid read/write within buffer bounds
    assert sanitizer.check_access(buf_addr, 16, AccessType.READ) is None
    assert sanitizer.check_access(buf_addr + 16, 16, AccessType.WRITE) is None

    # Buffer underflow (reads 4 bytes starting before the buffer)
    v_under = sanitizer.check_access(buf_addr - 4, 4, AccessType.READ)
    assert v_under is not None
    assert v_under.tag == ShadowTag.REDZONE

    # Buffer overflow (reads past the end of the buffer)
    v_over = sanitizer.check_access(buf_addr + 32, 4, AccessType.WRITE)
    assert v_over is not None
    assert v_over.tag == ShadowTag.REDZONE

    # Test assert_bounds raises MemorySanitizerError
    with pytest.raises(MemorySanitizerError):
        sanitizer.assert_bounds(buf_addr + 32, 4, AccessType.WRITE)

    # Poison region (e.g. deallocation)
    sanitizer.poison_region(buf_addr, 32)
    v_uaf = sanitizer.check_access(buf_addr, 4, AccessType.READ)
    assert v_uaf is not None
    assert v_uaf.tag == ShadowTag.POISONED

    rep = sanitizer.report()
    assert rep.total_checks >= 4
    assert len(rep.violations) >= 3
    assert "ROM-ASan Memory Safety Report" in rep.summary()


# =====================================================================
# 5. Save-State Diff-Fuzzing & Pointer Trail Hunter Tests
# =====================================================================
def test_save_state_diff_and_pointer_trail_hunter():
    # Construct 3 memory snapshots (e.g. health increasing: 100 -> 150 -> 200)
    ram_base = 0x80000000
    s1_data = bytearray(0x400)
    s2_data = bytearray(0x400)
    s3_data = bytearray(0x400)

    health_offset = 0x50
    struct.pack_into(">I", s1_data, health_offset, 100)
    struct.pack_into(">I", s2_data, health_offset, 150)
    struct.pack_into(">I", s3_data, health_offset, 200)

    snaps = [
        RAMSnapshot(name="state1", data=bytes(s1_data), ram_base=ram_base),
        RAMSnapshot(name="state2", data=bytes(s2_data), ram_base=ram_base),
        RAMSnapshot(name="state3", data=bytes(s3_data), ram_base=ram_base),
    ]

    matches = SaveStateDiffHunter.diff_snapshots(snaps, condition="increased", stride=4, endian=">")
    assert len(matches) == 1
    assert matches[0].offset == health_offset
    assert matches[0].ram_addr == ram_base + health_offset
    assert matches[0].values == [100, 150, 200]
    assert "0x64 (100) -> 0x96 (150) -> 0xC8 (200)" in matches[0].summary()

    # Pointer trail hunting:
    # Let static pointer at 0x10 point to a struct base at 0x80000040 (offset delta = 0x10 to health at 0x50)
    snap_trail = bytearray(0x400)
    struct.pack_into(">I", snap_trail, 0x10, ram_base + 0x40)
    # Struct offset 0x10 has the health value (0x40 + 0x10 = 0x50)
    target_ram = ram_base + 0x50

    trails = SaveStateDiffHunter.find_pointer_trails(
        snapshot=RAMSnapshot("state_ptr", bytes(snap_trail), ram_base=ram_base),
        target_ram=target_ram,
        max_depth=2,
        max_offset=0x100,
        endian=">",
    )
    assert len(trails) >= 1
    assert trails[0].base_ram == ram_base + 0x10
    assert trails[0].offsets == [0x10]
    assert trails[0].resolved_target == target_ram
    assert "->" in trails[0].expression()

    report = DiffHunterReport(snapshots_analyzed=3, matches=matches, pointer_trails=trails)
    assert "Save-State Diff & Pointer Trail Report" in report.summary()
