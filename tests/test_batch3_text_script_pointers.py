import struct
import pytest

from miorom import (
    CharMapMiner,
    MinedCharMapResult,
    MultiLevelPointerTable,
    TableLevel,
    CascadingRelocator,
    CascadingShiftReport,
    MioScriptCompiler,
    ScriptArcheologist,
    ArcheologyReport,
    ScriptVM,
)


def test_charmap_miner_shifted_ascii():
    original_text = "The quick brown fox jumps over the lazy dog. Super Mario 64 text test!"
    # Shift ASCII bytes by +0x10
    shift_offset = 0x10
    encoded_data = bytes((ord(c) + shift_offset) & 0xFF for c in original_text)

    result = CharMapMiner.mine_1byte_charmap(encoded_data)
    assert isinstance(result, MinedCharMapResult)
    assert result.confidence > 0.5
    assert result.mapped_count > 0

    # Verify that the charmap can decode the characters
    decoded = result.charmap.decode(encoded_data[:10])
    assert "The quick " == decoded


def test_multilevel_pointer_table():
    # Construct a 2-level pointer table
    # Root table at offset 0x00: contains 2 pointers to sub-tables at 0x10 and 0x20
    # Sub-table 0 at 0x10: contains 2 pointers to string A (0x30) and string B (0x40)
    # Sub-table 1 at 0x20: contains 2 pointers to string C (0x50) and string D (0x60)
    buf = bytearray(0x80)

    # Root entries (offsets: 0x10, 0x20)
    struct.pack_into(">II", buf, 0x00, 0x10, 0x20)
    # Sub-table 0 entries
    struct.pack_into(">II", buf, 0x10, 0x30, 0x40)
    # Sub-table 1 entries
    struct.pack_into(">II", buf, 0x20, 0x50, 0x60)

    # Write strings
    buf[0x30:0x36] = b"Alpha\x00"
    buf[0x40:0x45] = b"Beta\x00"
    buf[0x50:0x56] = b"Gamma\x00"
    buf[0x60:0x66] = b"Delta\x00"

    levels = [
        TableLevel(level_index=0, stride=4, endian=">"),
        TableLevel(level_index=1, stride=4, endian=">"),
    ]
    mlpt = MultiLevelPointerTable(root_offset=0x00, levels=levels)

    # Resolve and read
    assert mlpt.resolve_path(bytes(buf), [0, 0]) == 0x30
    assert mlpt.read_leaf_string(bytes(buf), [0, 0]) == "Alpha"

    assert mlpt.resolve_path(bytes(buf), [0, 1]) == 0x40
    assert mlpt.read_leaf_string(bytes(buf), [0, 1]) == "Beta"

    assert mlpt.resolve_path(bytes(buf), [1, 0]) == 0x50
    assert mlpt.read_leaf_string(bytes(buf), [1, 0]) == "Gamma"

    assert mlpt.resolve_path(bytes(buf), [1, 1]) == 0x60
    assert mlpt.read_leaf_string(bytes(buf), [1, 1]) == "Delta"

    # Update leaf pointer: change [1, 0] to point to a new string at 0x70
    buf[0x70:0x76] = b"Omega\x00"
    mlpt.update_leaf_pointer(buf, [1, 0], 0x70)

    assert mlpt.resolve_path(bytes(buf), [1, 0]) == 0x70
    assert mlpt.read_leaf_string(bytes(buf), [1, 0]) == "Omega"


def test_cascading_relocator():
    # Create buffer with a direct pointer table at 0x00 and PowerPC split instruction at 0x20
    buf = bytearray(0x80)
    ram_base = 0x80000000

    # Direct pointer table: 2 pointers pointing to 0x30 (RAM 0x80000030) and 0x60 (RAM 0x80000060)
    struct.pack_into(">II", buf, 0x00, ram_base + 0x30, ram_base + 0x60)

    # PowerPC split pointer: targeting 0x80000050 (file offset 0x50)
    # lis r3, 0x8000 (opcode 15)
    # addi r3, r3, 0x0050 (opcode 14)
    target_addr = 0x80000050
    ha = ((target_addr + 0x8000) >> 16) & 0xFFFF
    lo = target_addr & 0xFFFF
    insn_lis = (15 << 26) | (3 << 21) | ha
    insn_addi = (14 << 26) | (3 << 21) | (3 << 16) | lo
    struct.pack_into(">II", buf, 0x20, insn_lis, insn_addi)

    # Shift at boundary 0x40 by 0x20 (32 bytes)
    report = CascadingRelocator.shift_and_relocate(
        data=buf,
        shift_boundary=0x40,
        delta_bytes=0x20,
        direct_tables=[(0x00, 2)],
        split_pointers=[(0x20, 0x24)],
        ram_base=ram_base,
        endian=">",
        arch="ppc",
    )

    assert report.delta_bytes == 0x20
    assert report.direct_pointers_updated == 1
    assert report.split_pointers_updated == 1
    assert len(buf) == 0x80 + 0x20

    # Verify direct pointers
    p1 = struct.unpack_from(">I", buf, 0x00)[0]
    p2 = struct.unpack_from(">I", buf, 0x04)[0]
    assert p1 == ram_base + 0x30
    assert p2 == ram_base + 0x80

    # Verify split PPC pointer
    lis_patched = struct.unpack_from(">I", buf, 0x20)[0]
    addi_patched = struct.unpack_from(">I", buf, 0x24)[0]
    ha_new = lis_patched & 0xFFFF
    lo_new = struct.unpack(">h", struct.pack(">H", addi_patched & 0xFFFF))[0]
    reconstructed = (ha_new << 16) + lo_new
    assert reconstructed == ram_base + 0x70
    assert "Cascading Relocation Report" in report.summary()


def test_mioscript_compiler():
    compiler = MioScriptCompiler()
    source = """
    if (check_flag(100)) {
        dialogue("Welcome hero!");
        sleep(30);
    } else {
        dialogue("Go away stranger!");
    }
    exit();
    """

    asm_code = compiler.compile_to_assembly(source)
    assert "CHECK_FLAG 100" in asm_code
    assert "JUMP_IF_FALSE" in asm_code
    assert 'MESSAGE "Welcome hero!"' in asm_code
    assert "WAIT 30" in asm_code
    assert 'MESSAGE "Go away stranger!"' in asm_code
    assert "EXIT" in asm_code

    # Direct bytecode compilation
    bc = compiler.compile(source)
    assert len(bc) > 0
    assert isinstance(bc, bytes)


def test_script_archeologist():
    # Synthesize bytecode stream:
    # Opcode 0x01 with string "Hello\x00"
    # Opcode 0x02
    # Opcode 0x01 with string "World\x00"
    stream = b"\x01Hello\x00\x02\x01World\x00\x02\x02"

    report = ScriptArcheologist.analyze_stream(stream)
    assert report.total_bytes == len(stream)
    assert len(report.detected_opcodes) >= 2
    assert "Script Bytecode Archeology Report" in report.summary()

    # Verify synthesis
    vm = ScriptArcheologist.synthesize_vm(report)
    assert isinstance(vm, ScriptVM)
    assert len(vm.opcodes) >= 2
