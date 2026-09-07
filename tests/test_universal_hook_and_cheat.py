import struct
import pytest

from miorom.asm.branch import ARMBranch, ThumbBranch, PowerPCBranch, MIPSBranch
from miorom.asm.trampoline import TrampolineHook, HookRecord
from miorom.asm.cheat import (
    CheatCodeGenerator,
    GeckoCode,
    ActionReplayCode,
    CWCheatCode,
    GameSharkCode,
)


def test_powerpc_branch():
    pc = 0x80001000
    target = 0x80001080

    # Test relative branch (b target)
    b_instr = PowerPCBranch.encode_b(source_pc=pc, target_addr=target)
    assert len(b_instr) == 4
    dec_target, link, abs_flag = PowerPCBranch.decode_b(source_pc=pc, instr_bytes=b_instr)
    assert dec_target == target
    assert not link
    assert not abs_flag

    # Test branch with link (bl target)
    bl_instr = PowerPCBranch.encode_b(source_pc=pc, target_addr=target, link=True)
    dec_target, link, abs_flag = PowerPCBranch.decode_b(source_pc=pc, instr_bytes=bl_instr)
    assert dec_target == target
    assert link
    assert not abs_flag

    # Test backward branch
    target_back = 0x80000800
    b_back = PowerPCBranch.encode_b(source_pc=pc, target_addr=target_back)
    dec_back, _, _ = PowerPCBranch.decode_b(source_pc=pc, instr_bytes=b_back)
    assert dec_back == target_back

    # Test nop and blr
    assert PowerPCBranch.nop() == b"\x60\x00\x00\x00"
    assert PowerPCBranch.blr() == b"\x4E\x80\x00\x20"


def test_mips_branch():
    pc = 0x80020000
    target = 0x80024000

    # Test J target
    j_instr = MIPSBranch.encode_j(source_pc=pc, target_addr=target, endian="<")
    assert len(j_instr) == 4
    dec_target, link = MIPSBranch.decode_j(source_pc=pc, instr_bytes=j_instr, endian="<")
    assert dec_target == target
    assert not link

    # Test JAL target
    jal_instr = MIPSBranch.encode_j(source_pc=pc, target_addr=target, link=True, endian="<")
    dec_target, link = MIPSBranch.decode_j(source_pc=pc, instr_bytes=jal_instr, endian="<")
    assert dec_target == target
    assert link

    # Test big-endian (N64)
    j_n64 = MIPSBranch.encode_j(source_pc=pc, target_addr=target, endian=">")
    dec_n64, _ = MIPSBranch.decode_j(source_pc=pc, instr_bytes=j_n64, endian=">")
    assert dec_n64 == target

    assert MIPSBranch.nop() == b"\x00\x00\x00\x00"
    assert MIPSBranch.jr_ra() == b"\x08\x00\xE0\x03"


def test_trampoline_ppc():
    hook_addr = 0x80100000
    cave_addr = 0x80200000
    orig_instr = b"\x7C\x63\x02\xA6"  # mflr r3
    custom_payload = b"\x38\x60\x00\x01"  # li r3, 1

    hook_bytes, cave_bytes = TrampolineHook.create_ppc_hook(
        hook_ram_addr=hook_addr,
        original_instr_bytes=orig_instr,
        custom_payload_bytes=custom_payload,
        cave_ram_addr=cave_addr,
    )

    # Hook must be 4 bytes branching to cave
    assert len(hook_bytes) == 4
    target, _, _ = PowerPCBranch.decode_b(source_pc=hook_addr, instr_bytes=hook_bytes)
    assert target == cave_addr

    # Cave must contain: payload + orig + return branch
    assert cave_bytes.startswith(custom_payload)
    assert orig_instr in cave_bytes
    # Return branch at end of cave must point to hook_addr + 4
    ret_branch = cave_bytes[-4:]
    ret_pc = cave_addr + len(cave_bytes) - 4
    ret_target, _, _ = PowerPCBranch.decode_b(source_pc=ret_pc, instr_bytes=ret_branch)
    assert ret_target == hook_addr + 4


def test_trampoline_mips():
    hook_addr = 0x80050000
    cave_addr = 0x80080000
    orig_instr = b"\x24\x04\x00\x01\x00\x00\x00\x00"  # li a0, 1 + nop delay slot
    custom_payload = b"\x24\x02\x00\x2A"  # li v0, 42

    hook_bytes, cave_bytes = TrampolineHook.create_mips_hook(
        hook_ram_addr=hook_addr,
        original_instr_bytes=orig_instr,
        custom_payload_bytes=custom_payload,
        cave_ram_addr=cave_addr,
        endian="<",
    )

    # MIPS hook site is 8 bytes (j cave + nop)
    assert len(hook_bytes) == 8
    target, _ = MIPSBranch.decode_j(source_pc=hook_addr, instr_bytes=hook_bytes[:4], endian="<")
    assert target == cave_addr
    assert hook_bytes[4:] == b"\x00\x00\x00\x00"  # nop delay slot

    # Return jump inside cave
    ret_j = cave_bytes[-8:-4]
    ret_pc = cave_addr + len(cave_bytes) - 8
    ret_target, _ = MIPSBranch.decode_j(source_pc=ret_pc, instr_bytes=ret_j, endian="<")
    assert ret_target == hook_addr + 8


def test_unified_create_hook():
    orig_4 = b"\x00\x00\x00\x00"
    payload = b"\x01\x02\x03\x04"

    # Test PowerPC dispatcher
    h_ppc, c_ppc = TrampolineHook.create_hook("ppc", 0x80001000, orig_4, payload, 0x80005000)
    assert len(h_ppc) == 4

    # Test ARM dispatcher
    h_arm, c_arm = TrampolineHook.create_hook("arm", 0x02001000, orig_4, payload, 0x02005000)
    assert len(h_arm) == 4

    # Test Thumb dispatcher
    orig_2 = b"\x00\x00"
    h_thumb, c_thumb = TrampolineHook.create_hook("thumb", 0x02001000, orig_2, payload, 0x02001080)
    assert len(h_thumb) == 2


def test_auto_hook_with_code_cave():
    # Build synthetic binary with empty padding area (0x00 * 64)
    data = bytearray(b"\x90" * 128 + b"\x00" * 64 + b"\x90" * 64)
    hook_offset = 0x10
    hook_ram = 0x80000010

    orig_instr = b"\x7C\x63\x02\xA6"
    data[hook_offset:hook_offset + 4] = orig_instr
    payload = b"\x38\x60\x00\x01"

    patched_buf, record = TrampolineHook.auto_hook(
        data=data,
        hook_file_offset=hook_offset,
        hook_ram_addr=hook_ram,
        original_instr_bytes=orig_instr,
        custom_payload_bytes=payload,
        arch="ppc",
        ram_base_offset=0x80000000,
    )

    assert record.cave_file_offset == 128  # First 0x00 block
    assert record.hook_bytes == patched_buf[hook_offset:hook_offset + 4]
    assert record.cave_bytes == patched_buf[128:128 + len(record.cave_bytes)]


def test_gecko_code():
    gen = CheatCodeGenerator("RFF Infinite HP")
    gen.add_write_u32(0x80456780, 0x000003E7)
    gen.add_write_u16(0x80456784, 0x03E7)
    gen.add_write_u8(0x80456786, 0x63)

    txt = gen.to_gecko(game_id="RUFE99")
    assert "[RUFE99]" in txt
    assert "$RFF Infinite HP" in txt
    assert "04456780 000003E7" in txt
    assert "02456784 000003E7" in txt
    assert "00456786 00000063" in txt

    # Test C2 code
    gen_c2 = CheatCodeGenerator("C2 Hook")
    asm_payload = b"\x38\x60\x00\x01\x4E\x80\x00\x20"  # 8 bytes (2 instructions)
    gen_c2.add_c2_asm(0x80001234, asm_payload)
    c2_txt = gen_c2.to_gecko()
    assert "C2001234 00000001" in c2_txt
    assert "38600001 4E800020" in c2_txt

    # Test binary GCT export
    gct = gen.to_gct()
    assert gct.startswith(b"\x00\xD0\xC0\xDE\x00\xD0\xC0\xDE")
    assert gct.endswith(b"\xF0\x00\x00\x00\x00\x00\x00\x00")


def test_action_replay_and_cwcheat():
    gen = CheatCodeGenerator("NDS/PSP Patch")
    gen.add_write_u32(0x02010000, 0x12345678)
    gen.add_write_u16(0x02010004, 0xABCD)
    gen.add_write_u8(0x02010006, 0xFF)

    # Action Replay
    ar = gen.to_action_replay()
    assert "02010000 12345678" in ar
    assert "12010004 0000ABCD" in ar
    assert "22010006 000000FF" in ar
    assert "D2000000 00000000" in ar

    # CWCheat
    cw = gen.to_cwcheat(game_id="ULES-01234")
    assert "_S ULES-01234" in cw
    assert "_L 0x22010000 0x12345678" in cw
    assert "_L 0x12010004 0x0000ABCD" in cw
    assert "_L 0x02010006 0x000000FF" in cw


def test_cheat_from_diff():
    orig = b"\x00\x00\x00\x00\x11\x22\x33\x44\x00\x00\x00\x00"
    mod =  b"\x00\x00\x00\x00\xAA\xBB\xCC\xDD\x00\x00\x00\x00"

    gen = CheatCodeGenerator.from_diff(orig, mod, base_address=0x80001000)
    gecko = gen.to_gecko()
    assert "04001004 AABBCCDD" in gecko
