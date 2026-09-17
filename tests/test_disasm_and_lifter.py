import struct

from miorom.asm.disambiguator import ByteClassification, CodeDataDisambiguator
from miorom.asm.disasm import UniversalDisassembler
from miorom.asm.slicer import DataFlowSlicer
from miorom.script.ir import IROp
from miorom.script.lifter import BinaryLifter


def test_universal_disassembler_ppc():
    # Instructions:
    # 0x00: lis r3, 0x8025
    # 0x04: addi r3, r3, 0x1234
    # 0x08: bl 0x80005000
    # 0x0C: blr
    text = bytearray(16)
    struct.pack_into(">I", text, 0, 0x3C608025)
    struct.pack_into(">I", text, 4, 0x38631234)
    # bl to 0x80005000 from 0x80001008 -> diff = 0x00003FF8
    struct.pack_into(">I", text, 8, 0x48003FF9)
    struct.pack_into(">I", text, 12, 0x4E800020)

    instrs = UniversalDisassembler.disassemble(bytes(text), base_address=0x80001000, arch="ppc")
    assert len(instrs) == 4

    assert instrs[0].mnemonic == "lis"
    assert instrs[0].operands == ["r3", "0x8025"]

    assert instrs[1].mnemonic == "addi"
    assert instrs[1].operands == ["r3", "r3", "4660"]

    assert instrs[2].mnemonic == "bl"
    assert instrs[2].is_call is True
    assert instrs[2].target_address == 0x80005000

    assert instrs[3].mnemonic == "blr"
    assert instrs[3].is_return is True

    # Test listing formatting with symbols
    listing = UniversalDisassembler.format_listing(instrs, symbols={0x80005000: "OSReport"})
    assert "<OSReport>" in listing
    assert "blr" in listing


def test_universal_disassembler_arm():
    # 0x00: mov r0, #42
    # 0x04: bl 0x08002000 (from 0x08001004: diff = 0xFF4, imm = 0x3FD)
    # 0x08: bx lr
    text = bytearray(12)
    struct.pack_into("<I", text, 0, 0xE3A0002A)
    struct.pack_into("<I", text, 4, 0xEB0003FD)
    struct.pack_into("<I", text, 8, 0xE12FFF1E)

    instrs = UniversalDisassembler.disassemble(bytes(text), base_address=0x08001000, arch="arm")
    assert len(instrs) == 3
    assert instrs[0].mnemonic == "mov"
    assert instrs[1].mnemonic == "bl"
    assert instrs[1].target_address == 0x08002000
    assert instrs[2].mnemonic == "bx"
    assert instrs[2].is_return is True


def test_code_data_disambiguator():
    # Build synthetic ROM section:
    # 0x00..0x08: Code (li r3, 1; blr)
    # 0x08..0x10: Padding (0x00)
    # 0x10..0x18: Jump Table (pointers to 0x80000000, 0x80000004)
    # 0x18..0x24: String ("MioROM\x00")
    # 0x24..0x28: Rodata (0x12345678)
    rom = bytearray(40)
    struct.pack_into(">I", rom, 0x00, 0x38600001)  # li r3, 1
    struct.pack_into(">I", rom, 0x04, 0x4E800020)  # blr
    # Padding at 0x08..0x10 is 0x00 * 8
    # Jump Table at 0x10:
    struct.pack_into(">I", rom, 0x10, 0x80000000)  # Case 0 points to li r3, 1
    struct.pack_into(">I", rom, 0x14, 0x80000004)  # Case 1 points to blr
    # String at 0x18:
    rom[0x18:0x1F] = b"MioROM\x00"
    # Rodata at 0x20:
    struct.pack_into(">I", rom, 0x20, 0x12345678)

    report = CodeDataDisambiguator.analyze(
        data=bytes(rom),
        base_address=0x80000000,
        entry_points=[0x80000000],
        arch="ppc",
    )

    assert report.total_bytes == 40
    assert "CODE" in report.stats
    assert "PADDING" in report.stats
    assert "JUMP_TABLE" in report.stats
    assert "STRING" in report.stats

    # Check classifications
    classifications = {r.classification for r in report.ranges}
    assert ByteClassification.CODE in classifications
    assert ByteClassification.PADDING in classifications
    assert ByteClassification.JUMP_TABLE in classifications
    assert ByteClassification.STRING in classifications


def test_data_flow_slicer_jump_table():
    # PowerPC Switch-Case block:
    # 0x00: cmplwi r3, 2       ; 3 cases (0, 1, 2)
    # 0x04: bgt loc_default    ; conditional branch to default (0x80000020)
    # 0x08: lis r5, 0x8000     ; table base hi
    # 0x0C: addi r5, r5, 0x0018 ; table base lo (table at 0x80000018)
    # 0x10: mtctr r5           ; dummy move
    # 0x14: bctr               ; indirect jump!
    # 0x18: table entry 0 -> 0x80000030
    # 0x1C: table entry 1 -> 0x80000040
    # 0x20: table entry 2 -> 0x80000050
    # 0x24: default target
    code = bytearray(48)
    struct.pack_into(">I", code, 0x00, 0x28030002)  # cmplwi r3, 2
    # bgt to 0x80000024 -> diff = 0x20, bc opcode 16, bo=12, bi=1 (gt)
    struct.pack_into(">I", code, 0x04, 0x41810020)  # bc 12, 1, 0x20
    struct.pack_into(">I", code, 0x08, 0x3CA08000)  # lis r5, 0x8000
    struct.pack_into(">I", code, 0x0C, 0x38A50018)  # addi r5, r5, 0x18
    struct.pack_into(">I", code, 0x10, 0x7CA903A6)  # mtctr r5
    struct.pack_into(">I", code, 0x14, 0x4E800420)  # bctr

    # Table data at 0x18
    struct.pack_into(">I", code, 0x18, 0x80000030)
    struct.pack_into(">I", code, 0x1C, 0x80000040)
    struct.pack_into(">I", code, 0x20, 0x80000050)

    jts = DataFlowSlicer.find_jump_tables(bytes(code), base_address=0x80000000, arch="ppc")
    assert len(jts) == 1

    jt = jts[0]
    assert jt.jump_address == 0x80000014
    assert jt.table_address == 0x80000018
    assert jt.entry_count == 3
    assert jt.case_targets == [0x80000030, 0x80000040, 0x80000050]
    assert "Jump Table at 0x80000018" in jt.summary()


def test_binary_lifter_to_c():
    # PowerPC function:
    # 0x00: addi r3, r3, 10
    # 0x04: blr
    code = bytearray(8)
    struct.pack_into(">I", code, 0x00, 0x3863000A)  # addi r3, r3, 10
    struct.pack_into(">I", code, 0x04, 0x4E800020)  # blr

    ir_func = BinaryLifter.lift(bytes(code), base_address=0x80001000, arch="ppc", function_name="add_ten")
    assert ir_func.name == "add_ten"
    assert len(ir_func.blocks) == 1

    c_code = BinaryLifter.decompile_to_c(ir_func)
    assert "int add_ten()" in c_code
    assert "r3_1 = r3 + 0xA;" in c_code
    assert "return r3_1;" in c_code


def test_binary_lifter_linear_function_does_not_insert_phi():
    # PowerPC function:
    # 0x00: addi r3, r3, 10
    # 0x04: blr
    code = bytearray(8)
    struct.pack_into(">I", code, 0x00, 0x3863000A)
    struct.pack_into(">I", code, 0x04, 0x4E800020)

    ir_func = BinaryLifter.lift(bytes(code), base_address=0x80001000, arch="ppc")

    assert all(
        ins.op != IROp.PHI
        for block in ir_func.blocks.values()
        for ins in block.instructions
    )


def test_universal_disassembler_mips():
    # MIPS instructions (big-endian):
    # 0x00: addiu $a0, $zero, 42 -> 0x2404002A (li $a0, 42)
    # 0x04: lw $v0, 0($a0)       -> 0x8C820000
    # 0x08: jal 0x80002000       -> 0x0C000800
    # 0x0C: nop                  -> 0x00000000 (delay slot)
    # 0x10: jr $ra               -> 0x03E00008
    text = bytearray(20)
    struct.pack_into(">I", text, 0, 0x2404002A)
    struct.pack_into(">I", text, 4, 0x8C820000)
    struct.pack_into(">I", text, 8, 0x0C000800)
    struct.pack_into(">I", text, 12, 0x00000000)
    struct.pack_into(">I", text, 16, 0x03E00008)

    instrs = UniversalDisassembler.disassemble(bytes(text), base_address=0x80001000, arch="mips", endian=">")
    assert len(instrs) == 5
    assert instrs[0].mnemonic == "li"
    assert instrs[0].operands == ["$a0", "42"]
    assert instrs[1].mnemonic == "lw"
    assert instrs[1].operands == ["$v0", "0($a0)"]
    assert instrs[2].mnemonic == "jal"
    assert instrs[2].is_call is True
    assert instrs[2].target_address == 0x80002000
    assert instrs[3].mnemonic == "nop"
    assert instrs[4].mnemonic == "jr"
    assert instrs[4].is_return is True


def test_binary_lifter_mips_to_c():
    # MIPS function:
    # 0x00: addiu $v0, $a0, 10 -> 0x2482000A
    # 0x04: jr $ra              -> 0x03E00008
    code = bytearray(8)
    struct.pack_into(">I", code, 0, 0x2482000A)
    struct.pack_into(">I", code, 4, 0x03E00008)

    ir_func = BinaryLifter.lift(bytes(code), base_address=0x80001000, arch="mips", endian=">", function_name="mips_add_ten")
    assert ir_func.name == "mips_add_ten"
    c_code = BinaryLifter.decompile_to_c(ir_func)
    assert "int mips_add_ten()" in c_code
    assert "$v0_1 = $a0 + 0xA;" in c_code
    assert "return $v0_1;" in c_code


def test_binary_lifter_mips_conditional_branch_delay_slot_stays_in_branch_block():
    # MIPS: beqz $t0, 0x100C; addiu $t1, $t1, 1 (delay slot); nop; nop
    beq = (0x04 << 26) | (8 << 21) | (0 << 16) | 2
    addiu = (0x09 << 26) | (9 << 21) | (9 << 16) | 1
    code = struct.pack(">IIII", beq, addiu, 0, 0)

    ir_func = BinaryLifter.lift(code, 0x1000, arch="mips", endian=">")
    entry = ir_func.blocks["loc_00001000"]

    add_ins = next(ins for ins in entry.instructions if ins.op == IROp.ADD)
    branch_ins = next(ins for ins in entry.instructions if ins.op == IROp.BRANCH_COND)

    assert add_ins.pc == 0x1004
    assert branch_ins.pc == 0x1000
    assert entry.instructions.index(add_ins) < entry.instructions.index(branch_ins)
    assert "loc_00001004" not in ir_func.blocks
    assert "loc_00001008" in entry.successors
    assert "loc_0000100C" in entry.successors


def test_binary_lifter_mips_jump_and_return_delay_slots_stay_in_branch_block():
    addiu = (0x09 << 26) | (9 << 21) | (9 << 16) | 1
    cases = [
        ((0x02 << 26) | 0x403, IROp.BRANCH),
        ((0x03 << 26) | 0x403, IROp.CALL),
        (0x03E00008, IROp.RETURN),
    ]

    for branch_word, expected_op in cases:
        code = struct.pack(">IIII", branch_word, addiu, 0, 0)
        ir_func = BinaryLifter.lift(code, 0x1000, arch="mips", endian=">")
        entry = ir_func.blocks["loc_00001000"]

        add_ins = next(ins for ins in entry.instructions if ins.op == IROp.ADD)
        control_ins = next(ins for ins in entry.instructions if ins.op == expected_op)

        assert add_ins.pc == 0x1004
        assert control_ins.pc == 0x1000
        assert entry.instructions.index(add_ins) < entry.instructions.index(control_ins)
        assert "loc_00001004" not in ir_func.blocks


def test_binary_lifter_mips_branch_without_available_delay_slot_is_safe():
    beq = (0x04 << 26) | (8 << 21) | (0 << 16) | 2
    code = struct.pack(">I", beq)

    ir_func = BinaryLifter.lift(code, 0x1000, arch="mips", endian=">")
    entry = ir_func.blocks["loc_00001000"]

    assert entry.instructions[0].op == IROp.BRANCH_COND
    assert entry.instructions[0].comment == "MIPS delay slot outside lifted data"


def test_binary_lifter_conditional_branch_cfg_and_cyclomatic_complexity():
    from miorom.diff.bindiff import BinDiffEngine

    # Diamond CFG in Thumb:
    # 0x1000: cmp r0, #0       (0x2800)
    # 0x1002: beq 0x1006       (0xD000: PC+4+0 = 0x1006)
    # 0x1004: movs r1, #1      (0x2101)  <- fall-through branch
    # 0x1006: bx lr            (0x4770)  <- convergence block
    thumb_code = struct.pack("<4H", 0x2800, 0xD000, 0x2101, 0x4770)
    func = BinaryLifter.lift(thumb_code, base_address=0x1000, arch="thumb", function_name="thumb_diamond")

    # 3 basic blocks: entry (1000), fall-through (1004), join (1006)
    assert len(func.blocks) == 3
    b_entry = func.blocks["loc_00001000"]
    b_fall = func.blocks["loc_00001004"]
    b_join = func.blocks["loc_00001006"]

    # Entry block must have 2 successors: branch taken (1006) and fall-through (1004)
    assert "loc_00001006" in b_entry.successors
    assert "loc_00001004" in b_entry.successors
    assert len(b_entry.successors) == 2

    # Fall-through block must NOT be an orphan; its predecessor is entry block
    assert "loc_00001000" in b_fall.predecessors
    assert b_fall.successors == ["loc_00001006"]

    # Join block must have both paths as predecessors
    assert "loc_00001000" in b_join.predecessors
    assert "loc_00001004" in b_join.predecessors
    assert all(ins.op != IROp.PHI for ins in b_join.instructions)

    # Cyclomatic complexity: E - V + 2 = 3 edges - 3 nodes + 2 = 2
    fp = BinDiffEngine.fingerprint_function(thumb_code, 0x1000, 0x1000, arch="thumb")
    assert fp.block_count == 3
    assert fp.edge_count == 3
    assert fp.cyclomatic_complexity == 2


def test_binary_lifter_cmp_and_arm_condition_expression():
    # ARM conditional branch with CMP:
    # 0x1000: cmp r0, #0
    # 0x1004: beq 0x100C
    # 0x1008: mov r1, #1
    # 0x100C: bx lr
    arm_code = struct.pack("<4I", 0xE3500000, 0x0A000000, 0xE3A01001, 0xE12FFF1E)
    func = BinaryLifter.lift(arm_code, base_address=0x1000, arch="arm", function_name="arm_cmp_test")

    b_entry = func.blocks["loc_00001000"]
    # First instruction must be CMP
    cmp_ins = b_entry.instructions[0]
    assert cmp_ins.op == IROp.CMP
    assert str(cmp_ins.args[0]) == "r0"
    assert cmp_ins.args[1] == 0

    # Second instruction must be BRANCH_COND with synthesized condition expression "r0 == 0"
    br_ins = b_entry.instructions[1]
    assert br_ins.op == IROp.BRANCH_COND
    assert br_ins.args == [0x100C, "r0 == 0"]

    # Decompile to C must include synthesized relational condition
    c_code = BinaryLifter.decompile_to_c(func)
    assert "if (r0 == 0) goto loc_0000100C;" in c_code


def test_binary_lifter_inserts_phi_for_arm_loop_back_edge():
    # Loop:
    # 0x1000: mov r0, #5
    # 0x1004: sub r0, r0, #1
    # 0x1008: cmp r0, #0
    # 0x100C: bne 0x1004
    # 0x1010: bx lr
    code = struct.pack(
        "<5I",
        0xE3A00005,
        0xE2400001,
        0xE3500000,
        0x1AFFFFFC,
        0xE12FFF1E,
    )

    ir_func = BinaryLifter.lift(code, 0x1000, arch="arm")
    loop_block = ir_func.blocks["loc_00001004"]

    assert loop_block.predecessors == ["loc_00001000", "loc_00001004"]
    assert loop_block.instructions[0].op == IROp.PHI

    phi_nodes = [ins for ins in loop_block.instructions if ins.op == IROp.PHI]
    assert len(phi_nodes) == 1

    phi = phi_nodes[0]
    assert str(phi.dst) == "r0_3"
    assert len(phi.args) == 2
    assert [(pred, str(var)) for pred, var in phi.args] == [
        ("loc_00001000", "r0_1"),
        ("loc_00001004", "r0_2"),
    ]

    sub_ins = next(ins for ins in loop_block.instructions if ins.op == IROp.SUB)
    assert sub_ins.args[0] == phi.dst
    assert str(sub_ins.args[0]) != "r0_1"
