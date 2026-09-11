import struct
import pytest

from miorom import (
    CodePointer,
    PPCInstructionScanner,
    MIPSInstructionScanner,
    ScriptVM,
    FontMetrics,
    PixelWordWrapper,
    DolphinClient,
    DolphinMemoryMock,
    FstInjector,
    BinaryDiffMapper,
)


def test_instruction_pointer_scanner_ppc_and_mips():
    # PowerPC: lis r3, 0x8024 (opcode 15) then addi r3, r3, 0x51A0 (opcode 14)
    # insn1: (15 << 26) | (3 << 21) | (0 << 16) | 0x8024
    insn_lis = (15 << 26) | (3 << 21) | 0x8024
    # insn2: (14 << 26) | (3 << 21) | (3 << 16) | 0x51A0
    insn_addi = (14 << 26) | (3 << 21) | (3 << 16) | 0x51A0

    buf = bytearray(struct.pack(">II", insn_lis, insn_addi))
    ptrs = PPCInstructionScanner.find_split_pointers(bytes(buf), min_target=0x80000000)
    assert len(ptrs) == 1
    assert ptrs[0].target_address == 0x802451A0
    assert ptrs[0].reg == 3

    # Test patch
    ptrs[0].patch(buf, 0x80281234, endian=">")
    ptrs_patched = PPCInstructionScanner.find_split_pointers(bytes(buf), min_target=0x80000000)
    assert len(ptrs_patched) == 1
    assert ptrs_patched[0].target_address == 0x80281234

    # MIPS: lui $v0, 0x8005 then addiu $v0, $v0, 0x1234
    # lui: (15 << 26) | (0 << 21) | (2 << 16) | 0x8005
    mips_lui = (15 << 26) | (2 << 16) | 0x8005
    # addiu: (9 << 26) | (2 << 21) | (2 << 16) | 0x1234
    mips_addiu = (9 << 26) | (2 << 21) | (2 << 16) | 0x1234
    buf_mips = bytearray(struct.pack(">II", mips_lui, mips_addiu))

    ptrs_mips = MIPSInstructionScanner.find_split_pointers(bytes(buf_mips), min_target=0x80000000)
    assert len(ptrs_mips) == 1
    assert ptrs_mips[0].target_address == 0x80051234


def test_script_vm_roundtrip():
    vm = ScriptVM(opcode_size=1, endian=">")

    vm.register(0x01, "EXIT")
    vm.register(0x05, "MESSAGE", args=["speaker:u16", "text:str_ascii"])
    vm.register(0x10, "JUMP", args=["target:label"])

    src = """
    MESSAGE 1, "Hello warrior"
    JUMP label_target
    EXIT

label_target:
    MESSAGE 2, "You made it!"
    EXIT
    """

    bytecode = vm.assemble(src)
    assert len(bytecode) > 0

    disasm = vm.disassemble(bytecode)
    assert "MESSAGE 1, 'Hello warrior'" in disasm
    assert "JUMP" in disasm
    assert "MESSAGE 2, 'You made it!'" in disasm

    # Re-assemble disassembled output
    bytecode_re = vm.assemble(disasm)
    assert bytecode == bytecode_re


def test_pixel_word_wrapper():
    metrics = FontMetrics(default_width=10)
    assert metrics.measure_char("i") == 4
    assert metrics.measure_char("W") == 14

    # Tag stripping in measure
    assert metrics.measure_text("<WARNA>i") == 4

    wrapper = PixelWordWrapper(metrics, max_pixel_width=50, max_lines=2)
    # "WWWW" = 14 * 4 = 56px (exceeds 50px)
    valid, warnings = wrapper.validate("WWWW")
    assert valid is False
    assert len(warnings) == 1

    # "iiii" = 4 * 4 = 16px (fits easily)
    valid_i, _ = wrapper.validate("iiii")
    assert valid_i is True

    # Auto wrap
    wrapped = wrapper.wrap("W W W W")
    assert "\n" in wrapped


def test_dolphin_live_debug_mock():
    mock = DolphinMemoryMock()
    mock.write_u32(0x80001000, 0x12345678)
    assert mock.read_u32(0x80001000) == 0x12345678

    mock.write_string(0x80002000, "Halo Dunia", encoding="utf-16-be")
    res = mock.read_string(0x80002000, encoding="utf-16-be")
    assert res == "Halo Dunia"


def test_fst_injector():
    # Construct synthetic FST (root entry + 1 file entry "script.bin")
    # Total entries = 2
    # String table starts at 2 * 12 = 24
    fst = bytearray()
    # Root: is_dir=1, name_off=0, parent=0, num_entries=2
    fst.extend(struct.pack(">III", 0x01000000, 0, 2))
    # Entry 1: file, name_off=0 ("script.bin"), offset=0x1000, size=500
    fst.extend(struct.pack(">III", 0x00000000, 0x1000, 500))
    # String table
    fst.extend(b"script.bin\x00")

    injector = FstInjector(fst)
    assert len(injector.nodes) == 2
    node = injector.find_by_name("script.bin")
    assert node is not None
    assert node.offset == 0x1000
    assert node.size == 500

    # In-place update
    injector.update_entry(node.index, new_offset=0x2000, new_size=800)
    assert injector.find_by_name("script.bin").offset == 0x2000
    assert injector.find_by_name("script.bin").size == 800


def test_binary_diff_mapper():
    data_a = b"AAAA" + b"BBBB" * 8 + b"CCCC" * 8
    # Shifted by 16 bytes in data_b
    data_b = b"XXXX" * 4 + b"BBBB" * 8 + b"CCCC" * 8

    mapper = BinaryDiffMapper(data_a, data_b)
    matches = mapper.find_matching_blocks(chunk_size=16, stride=4)
    assert len(matches) > 0

    # Correlate offset
    # "BBBB"*8 starts at offset 4 in data_a and offset 16 in data_b (delta = +12)
    correl = mapper.correlate_offset(4)
    assert correl == 16
