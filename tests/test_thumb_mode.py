"""Tests for ARM Thumb Mode (16-bit) support in MioROM.

Verifies:
1. UniversalDisassembler._disasm_thumb across all Formats 1-19.
2. BinaryLifter._lift_instruction for Thumb architecture.
3. FunctionPrologueScanner.scan for Thumb 16-bit function prologues.
4. End-to-end disassembly and decompilation of realistic compiled routines.
"""

import struct
import pytest

from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction
from miorom.asm.prologue_scanner import FunctionPrologueScanner
from miorom.script.ir import IROp
from miorom.script.lifter import BinaryLifter


# ==============================================================================
# Format-by-format Disassembly Tests (Pure Python bytes)
# ==============================================================================

def test_thumb_format_1_shift():
    # Format 1: Move shifted register (lsl, lsr, asr)
    # lsl r0, r1, #2  -> 0x0088
    # lsr r2, r3, #4  -> 0x091A
    # asr r4, r5, #6  -> 0x11AC
    code = struct.pack("<3H", 0x0088, 0x091A, 0x11AC)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 3
    assert instrs[0].mnemonic == "lsl"
    assert instrs[0].operands == ["r0", "r1", "#2"]

    assert instrs[1].mnemonic == "lsr"
    assert instrs[1].operands == ["r2", "r3", "#4"]

    assert instrs[2].mnemonic == "asr"
    assert instrs[2].operands == ["r4", "r5", "#6"]


def test_thumb_format_2_add_sub():
    # Format 2: Add/subtract register or 3-bit immediate
    # add r0, r1, r2  -> 0x1888
    # sub r3, r4, #5  -> 0x1F63
    code = struct.pack("<2H", 0x1888, 0x1F63)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 2
    assert instrs[0].mnemonic == "add"
    assert instrs[0].operands == ["r0", "r1", "r2"]

    assert instrs[1].mnemonic == "sub"
    assert instrs[1].operands == ["r3", "r4", "#5"]


def test_thumb_format_3_mov_cmp_add_sub_imm():
    # Format 3: Move/compare/add/subtract 8-bit immediate
    # mov r0, #42 -> 0x202A
    # cmp r1, #10 -> 0x290A
    # add r2, #1  -> 0x3201
    # sub r3, #8  -> 0x3B08
    code = struct.pack("<4H", 0x202A, 0x290A, 0x3201, 0x3B08)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 4
    assert instrs[0].mnemonic == "mov"
    assert instrs[0].operands == ["r0", "#42"]

    assert instrs[1].mnemonic == "cmp"
    assert instrs[1].operands == ["r1", "#10"]

    assert instrs[2].mnemonic == "add"
    assert instrs[2].operands == ["r2", "#1"]

    assert instrs[3].mnemonic == "sub"
    assert instrs[3].operands == ["r3", "#8"]


def test_thumb_format_4_alu():
    # Format 4: ALU operations
    # and r0, r1 -> 0x4008
    # eor r2, r3 -> 0x405A
    # mul r4, r5 -> 0x436C
    # neg r6, r7 -> 0x427E
    # mvn r1, r2 -> 0x43D1
    code = struct.pack("<5H", 0x4008, 0x405A, 0x436C, 0x427E, 0x43D1)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 5
    assert instrs[0].mnemonic == "and"
    assert instrs[0].operands == ["r0", "r1"]

    assert instrs[1].mnemonic == "eor"
    assert instrs[1].operands == ["r2", "r3"]

    assert instrs[2].mnemonic == "mul"
    assert instrs[2].operands == ["r4", "r5"]

    assert instrs[3].mnemonic == "neg"
    assert instrs[3].operands == ["r6", "r7"]

    assert instrs[4].mnemonic == "mvn"
    assert instrs[4].operands == ["r1", "r2"]


def test_thumb_format_5_hi_regs_and_bx():
    # Format 5: High register operations and BX
    # add r8, r1 -> 0x4488
    # cmp r0, lr -> 0x4570
    # mov r1, sp -> 0x4669
    # bx lr      -> 0x4770
    code = struct.pack("<4H", 0x4488, 0x4570, 0x4669, 0x4770)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 4
    assert instrs[0].mnemonic == "add"
    assert instrs[0].operands == ["r8", "r1"]

    assert instrs[1].mnemonic == "cmp"
    assert instrs[1].operands == ["r0", "lr"]

    assert instrs[2].mnemonic == "mov"
    assert instrs[2].operands == ["r1", "sp"]

    assert instrs[3].mnemonic == "bx"
    assert instrs[3].operands == ["lr"]
    assert instrs[3].is_return is True
    assert instrs[3].is_branch is True


def test_thumb_format_6_pc_relative_load():
    # Format 6: PC-relative load
    # ldr r0, [pc, #32] at 0x08000000
    # target = ((0x08000000 + 4) & ~2) + 32 = 0x08000024
    code = struct.pack("<H", 0x4808)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 1
    assert instrs[0].mnemonic == "ldr"
    assert instrs[0].operands == ["r0", "[pc, #32]"]
    assert instrs[0].comment == "=0x08000024"


def test_thumb_format_7_reg_offset_load_store():
    # Format 7: Register offset load/store
    # str r0, [r1, r2] -> 0x5088
    # ldr r3, [r4, r5] -> 0x5963
    # strb r6, [r7, r0]-> 0x543E
    code = struct.pack("<3H", 0x5088, 0x5963, 0x543E)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 3
    assert instrs[0].mnemonic == "str"
    assert instrs[0].operands == ["r0", "[r1, r2]"]

    assert instrs[1].mnemonic == "ldr"
    assert instrs[1].operands == ["r3", "[r4, r5]"]

    assert instrs[2].mnemonic == "strb"
    assert instrs[2].operands == ["r6", "[r7, r0]"]


def test_thumb_format_8_sign_extended_load_store():
    # Format 8: Load/store sign-extended byte/halfword
    # strh r0, [r1, r2] -> 0x5288
    # ldrh r0, [r1, r2] -> 0x5A88
    # ldsb r3, [r4, r5] -> 0x5763
    code = struct.pack("<3H", 0x5288, 0x5A88, 0x5763)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 3
    assert instrs[0].mnemonic == "strh"
    assert instrs[0].operands == ["r0", "[r1, r2]"]

    assert instrs[1].mnemonic == "ldrh"
    assert instrs[1].operands == ["r0", "[r1, r2]"]

    assert instrs[2].mnemonic == "ldsb"
    assert instrs[2].operands == ["r3", "[r4, r5]"]


def test_thumb_format_9_imm_offset_load_store():
    # Format 9: Load/store immediate offset
    # str r0, [r1, #8]  -> 0x6088
    # ldr r2, [r3, #16] -> 0x691A
    # strb r4, [r5, #1] -> 0x706C
    # ldrb r6, [r7]     -> 0x783E (offset 0)
    code = struct.pack("<4H", 0x6088, 0x691A, 0x706C, 0x783E)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 4
    assert instrs[0].mnemonic == "str"
    assert instrs[0].operands == ["r0", "[r1, #8]"]

    assert instrs[1].mnemonic == "ldr"
    assert instrs[1].operands == ["r2", "[r3, #16]"]

    assert instrs[2].mnemonic == "strb"
    assert instrs[2].operands == ["r4", "[r5, #1]"]

    assert instrs[3].mnemonic == "ldrb"
    assert instrs[3].operands == ["r6", "[r7]"]


def test_thumb_format_10_halfword_load_store():
    # Format 10: Halfword load/store
    # strh r2, [r3, #6] -> 0x80DA
    # ldrh r0, [r1, #4] -> 0x8888
    code = struct.pack("<2H", 0x80DA, 0x8888)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 2
    assert instrs[0].mnemonic == "strh"
    assert instrs[0].operands == ["r2", "[r3, #6]"]

    assert instrs[1].mnemonic == "ldrh"
    assert instrs[1].operands == ["r0", "[r1, #4]"]


def test_thumb_format_11_sp_relative_load_store():
    # Format 11: SP-relative load/store
    # str r1, [sp, #12] -> 0x9103
    # ldr r0, [sp, #8]  -> 0x9802
    # ldr r0, [sp]      -> 0x9800 (offset 0)
    code = struct.pack("<3H", 0x9103, 0x9802, 0x9800)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 3
    assert instrs[0].mnemonic == "str"
    assert instrs[0].operands == ["r1", "[sp, #12]"]

    assert instrs[1].mnemonic == "ldr"
    assert instrs[1].operands == ["r0", "[sp, #8]"]

    assert instrs[2].mnemonic == "ldr"
    assert instrs[2].operands == ["r0", "[sp]"]


def test_thumb_format_12_load_address():
    # Format 12: Load address
    # add r0, pc, #8  -> 0xA002
    # add r1, sp, #16 -> 0xA904
    code = struct.pack("<2H", 0xA002, 0xA904)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 2
    assert instrs[0].mnemonic == "add"
    assert instrs[0].operands == ["r0", "pc", "#8"]

    assert instrs[1].mnemonic == "add"
    assert instrs[1].operands == ["r1", "sp", "#16"]


def test_thumb_format_13_add_sub_sp():
    # Format 13: Add offset to SP
    # add sp, #16 -> 0xB004
    # sub sp, #32 -> 0xB088
    code = struct.pack("<2H", 0xB004, 0xB088)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 2
    assert instrs[0].mnemonic == "add"
    assert instrs[0].operands == ["sp", "#16"]

    assert instrs[1].mnemonic == "sub"
    assert instrs[1].operands == ["sp", "#32"]


def test_thumb_format_14_push_pop():
    # Format 14: Push/pop register list
    # push {r4, r5, lr} -> 0xB530 (L=0, R=1, rlist=0x30)
    # pop {r4, r5, pc}  -> 0xBD30 (L=1, R=1, rlist=0x30)
    code = struct.pack("<2H", 0xB530, 0xBD30)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 2
    assert instrs[0].mnemonic == "push"
    assert instrs[0].operands == ["{r4, r5, lr}"]
    assert instrs[0].is_return is False

    assert instrs[1].mnemonic == "pop"
    assert instrs[1].operands == ["{r4, r5, pc}"]
    assert instrs[1].is_return is True
    assert instrs[1].is_branch is True


def test_thumb_format_15_stmia_ldmia():
    # Format 15: Multiple load/store
    # stmia r0!, {r1, r2} -> 0xC006
    # ldmia r3!, {r4, r5} -> 0xCB30
    code = struct.pack("<2H", 0xC006, 0xCB30)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 2
    assert instrs[0].mnemonic == "stmia"
    assert instrs[0].operands == ["r0!", "{r1, r2}"]

    assert instrs[1].mnemonic == "ldmia"
    assert instrs[1].operands == ["r3!", "{r4, r5}"]


def test_thumb_format_16_conditional_branches():
    # Format 16: Conditional branch
    # at 0x08000000:
    # beq to +12 bytes (target = 0x08000000 + 4 + 8 = 0x0800000C, imm8 = 4) -> 0xD004
    # bne to -4 bytes (diff = -4, target = 0x08000002 + 4 - 4 = 0x08000002, imm8 = 0xFE) -> 0xD1FE
    code = struct.pack("<2H", 0xD004, 0xD1FE)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 2
    assert instrs[0].mnemonic == "beq"
    assert instrs[0].target_address == 0x0800000C
    assert instrs[0].is_conditional is True

    assert instrs[1].mnemonic == "bne"
    assert instrs[1].target_address == 0x08000002
    assert instrs[1].is_conditional is True


def test_thumb_format_17_swi():
    # Format 17: Software Interrupt
    # swi 0x06 -> 0xDF06 (Div on GBA BIOS)
    code = struct.pack("<H", 0xDF06)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 1
    assert instrs[0].mnemonic == "swi"
    assert instrs[0].operands == ["0x06"]
    assert instrs[0].is_call is True


def test_thumb_format_18_unconditional_branch():
    # Format 18: Unconditional branch (b)
    # at 0x08000000: target = 0x08000000 + 4 + (10 << 1) = 0x08000018
    # imm11 = 10 -> 0xE00A
    code = struct.pack("<H", 0xE00A)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 1
    assert instrs[0].mnemonic == "b"
    assert instrs[0].target_address == 0x08000018
    assert instrs[0].is_branch is True


def test_thumb_format_19_bl_call():
    # Format 19: Long branch with link (BL) - 32-bit paired halfwords
    # at 0x08000000: call 0x0800000C
    code = struct.pack("<2H", 0xF000, 0xF804)
    instrs = UniversalDisassembler.disassemble(code, base_address=0x08000000, arch="thumb")

    assert len(instrs) == 1
    assert instrs[0].mnemonic == "bl"
    assert instrs[0].target_address == 0x0800000C
    assert instrs[0].is_call is True
    assert len(instrs[0].raw_bytes) == 4


# ==============================================================================
# Function Prologue Scanner Tests
# ==============================================================================

def test_thumb_function_prologue_scanner():
    # A chunk of ROM data containing two Thumb functions:
    # Function 1 at offset 0x04: push {r4-r7, lr} (0xB5F0)
    # Function 2 at offset 0x20: push {r4, lr}    (0xB510)
    rom = bytearray(0x40)
    struct.pack_into("<H", rom, 0x04, 0xB5F0)  # push {r4-r7, lr}
    struct.pack_into("<H", rom, 0x06, 0xB082)  # sub sp, #8
    struct.pack_into("<H", rom, 0x20, 0xB510)  # push {r4, lr}

    funcs = FunctionPrologueScanner.scan(bytes(rom), base_address=0x08000000, arch="thumb")

    assert len(funcs) == 2
    assert funcs[0].address == 0x08000004
    assert funcs[0].architecture == "thumb"
    assert funcs[0].prologue_mnemonic == "push {..., lr}"
    assert funcs[0].confidence >= 0.9

    assert funcs[1].address == 0x08000020
    assert funcs[1].architecture == "thumb"

    # Also test alias "arm_thumb"
    funcs_alias = FunctionPrologueScanner.scan(bytes(rom), base_address=0x08000000, arch="arm_thumb")
    assert len(funcs_alias) == 2


# ==============================================================================
# BinaryLifter SSA IR and C Decompilation Tests
# ==============================================================================

def test_thumb_binary_lifter_arithmetic_and_c():
    # Thumb function:
    # 0x00: mov r0, #10     -> 0x200A
    # 0x02: add r0, r0, #5  -> 0x3005
    # 0x04: sub r1, r0, #2  -> 0x1E81
    # 0x06: mul r0, r1      -> 0x4348
    # 0x08: bx lr           -> 0x4770
    code = struct.pack("<5H", 0x200A, 0x3005, 0x1E81, 0x4348, 0x4770)

    ir_func = BinaryLifter.lift(
        bytes(code),
        base_address=0x08001000,
        arch="thumb",
        function_name="calc_score",
    )

    assert ir_func.name == "calc_score"
    assert len(ir_func.blocks) == 1

    ops = [i.op for i in list(ir_func.blocks.values())[0].instructions]
    assert IROp.ASSIGN in ops
    assert IROp.ADD in ops
    assert IROp.SUB in ops
    assert IROp.MUL in ops
    assert IROp.RETURN in ops

    c_code = BinaryLifter.decompile_to_c(ir_func)
    assert "int calc_score()" in c_code
    assert "r0_1 = 0xA;" in c_code
    assert "return" in c_code


def test_thumb_binary_lifter_call_and_pop_pc():
    # Thumb function with call and epilogue pop {..., pc}:
    # 0x00: push {r4, lr}           -> 0xB510
    # 0x02: mov r0, #1              -> 0x2001
    # 0x04: bl 0x0800100C (diff=4)  -> 0xF000, 0xF800
    # 0x08: pop {r4, pc}            -> 0xBD10
    code = bytearray()
    code.extend(struct.pack("<H", 0xB510))
    code.extend(struct.pack("<H", 0x2001))
    code.extend(struct.pack("<2H", 0xF000, 0xF800))
    code.extend(struct.pack("<H", 0xBD10))

    ir_func = BinaryLifter.lift(
        bytes(code),
        base_address=0x08001000,
        arch="thumb",
        function_name="call_subroutine",
    )

    ops = [i.op for i in list(ir_func.blocks.values())[0].instructions]
    assert IROp.CALL in ops
    assert IROp.RETURN in ops

    c_code = BinaryLifter.decompile_to_c(ir_func)
    assert "int call_subroutine()" in c_code
