import pytest
from miorom.asm.branch import ARMBranch, ThumbBranch
from miorom.asm.codecave import CodeCaveFinder
from miorom.asm.trampoline import TrampolineHook


def test_arm_branch_encode_decode():
    # PC = 0x08001000, Target = 0x08001050
    # diff = 0x50 - 8 = 0x48. imm24 = 0x48 >> 2 = 0x12.
    # B instruction opcode = 0xEA000012
    pc = 0x08001000
    target = 0x08001050

    b_bytes = ARMBranch.encode_b(source_pc=pc, target_addr=target, link=False)
    assert b_bytes == b"\x12\x00\x00\xEA"

    decoded_target, link, cond = ARMBranch.decode_b(source_pc=pc, instr_bytes=b_bytes)
    assert decoded_target == target
    assert link is False
    assert cond == 0xE

    # Backward branch: PC = 0x08002000, Target = 0x08001000
    target_back = 0x08001000
    pc_back = 0x08002000
    b_back = ARMBranch.encode_b(source_pc=pc_back, target_addr=target_back)
    decoded_back, _, _ = ARMBranch.decode_b(source_pc=pc_back, instr_bytes=b_back)
    assert decoded_back == target_back


def test_thumb_branch_encode():
    # PC = 0x08001000, Target = 0x08001020
    # diff = 0x20 - 4 = 0x1C. imm11 = 0x1C >> 1 = 0x0E.
    # Opcode = 0xE00E
    pc = 0x08001000
    target = 0x08001020

    b_bytes = ThumbBranch.encode_b(source_pc=pc, target_addr=target)
    assert b_bytes == b"\x0E\xE0"


def test_code_cave_finder():
    data = bytearray(b"\xAA\xBB" + (b"\x00" * 32) + b"\xCC\xDD" + (b"\xFF" * 16))
    caves_zero = CodeCaveFinder.find_caves(bytes(data), min_size=16, filler_byte=0x00, alignment=4)
    assert len(caves_zero) == 1
    assert caves_zero[0].offset == 4 # Aligned to 4
    assert caves_zero[0].size >= 16

    caves_ff = CodeCaveFinder.find_caves(bytes(data), min_size=16, filler_byte=0xFF, alignment=4)
    assert len(caves_ff) == 1


def test_trampoline_hook_arm():
    hook_addr = 0x08005000
    orig_instr = b"\x00\x00\xA0\xE3" # MOV R0, #0
    custom_payload = b"\x01\x10\xA0\xE3" # MOV R1, #1
    cave_addr = 0x08009000

    hook_bytes, cave_bytes = TrampolineHook.create_arm_hook(
        hook_ram_addr=hook_addr,
        original_instr_bytes=orig_instr,
        custom_payload_bytes=custom_payload,
        cave_ram_addr=cave_addr,
    )

    # hook_bytes should be a 4-byte branch to cave_addr
    target, _, _ = ARMBranch.decode_b(hook_addr, hook_bytes)
    assert target == cave_addr

    # cave_bytes structure: custom payload (4B), original instruction (4B), return branch (4B)
    assert len(cave_bytes) == 12
    assert cave_bytes[:4] == custom_payload
    assert cave_bytes[4:8] == orig_instr

    ret_target, _, _ = ARMBranch.decode_b(cave_addr + 8, cave_bytes[8:12])
    assert ret_target == hook_addr + 4
