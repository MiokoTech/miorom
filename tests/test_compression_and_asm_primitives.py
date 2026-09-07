import struct
import pytest
from miorom.compression.inspector import (
    CompressionHeaderInspector,
    CompressedSizeComparator,
    CompressionSizeReport,
)
from miorom.asm.micro_patcher import (
    SplitImmediateCalculator,
    StackAllocPatcher,
    OpcodeTransmuter,
)


def test_compression_header_inspector():
    # Nintendo LZ10 header: 0x10, len=0x001234 (little endian: 0x34, 0x12, 0x00)
    lz10_buf = bytearray([0x10, 0x34, 0x12, 0x00, 0xAA, 0xBB])
    size = CompressionHeaderInspector.read_uncompressed_size(bytes(lz10_buf))
    assert size == 0x001234

    # Patch size to 0x005678
    ok = CompressionHeaderInspector.patch_uncompressed_size(lz10_buf, 0x005678)
    assert ok is True
    new_size = CompressionHeaderInspector.read_uncompressed_size(bytes(lz10_buf))
    assert new_size == 0x005678

    # Yaz0 header: "Yaz0", u32 big-endian size
    yaz0_buf = bytearray(b"Yaz0" + struct.pack(">I", 0x10000))
    yaz_size = CompressionHeaderInspector.read_uncompressed_size(bytes(yaz0_buf))
    assert yaz_size == 0x10000

    ok_yaz = CompressionHeaderInspector.patch_uncompressed_size(yaz0_buf, 0x25000)
    assert ok_yaz is True
    assert CompressionHeaderInspector.read_uncompressed_size(bytes(yaz0_buf)) == 0x25000


def test_compressed_size_comparator():
    orig = b"A" * 100
    expanded = b"A" * 150
    rep = CompressedSizeComparator.compare(orig, expanded, format_name="lz10")
    assert rep.original_size == 100
    assert rep.new_size == 150
    assert rep.delta == 50
    assert rep.has_expanded is True


def test_split_immediate_calculator():
    # PPC: target address 0x80251000 (lo=0x1000 < 0x8000 -> ha = 0x8025, l = 0x1000)
    ha, l = SplitImmediateCalculator.calc_ppc_ha_l(0x80251000)
    assert ha == 0x8025
    assert l == 0x1000

    # PPC with sign carry: target address 0x80259000 (lo=0x9000 >= 0x8000 -> ha = 0x8025 + 1 = 0x8026, l = 0x9000)
    ha_carry, l_carry = SplitImmediateCalculator.calc_ppc_ha_l(0x80259000)
    assert ha_carry == 0x8026
    assert l_carry == 0x9000

    # MIPS: target address 0x8004A000 (lo >= 0x8000 -> hi = 0x8004 + 1 = 0x8005)
    m_hi, m_lo = SplitImmediateCalculator.calc_mips_hi_lo(0x8004A000)
    assert m_hi == 0x8005
    assert m_lo == 0xA000

    # ARM movw/movt
    imm_lo, imm_hi = SplitImmediateCalculator.calc_arm_movw_movt(0x02158040)
    assert imm_lo == 0x8040
    assert imm_hi == 0x0215


def test_stack_alloc_patcher():
    # ARM SUB SP, SP, #64 (0xE24DD040)
    arm_code = bytearray(struct.pack("<I", 0xE24DD040))
    ok_arm = StackAllocPatcher.patch_arm_sub_sp(arm_code, offset=0, frame_size=128)
    assert ok_arm is True
    patched_op = struct.unpack_from("<I", arm_code, 0)[0]
    assert (patched_op & 0xFF) == 128

    # MIPS addiu $sp, $sp, -64
    mips_code = bytearray(4)
    ok_mips = StackAllocPatcher.patch_mips_addiu_sp(mips_code, offset=0, frame_size=128, endian=">")
    assert ok_mips is True
    op = struct.unpack_from(">I", mips_code, 0)[0]
    # Check opcode bits 0x27BD and signed immediate (-128 & 0xFFFF = 0xFF80)
    assert (op >> 16) == 0x27BD
    assert (op & 0xFFFF) == ((-128) & 0xFFFF)


def test_opcode_transmuter():
    # LDRH r0, [r1, #8] -> cond=0xE, 0x1D, Rn=1, Rd=0, imm_hi=0, 0xB, imm_lo=8 -> 0xE1D100B8
    code = bytearray(struct.pack("<I", 0xE1D100B8))
    ok = OpcodeTransmuter.transmute_arm_ldrh_to_ldrb(code, offset=0, endian="<")
    assert ok is True

    # Check that new opcode is LDRB r0, [r1, #8] -> 0xE5D10008
    new_op = struct.unpack_from("<I", code, 0)[0]
    assert new_op == 0xE5D10008
