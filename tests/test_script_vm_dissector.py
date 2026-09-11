"""
Unit tests for ScriptVMDissector, DissectedScriptVM, and automated branch relinking.
"""

import pytest
import struct

from miorom.script.script_dissector import (
    ScriptVMDissector,
    DissectedScriptVM,
    DissectedInstruction,
    VMInstructionDef,
    VMOpcodeType,
)
from miorom.text.charmap import CharMap


# Define a realistic sample VM opcode table for an RPG event script engine
OP_SET_SPEAKER = 0x01   # [0x01, speaker_id] (2 bytes)
OP_SHOW_TEXT   = 0x02   # [0x02, text..., 0x00] (variable length)
OP_BRANCH_REL  = 0x03   # [0x03, signed_s16] (3 bytes, rel to inst start)
OP_JUMP_ABS    = 0x04   # [0x04, target_u16] (3 bytes, abs target)
OP_SWITCH      = 0x05   # [0x05, case_count, target_u16 * count]
OP_WAIT_KEY    = 0x06   # [0x06] (1 byte)
OP_END         = 0xFF   # [0xFF] (1 byte)

SAMPLE_OPCODE_TABLE = {
    OP_SET_SPEAKER: VMInstructionDef(OP_SET_SPEAKER, "SET_SPEAKER", VMOpcodeType.CONTROL, fixed_length=2),
    OP_SHOW_TEXT: VMInstructionDef(OP_SHOW_TEXT, "SHOW_TEXT", VMOpcodeType.TEXT, text_terminator=b"\x00"),
    OP_BRANCH_REL: VMInstructionDef(OP_BRANCH_REL, "BRANCH_REL", VMOpcodeType.BRANCH_REL, fixed_length=3, operand_format="<h"),
    OP_JUMP_ABS: VMInstructionDef(OP_JUMP_ABS, "JUMP_ABS", VMOpcodeType.BRANCH_ABS, fixed_length=3, operand_format="<H"),
    OP_SWITCH: VMInstructionDef(OP_SWITCH, "SWITCH", VMOpcodeType.SWITCH, operand_format="<H"),
    OP_WAIT_KEY: VMInstructionDef(OP_WAIT_KEY, "WAIT_KEY", VMOpcodeType.CONTROL, fixed_length=1),
    OP_END: VMInstructionDef(OP_END, "END", VMOpcodeType.TERMINATOR, fixed_length=1),
}


def test_disassemble_script():
    """Test disassembling an event script with text, relative branch, and jump targets."""
    # Build a simulated event script bytecode
    # 0x00: SET_SPEAKER 1
    # 0x02: SHOW_TEXT "Hello" \x00 (length = 1 + 5 + 1 = 7 bytes) -> ends at 0x09
    # 0x09: WAIT_KEY (1 byte) -> ends at 0x0A
    # 0x0A: BRANCH_REL +6 -> target = 0x0A + 6 = 0x10 (3 bytes) -> ends at 0x0D
    # 0x0D: JUMP_ABS 0x0010 (3 bytes) -> ends at 0x10
    # 0x10: END (1 byte) -> ends at 0x11
    code = bytearray()
    code.extend([OP_SET_SPEAKER, 1])                      # 0x00
    code.extend([OP_SHOW_TEXT])                            # 0x02
    code.extend(b"Hello\x00")                              # 0x03..0x08
    code.extend([OP_WAIT_KEY])                             # 0x09
    code.extend([OP_BRANCH_REL])                           # 0x0A
    code.extend(struct.pack("<h", 6))                      # 0x0B (target = 0x0A + 6 = 0x10)
    code.extend([OP_JUMP_ABS])                             # 0x0D
    code.extend(struct.pack("<H", 0x10))                   # 0x0E (target = 0x10)
    code.extend([OP_END])                                  # 0x10

    script = ScriptVMDissector.disassemble(bytes(code), opcode_table=SAMPLE_OPCODE_TABLE)

    assert len(script.instructions) == 6
    assert script.total_bytes == len(code)

    # Verify instruction 1 (SHOW_TEXT)
    inst_text = script.instructions[1]
    assert inst_text.opcode == OP_SHOW_TEXT
    assert inst_text.text_payload == "Hello"
    assert inst_text.offset == 0x02
    assert inst_text.length == 7

    # Verify instruction 3 (BRANCH_REL)
    inst_branch = script.instructions[3]
    assert inst_branch.opcode == OP_BRANCH_REL
    assert inst_branch.offset == 0x0A
    assert inst_branch.relative_delta == 6
    assert inst_branch.branch_target == 0x10

    # Verify instruction 4 (JUMP_ABS)
    inst_jump = script.instructions[4]
    assert inst_jump.opcode == OP_JUMP_ABS
    assert inst_jump.branch_target == 0x10

    # Test dialogues list & PO export
    dialogues = script.get_dialogues()
    assert dialogues == [(1, "Hello")]

    po_text = script.to_po()
    assert 'msgid "Hello"' in po_text


def test_splice_and_relink_single_expansion():
    """Test expanding a string and verifying automatic branch and jump recalculation."""
    # Bytecode:
    # 0x00: SET_SPEAKER 1 (2 bytes: 0x00..0x01)
    # 0x02: SHOW_TEXT "Hi\x00" (4 bytes: 0x02..0x05)
    # 0x06: BRANCH_REL +6 -> target = 0x06 + 6 = 0x0C (3 bytes: 0x06..0x08)
    # 0x09: JUMP_ABS 0x000C (3 bytes: 0x09..0x0B)
    # 0x0C: END (1 byte at 0x0C)
    code = bytearray()
    code.extend([OP_SET_SPEAKER, 1])
    code.extend([OP_SHOW_TEXT])
    code.extend(b"Hi\x00")
    code.extend([OP_BRANCH_REL])
    code.extend(struct.pack("<h", 6))    # points to END at 0x0C
    code.extend([OP_JUMP_ABS])
    code.extend(struct.pack("<H", 0x0C)) # points to END at 0x0C
    code.extend([OP_END])

    script = ScriptVMDissector.disassemble(bytes(code), opcode_table=SAMPLE_OPCODE_TABLE)

    # Expand "Hi" (4 bytes total: op+payload) to "Greetings traveler!" (21 bytes total) -> +17 bytes delta
    translations = {1: "Greetings traveler!"}
    patched_bytecode = ScriptVMDissector.splice_and_relink(
        bytes(code),
        script,
        translations,
        opcode_table=SAMPLE_OPCODE_TABLE,
    )

    # Verify length expansion: len(code) + 17
    assert len(patched_bytecode) == len(code) + 17

    # Re-disassemble patched bytecode
    patched_script = ScriptVMDissector.disassemble(bytes(patched_bytecode), opcode_table=SAMPLE_OPCODE_TABLE)

    # Instruction 1 text should be updated
    assert patched_script.instructions[1].text_payload == "Greetings traveler!"

    # Target of BRANCH_REL and JUMP_ABS was originally 0x0C.
    # Because of the +17 shift, the target should now be 0x0C + 17 = 29 (0x1D)
    patched_branch = patched_script.instructions[2]
    assert patched_branch.branch_target == 0x0C + 17

    patched_jump = patched_script.instructions[3]
    assert patched_jump.branch_target == 0x0C + 17
    assert patched_bytecode[0x0C + 17] == OP_END

    # Verify the target opcode is indeed OP_END
    end_inst = patched_script.instructions[4]
    assert end_inst.offset == 0x0C + 17
    assert end_inst.opcode == OP_END


def test_splice_and_relink_multiple_expansions_with_switch():
    """Test multiple simultaneous dialogue expansions with a switch/jump table."""
    # Script layout:
    # 0x00: SHOW_TEXT "One\x00" (5 bytes: 0x00..0x04)
    # 0x05: SWITCH case_count=2, targets=[0x13, 0x17] (6 bytes: 0x05..0x0A)
    # 0x0B: SHOW_TEXT "Two\x00" (5 bytes: 0x0B..0x0F)
    # 0x10: JUMP_ABS 0x17 (3 bytes: 0x10..0x12)
    # 0x13: WAIT_KEY (1 byte at 0x13)
    # 0x14: JUMP_ABS 0x17 (3 bytes: 0x14..0x16)
    # 0x17: END (1 byte at 0x17)
    code = bytearray()
    code.extend([OP_SHOW_TEXT])
    code.extend(b"One\x00")                               # 0x00..0x04
    code.extend([OP_SWITCH, 2])                          # 0x05..0x06
    code.extend(struct.pack("<2H", 0x13, 0x17))          # 0x07..0x0A (target 0: WAIT_KEY, target 1: END)
    code.extend([OP_SHOW_TEXT])                          # 0x0B
    code.extend(b"Two\x00")                               # 0x0C..0x0F
    code.extend([OP_JUMP_ABS])                           # 0x10
    code.extend(struct.pack("<H", 0x17))                 # 0x11..0x12 (points to END at 0x17)
    code.extend([OP_WAIT_KEY])                           # 0x13
    code.extend([OP_JUMP_ABS])                           # 0x14
    code.extend(struct.pack("<H", 0x17))                 # 0x15..0x16 (points to END at 0x17)
    code.extend([OP_END])                                # 0x17

    script = ScriptVMDissector.disassemble(bytes(code), opcode_table=SAMPLE_OPCODE_TABLE)

    # Expand both texts:
    # "One" (5 bytes total) -> "First long dialogue" (21 bytes total) -> +16 delta
    # "Two" (5 bytes total) -> "Second even longer dialogue" (29 bytes total) -> +24 delta
    translations = {
        0: "First long dialogue",
        2: "Second even longer dialogue",
    }

    patched_code = ScriptVMDissector.splice_and_relink(
        bytes(code),
        script,
        translations,
        opcode_table=SAMPLE_OPCODE_TABLE,
    )

    patched_script = ScriptVMDissector.disassemble(bytes(patched_code), opcode_table=SAMPLE_OPCODE_TABLE)

    # Verify both dialogues are updated
    assert patched_script.instructions[0].text_payload == "First long dialogue"
    assert patched_script.instructions[2].text_payload == "Second even longer dialogue"

    # Verify SWITCH targets were shifted:
    # Target 0 (WAIT_KEY) was at 0x13. It shifted by +16 (from first text) + 24 (from second text) = +40!
    # Target 1 (END) was at 0x17. It shifted by +16 + 24 = +40!
    switch_inst = patched_script.instructions[1]
    assert switch_inst.switch_targets[0] == 0x13 + 16 + 24
    assert switch_inst.switch_targets[1] == 0x17 + 16 + 24

    # Verify final opcode at shifted target is END
    final_offset = 0x17 + 16 + 24
    assert patched_code[final_offset] == OP_END
